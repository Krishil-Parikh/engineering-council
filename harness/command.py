"""Slash commands (opencode: packages/core/src/command.ts, config/plugin/command.ts, plugin/command.ts).

A command is a name with a prompt behind it. Running `/init focus on the build` expands the command's template with the arguments and sends the
result to the session as an ordinary prompt. Commands come from three places, later ones replacing earlier ones:

  - built in: `init` (guided AGENTS.md setup) and `review` (review uncommitted changes, a commit, a branch or a pull request);
  - markdown files under `command/` or `commands/` in any configuration directory (`commands/review/security.md` is `/review/security`);
  - the `commands` map of a configuration document.

Templates: `$1`, `$2`... are the arguments (the last placeholder takes the rest of the line), `$ARGUMENTS` is the whole input, and
!`some command` is replaced by that command's output. Text that uses none of these has the input appended. A command can name an agent and a
model to switch to, or run as a background subagent in a child session instead of in the current one."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from harness.config import markdown
from harness.config import service as cfg
from harness.schema import message as M
from harness.shell import select as Select
from harness.util import fs

log = logging.getLogger("harness.command")

ARGS_RE = re.compile(r"(?:\[Image\s+\d+\]|\"[^\"]*\"|'[^']*'|[^\s\"']+)", re.I)
PLACEHOLDER_RE = re.compile(r"\$(\d+)")
QUOTE_TRIM_RE = re.compile(r"^[\"']|[\"']$")
SHELL_RE = re.compile(r"!`([^`]+)`")
SOURCE_DIRS = ("command", "commands")
SUBAGENT_PREAMBLE = "You are a subagent spawned by another session."


class CommandError(Exception):
    pass


class NotFoundError(CommandError):
    def __init__(self, command: str) -> None:
        super().__init__(f"Command not found: {command}")
        self.command = command


class ExecutionError(CommandError):
    def __init__(self, command: str, message: str) -> None:
        super().__init__(message)
        self.command = command


@dataclass
class Invocation:
    session_id: str
    text: str  # what the user typed after the command name
    delivery: str = "steer"  # "steer": into the run in progress, or start one; "queue": after it


@dataclass
class Definition:
    name: str
    execute: Callable[[Invocation], Awaitable[Optional[bool]]]
    description: Optional[str] = None


@dataclass
class CommandInfo:
    name: str
    description: Optional[str] = None


def parse_arguments(text: str) -> list[str]:
    return [QUOTE_TRIM_RE.sub("", a) for a in ARGS_RE.findall(text)]


def append_input(template: str, text: str) -> str:
    """How the built-in commands take their argument: in place of $ARGUMENTS if the template has it, otherwise after the template."""
    value = text.strip()
    if "$ARGUMENTS" in template:
        return template.replace("$ARGUMENTS", value)
    return "\n\n".join(p for p in (template, value) if p)


async def run_shell_text(source: str, cwd: Path, shell: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        shell, *Select.args(shell, source), cwd=str(cwd), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return out.decode("utf-8", "replace")


async def evaluate_template(template: str, text: str, cwd: Path, shell: Optional[str] = None,
                            run: Callable[[str, Path, str], Awaitable[str]] = run_shell_text) -> str:
    """$1.. and $ARGUMENTS are filled from the input, then each !`command` is replaced by its output."""
    args = parse_arguments(text)
    placeholders = PLACEHOLDER_RE.findall(template)
    last = max([0, *[int(p) for p in placeholders]])

    def fill(match: re.Match) -> str:
        position = int(match.group(1))
        index = position - 1
        if index >= len(args):
            return ""
        if position == last:
            return " ".join(args[index:])
        return args[index]

    expanded = PLACEHOLDER_RE.sub(fill, template).replace("$ARGUMENTS", text)
    result = f"{expanded}\n\n{text}".strip() if not placeholders and "$ARGUMENTS" not in template and text.strip() else expanded.strip()
    matches = list(SHELL_RE.finditer(result))
    if not matches:
        return result
    shell = shell or Select.resolve("config")
    sem = asyncio.Semaphore(2)

    async def one(source: str) -> str:
        async with sem:
            try:
                return await run(source, cwd, shell)
            except OSError as exc:
                raise CommandError(f"Shell interpolation failed for {json.dumps(source)}: {exc}") from None

    outputs = iter(await asyncio.gather(*(one(m.group(1)) for m in matches)))
    return SHELL_RE.sub(lambda _m: next(outputs), result)


# ------------------------------------------------------------------ loading

def command_name(directory: Path, filepath: Path) -> str:
    rel = filepath.relative_to(directory).as_posix()
    return re.sub(r"\.md$", "", re.sub(r"^(command|commands)/", "", rel))


def load_directory(directory: Path) -> dict[str, dict[str, Any]]:
    """Commands from `{command,commands}/**/*.md` under a configuration directory."""
    out: dict[str, dict[str, Any]] = {}
    files = sorted(fs.scan("{command,commands}/**/*.md", directory, absolute=True, include="file", dot=True))
    for filepath in files:
        content = fs.read_text_safe(filepath)
        if content is None:
            continue
        parsed = markdown.parse_option(content)
        if parsed is None:
            continue
        info = dict(parsed.data)
        info["template"] = parsed.content.strip()
        out[command_name(directory, Path(filepath))] = info
    return out


def load_entries(entries: list[cfg.Entry]) -> dict[str, dict[str, Any]]:
    """Every command in the configuration, lowest priority first, so a later definition replaces an earlier one."""
    merged: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if isinstance(entry, cfg.Document):
            for name, info in (entry.info.get("commands") or {}).items():
                if isinstance(info, dict) and isinstance(info.get("template"), str):
                    merged[name] = info
        elif isinstance(entry, cfg.Directory):
            merged.update(load_directory(entry.path))
    return merged


def model_ref(value: Any) -> Optional[M.ModelRef]:
    """`{"providerID": "google", "model": "gemini-x", "variant": "high"}` or "google/gemini-x"."""
    if isinstance(value, dict) and value.get("model"):
        return M.ModelRef(provider_id=str(value.get("providerID") or value.get("provider_id") or ""), id=str(value["model"]), variant=value.get("variant"))
    if isinstance(value, str) and "/" in value:
        provider, _, rest = value.partition("/")
        model, _, variant = rest.partition("#")
        return M.ModelRef(provider_id=provider, id=model, variant=variant or None)
    return None


# ------------------------------------------------------------------ the service

class CommandService:
    """Needs the session service (to prompt, switch agent and model, create child sessions) and the agent registry. `subagent_jobs`
    (harness.tool.builtin.subagent.SubagentJobs) runs commands that are marked as subagents."""

    def __init__(self, sessions: Any, agents: Any, location_directory: Path, config: Optional[cfg.Config] = None, project_directory: Optional[Path] = None,
                 subagent_jobs: Any = None, shell: Optional[str] = None) -> None:
        self.sessions, self.agents, self.directory = sessions, agents, Path(location_directory)
        self.config, self.project_directory = config, Path(project_directory or location_directory)
        self.subagent_jobs, self.shell = subagent_jobs, shell
        self._transforms: list[Callable[[dict[str, Definition]], None]] = []
        self._defs: Optional[dict[str, Definition]] = None

    # ---- editing
    def transform(self, fn: Callable[[dict[str, Definition]], None]) -> None:
        """Register a change to the command set (add, replace, remove). Applied in order whenever the set is (re)built."""
        self._transforms.append(fn)
        self._defs = None

    def reload(self) -> None:
        """Re-reads the configuration (a command file was added or changed) and rebuilds the command set."""
        if self.config is not None:
            self.config.reload()
        self._defs = None

    def _build(self) -> dict[str, Definition]:
        defs: dict[str, Definition] = {}
        for builtin in self._builtins():
            defs[builtin.name] = builtin
        if self.config is not None:
            for name, info in load_entries(self.config.entries()).items():
                defs[name] = self._from_config(name, info)
        for fn in self._transforms:
            fn(defs)
        return defs

    def _all(self) -> dict[str, Definition]:
        if self._defs is None:
            self._defs = self._build()
        return self._defs

    # ---- reading
    def get(self, name: str) -> Optional[CommandInfo]:
        d = self._all().get(name)
        return CommandInfo(d.name, d.description) if d else None

    def list(self) -> list[CommandInfo]:
        return [CommandInfo(d.name, d.description) for d in self._all().values()]

    async def execute(self, name: str, invocation: Invocation) -> bool:
        """Runs the command. Returns True if a prompt was added to the session (the caller resumes it), False if the command ran elsewhere
        (as a background subagent). Raises NotFoundError or ExecutionError."""
        d = self._all().get(name)
        if d is None:
            raise NotFoundError(name)
        try:
            return (await d.execute(invocation)) is not False
        except Exception as exc:  # noqa: BLE001 - whatever went wrong inside a command is an execution error
            log.error("command %s failed: %s", name, exc)
            raise ExecutionError(name, str(exc) or "Command execution failed") from exc

    # ---- definitions
    def _builtins(self) -> list[Definition]:
        here = Path(__file__).parent / "commands"

        def prompt_command(name: str, description: str) -> Definition:
            template = (here / f"{name}.txt").read_text(encoding="utf-8").replace("${path}", str(self.project_directory))

            async def run(inv: Invocation) -> None:
                self.sessions.prompt(inv.session_id, append_input(template, inv.text))

            return Definition(name, run, description)

        return [
            prompt_command("init", "guided AGENTS.md setup"),
            prompt_command("review", "review changes [commit|branch|pr], defaults to uncommitted"),
        ]

    def _from_config(self, name: str, info: dict[str, Any]) -> Definition:
        subagent = info.get("subagent", info.get("subtask"))
        agent_id = info.get("agent")
        model = model_ref(info.get("model"))

        async def run(inv: Invocation) -> None:
            command_agent = self.agents.get(agent_id) if agent_id else None
            chosen_model = model or (command_agent.model if command_agent else None)
            text = await evaluate_template(str(info["template"]), inv.text, self.directory, self.shell)
            if subagent if subagent is not None else (command_agent is not None and command_agent.mode == "subagent"):
                await self._run_as_subagent(name, info, inv, agent_id, chosen_model, text)
                return False
            session = self.sessions.get(inv.session_id)
            if agent_id and session.agent != agent_id:
                self.sessions.switch_agent(inv.session_id, agent_id)
            if chosen_model is not None:
                self.sessions.switch_model(inv.session_id, chosen_model)
            self.sessions.prompt(inv.session_id, text)

        return Definition(name, run, info.get("description"))

    async def _run_as_subagent(self, name: str, info: dict[str, Any], inv: Invocation, agent_id: Optional[str], model: Optional[M.ModelRef], text: str) -> None:
        if self.subagent_jobs is None:
            raise CommandError(f"/{name} runs as a subagent, but subagents are not available here")
        parent = self.sessions.get(inv.session_id)
        selected = self.agents.resolve(agent_id or parent.agent)
        if selected is None:
            raise CommandError(f"Unknown agent: {agent_id or parent.agent}")
        parent_model = M.ModelRef(**parent.model) if parent.model else None
        child = self.sessions.create(parent_id=parent.id, title=info.get("description") or name, agent=selected.id, model=model or selected.model or parent_model)
        self.sessions.prompt(child.id, "\n".join([SUBAGENT_PREAMBLE, text]))
        recovery = {"kind": "subagent", "parentSessionID": parent.id, "childSessionID": child.id, "agent": selected.id, "description": info.get("description") or name}
        job = await self.subagent_jobs.start(recovery)
        self.subagent_jobs.background(recovery, job)
