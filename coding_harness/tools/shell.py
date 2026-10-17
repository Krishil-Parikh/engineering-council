"""The shell tool: run commands (git, gh, package managers, tests) with timeouts, background mode and permission scanning."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from coding_harness.jobs import Job, kill_tree
from coding_harness.tools.base import MAX_BYTES, MAX_LINES, Tool, ToolContext, ToolFailure, clip_lines
from coding_harness.types import ToolResult

DEFAULT_TIMEOUT_MS = 2 * 60 * 1000
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SUBCOMMAND_TOOLS = {"git", "gh", "npm", "pnpm", "yarn", "bun", "docker", "cargo", "pip", "uv", "poetry", "kubectl", "terraform", "go", "make", "systemctl"}


def pick_shell() -> tuple[list[str], str]:
    """(argv prefix, display name). HARNESS_SHELL overrides; Git Bash is preferred on Windows because models write bash."""
    forced = os.environ.get("HARNESS_SHELL")
    if forced:
        return [forced, "-c"], Path(forced).stem
    if sys.platform == "win32":
        for cand in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
            if Path(cand).exists():
                return [cand, "-c"], "bash (Git Bash)"
        ps = shutil.which("pwsh") or shutil.which("powershell")
        if ps:
            return [ps, "-NoProfile", "-NonInteractive", "-Command"], "PowerShell"
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c"], "cmd"
    return [shutil.which("bash") or "/bin/sh", "-c"], "bash"


def split_commands(command: str) -> list[str]:
    """Split a command line on ; && || | & and newlines, outside quotes."""
    parts, buf, quote, i = [], "", "", 0
    while i < len(command):
        c = command[i]
        if quote:
            buf += c
            if c == quote and command[i - 1] != "\\":
                quote = ""
        elif c in "\"'":
            quote = c
            buf += c
        elif c == "\\" and i + 1 < len(command):
            buf += command[i : i + 2]
            i += 1
        elif c in ";\n|&":
            if buf.strip():
                parts.append(buf.strip())
            buf = ""
            while i + 1 < len(command) and command[i + 1] in "|&":
                i += 1
        else:
            buf += c
        i += 1
    if buf.strip():
        parts.append(buf.strip())
    return parts


def scan_command(command: str, cwd: Path) -> tuple[list[tuple[str, str]], list[Path]]:
    """Per simple command: (resource to match rules against, pattern to remember on 'always'). Also the directories it touches."""
    cmds: list[tuple[str, str]] = []
    dirs: list[Path] = []
    for seg in split_commands(command):
        try:
            toks = shlex.split(seg, posix=True)
        except ValueError:
            toks = seg.split()
        while toks and _ENV_ASSIGN.match(toks[0]):
            toks.pop(0)
        if not toks:
            continue
        head = toks[0]
        resource = " ".join(toks)
        pattern = f"{head} {toks[1]} *" if head in _SUBCOMMAND_TOOLS and len(toks) > 1 and not toks[1].startswith("-") else f"{head} *"
        cmds.append((resource, pattern))
        for t in toks[1:]:
            if t.startswith(("/", "~", "..")) or re.match(r"^[A-Za-z]:[\\/]", t):
                p = Path(os.path.expanduser(t))
                p = p if p.is_absolute() else (cwd / p)
                dirs.append(Path(os.path.normpath(p)))
        if head == "cd" and len(toks) > 1:
            p = Path(os.path.expanduser(toks[1]))
            dirs.append(Path(os.path.normpath(p if p.is_absolute() else cwd / p)))
    return cmds, dirs


def _tail(text: str, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> tuple[str, bool]:
    return clip_lines(text, max_lines, max_bytes, tail=True)


class ShellTool(Tool):
    name = "shell"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command string to execute"},
            "workdir": {"type": "string", "description": "Working directory to run in. Defaults to the current working directory. Prefer this over 'cd' inside the command."},
            "timeout": {"type": "integer", "description": f"Timeout in milliseconds. 0 disables it. Defaults to {DEFAULT_TIMEOUT_MS} for foreground commands; background commands have none by default."},
            "background": {"type": "boolean", "description": "Run in the background and return immediately (dev servers, long builds). You are notified when it finishes; do NOT poll."},
        },
        "required": ["command"],
    }

    def description(self, ctx: Any = None) -> str:
        argv, name = pick_shell()
        plat = {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, "Linux")
        return (
            f"Execute a shell command and return its output. Commands run on {plat} using {name}. Quote paths containing spaces. "
            "Prefer the dedicated read/edit/write/glob/grep tools over cat, sed, find or grep. Use this for git, gh (GitHub CLI), "
            "package managers, builds and tests. When output is large the full result is saved to a file and the tail is returned. "
            "Commands never read from a terminal, so pass non-interactive flags. Background commands return immediately and you are "
            "notified when they finish."
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        command: str = args["command"]
        cwd = ctx.workspace.resolve(args["workdir"], ctx.cwd) if args.get("workdir") else ctx.cwd
        if not cwd.is_dir():
            raise ToolFailure(f"Working directory does not exist: {cwd}")
        await ctx.authorize_path(cwd, "directory")
        cmds, dirs = scan_command(command, cwd)
        outside = sorted({d.as_posix() for d in dirs if not ctx.workspace.inside(d)})
        if outside:
            await ctx.permit("external_directory", [f"{d}/*" for d in outside])
        if cmds:
            await ctx.permit("shell", [c for c, _ in cmds], save=list(dict.fromkeys(p for _, p in cmds)))
        background = bool(args.get("background"))
        timeout_ms = args.get("timeout")
        timeout = (0 if background else DEFAULT_TIMEOUT_MS) if timeout_ms is None else int(timeout_ms)

        argv, _ = pick_shell()
        job_id = ctx.jobs.next_id("shell")
        out_file = ctx.workspace.output_dir / f"{job_id}_{os.urandom(3).hex()}.log"
        env = {
            **os.environ, "AGENT": "1", "CI": os.environ.get("CI", "1"), "NO_COLOR": "1", "TERM": "dumb",
            "GIT_PAGER": "cat", "PAGER": "cat", "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true", "EDITOR": "true",
            "COUNCIL_SESSION_ID": ctx.session_id, **ctx.env,
        }
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        handle = open(out_file, "wb")
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, command, cwd=str(cwd), env=env, stdin=asyncio.subprocess.DEVNULL, stdout=handle, stderr=asyncio.subprocess.STDOUT, **kwargs
            )
        except OSError as exc:
            handle.close()
            raise ToolFailure(f"Unable to start the shell: {exc}") from None
        finally:
            pass
        job = ctx.jobs.add(Job(job_id, "shell", command, file=str(out_file), process=proc))
        ctx.emit("shell_start", {"id": job_id, "command": command})

        def output_text() -> str:
            try:
                return ANSI.sub("", out_file.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                return ""

        async def waiter() -> int:
            code = await proc.wait()
            handle.close()
            return code

        if background:
            async def watch() -> None:
                code = await waiter()
                body, _ = _tail(output_text(), 200, 12 * 1024)
                ctx.jobs.finish(
                    job, "completed" if code == 0 else "error",
                    f"Background command `{command}` (shell ID: {job_id}) finished with exit code {code}.\n\nOutput (tail):\n{body}\n\nFull output: {out_file}", code,
                )

            job.task = asyncio.create_task(watch())
            return ToolResult(
                f"Command moved to the background (shell ID: {job_id}).\nOutput is streaming to: {out_file}\n"
                "You will be notified automatically when it finishes. Do NOT poll for completion; keep working on anything that does not depend on it.",
                title=command, metadata={"status": "running", "shellID": job_id, "file": str(out_file)},
            )

        timed_out = False
        try:
            if timeout > 0:
                code = await asyncio.wait_for(waiter(), timeout / 1000)
            else:
                code = await waiter()
        except asyncio.TimeoutError:
            timed_out = True
            kill_tree(proc)
            code = await waiter()
        except asyncio.CancelledError:
            kill_tree(proc)
            handle.close()
            job.status = "cancelled"
            raise
        job.status, job.exit = ("error" if code else "completed"), code
        text = output_text()
        body, cut = _tail(text)
        notes = []
        if cut:
            notes.append(f"(Output truncated: showing the last part. Full output: {out_file})")
        if timed_out:
            notes.append(f"Command exceeded the timeout of {timeout} ms and was stopped. Retry with a larger timeout or run it in the background.")
        elif code != 0:
            notes.append(f"Command exited with code {code}.")
        out = "\n".join(x for x in [body.rstrip("\n"), *notes] if x) or "(no output)"
        return ToolResult(out, title=command, is_error=False, metadata={"exit": code, "timeout": timed_out, "truncated": cut, "shellID": job_id})
