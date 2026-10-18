"""The shell tool (opencode: tool/plugin/shell.ts).

Foreground commands run under a job the session blocks on; if the session is signalled (`JobService.background_all`) or the call asked for
`background`, the command keeps running and a synthetic message with its output is added to the session when it finishes.

`deps.extras` supplies "shell" (ShellService), "jobs" (JobService) and optionally "synthetic" (a callable
`(session_id, text, description, metadata)` that admits the completion message and wakes the session; default: append to the store)."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Optional

from pydantic import BaseModel, Field

from harness.file_access import resolve_path
from harness.job import JobService
from harness.schema.message import Synthetic, TextContent
from harness.shell import parse as ShellParse
from harness.shell import result as ShellResultFmt
from harness.shell import select as Select
from harness.shell.service import Invocation, NotFoundError, ShellService
from harness.tool.builtin.deps import ToolDeps
from harness.tool.info import ToolContext, ToolError, ToolInfo, ToolResult

NAME = "shell"
DEFAULT_TIMEOUT_MS = 2 * 60 * 1000

BACKGROUND_INSTRUCTION = (
    "You will be notified automatically when the command finishes. The notification will include the command's output. Unless the user explicitly asks "
    "otherwise, DO NOT poll for completion, even if you need the final result to continue. Repeatedly sleeping and reading or searching the output file "
    "is polling, not useful work. You may read the current output if it lets you do useful work now, but do not repeatedly check it while waiting for the "
    "command to finish. Keep working on anything that does not depend on the result. If you have nothing else to do, end your response; you will be "
    "resumed automatically when the command finishes."
)
OS_NAME = {"darwin": "macOS", "win32": "Windows", "linux": "Linux"}.get(sys.platform, sys.platform)


def description(shell: Optional[str] = None) -> str:
    return " ".join(
        ["Execute a shell command and return its output."]
        + ([f"Commands run on {OS_NAME} using {shell}."] if shell else [])
        + [
            "Quote file paths containing spaces or special characters.",
            "Prefer dedicated tools over shell commands when possible.",
            "When output is large, the full result is saved to a file and a truncated preview is returned.",
            "Rely on automatic truncation unless filtering the output is more useful.",
            "Commands accept an optional timeout, background commands have no timeout by default.",
            "Background commands return immediately, and you will be notified when they complete.",
        ]
    )


class Input(BaseModel):
    command: str = Field(description="Shell command string to execute")
    workdir: Optional[str] = Field(
        default=None,
        description="Working directory to execute the command in. Defaults to the current working directory. When possible, avoid changing directories in the command and set the working directory here instead.",
    )
    timeout: Optional[int] = Field(
        default=None, ge=0,
        description=f"Timeout in milliseconds. Set to 0 to disable the timeout. Defaults to {DEFAULT_TIMEOUT_MS} for foreground commands. Background commands have no timeout by default.",
    )
    background: Optional[bool] = Field(
        default=None,
        description="Run the command in the background and return immediately (useful for dev servers and long-running builds). You do not need to use '&' at the end of the command when using this parameter. You will be notified when it completes. DO NOT poll for completion.",
    )


def _messages(out: dict[str, Any]) -> list[str]:
    note = BACKGROUND_INSTRUCTION if out.get("status") == "running" else ShellResultFmt.notice(_as_output(out))
    return ([out["output"]] if out.get("output") else []) + ([note] if note else [])


def _as_output(out: dict[str, Any]) -> ShellResultFmt.Output:
    return ShellResultFmt.Output(out.get("output", ""), out.get("truncated", False), out.get("exit"), out.get("signal"), out.get("timeout"))


def _tool_result(out: dict[str, Any]) -> ToolResult:
    meta: dict[str, Any] = {"status": out.get("status"), **ShellResultFmt.metadata(_as_output(out))}
    if out.get("shellID") is not None:
        meta["shellID"] = out["shellID"]
    return ToolResult(content=[TextContent(text=t) for t in _messages(out)], output=out, metadata=meta)


def _background_result(shell_id: str, file: str) -> dict[str, Any]:
    return {"output": f"Command moved to the background (shell ID: {shell_id}).\nOutput is streaming to: {file}", "shellID": shell_id, "truncated": False, "status": "running"}


def make(deps: ToolDeps) -> ToolInfo:
    shell: ShellService = deps.extras["shell"]
    jobs: JobService = deps.extras["jobs"]

    def synthetic(session_id: str, text: str, description_: str, metadata: dict[str, Any]) -> None:
        hook = deps.extras.get("synthetic")
        if hook:
            hook(session_id, text, description_, metadata)
        else:
            deps.store.add(session_id, Synthetic(text=text, description=description_, metadata=metadata))

    async def prepare(inv: Invocation, ctx: ToolContext) -> int:
        target = deps.access.resolve(inv.cwd, "directory")
        inv.cwd = target.absolute
        try:
            parsed = ShellParse.scan(inv.command, inv.shell, target.absolute)
        except ShellParse.ScanError as exc:
            raise ToolError(str(exc)) from None
        directories = [deps.access.resolve(resolve_path(target.absolute, d), "directory") for d in parsed.directories]
        await deps.access.authorize_external([target, *directories], deps.invocation(ctx))
        if parsed.commands:
            await deps.assert_permission(ctx, NAME, [c["resource"] for c in parsed.commands], save=[c["save"] for c in parsed.commands])
        # Approval can outlive the directory, so validate immediately before spawning.
        if not os.path.exists(target.absolute):
            raise ToolError(f"Working directory does not exist: {target.absolute}")
        if not os.path.isdir(target.absolute):
            raise ToolError(f"Working directory is not a directory: {target.absolute}")
        return inv.timeout

    def notify_when_done(session_id: str, job_id: str, shell_id: str, command: str, settled: asyncio.Future) -> None:
        async def run() -> None:
            waited = await jobs.wait(job_id)
            info = waited.info
            if not info or info.status == "running":
                return
            out = await settled if info.status == "completed" else None
            text = "\n\n".join(_messages(out)) if out else (info.error or "Command failed") if info.status == "error" else "Cancelled"
            note = ShellResultFmt.notification(shell_id, command, info.status, text, job_id=job_id, output=_as_output(out) if out else None)
            synthetic(session_id, note["text"], command, note["metadata"])
            if info.notification_id:
                jobs.complete_background(info.notification_id)

        task = asyncio.ensure_future(run())
        deps.extras.setdefault("_background_tasks", set()).add(task)
        task.add_done_callback(lambda t: deps.extras["_background_tasks"].discard(t))

    async def execute(inp: Input, ctx: ToolContext) -> ToolResult:
        timeout = inp.timeout if inp.timeout is not None else (0 if inp.background is True else DEFAULT_TIMEOUT_MS)
        final_timeout = timeout

        async def before(inv: Invocation) -> None:
            nonlocal final_timeout
            inv.env["AGENT"] = "1"
            inv.env["HARNESS"] = "1"
            inv.env.setdefault("AI_AGENT", "harness")
            inv.env["HARNESS_SESSION_ID"] = ctx.session_id
            final_timeout = await prepare(inv, ctx)

        try:
            info = await shell.create(inp.command, inp.workdir, timeout, Select.resolve("compat"), {"sessionID": ctx.session_id}, before)
            ctx.progress({"shellID": info.id})
            settled: asyncio.Future = asyncio.get_running_loop().create_future()

            async def run() -> str:
                try:
                    res = await shell.result(info)
                except asyncio.CancelledError:
                    try:
                        await shell.remove(info.id)
                    except NotFoundError:
                        pass
                    raise
                if res.capture is None:
                    raise NotFoundError(info.id)
                out = vars(ShellResultFmt.output_of(res.info, res.capture)).copy()
                if out.get("timeout"):
                    out["output"] += f"\n\nCommand exceeded timeout of {final_timeout} ms. Retry with a larger timeout if the command is expected to take longer."
                out["status"] = "completed"
                if not settled.done():
                    settled.set_result(out)
                return "\n\n".join(_messages(out))

            job = await jobs.start(info.id, NAME, run, title=info.command, metadata={"sessionID": ctx.session_id, "shellID": info.id},
                                   recovery={"kind": "shell", "sessionID": ctx.session_id, "shellID": info.id, "command": info.command})
            if inp.background is True:
                jobs.background(job.id)
                notify_when_done(ctx.session_id, job.id, info.id, info.command, settled)
                return _tool_result(_background_result(info.id, info.file))
            try:
                result = await jobs.block(job.id, ctx.session_id)
            except asyncio.CancelledError:
                await jobs.cancel(job.id)
                raise
            if result and result.type == "backgrounded":
                shell.timeout(info.id, 0)
                notify_when_done(ctx.session_id, job.id, info.id, info.command, settled)
                return _tool_result(_background_result(info.id, info.file))
            if result and result.info.status == "error":
                raise ToolError(f"Unable to execute command: {inp.command}: {result.info.error or 'Command failed'}")
            if result and result.info.status == "cancelled":
                raise ToolError(f"Unable to execute command: {inp.command}: Command cancelled")
            return _tool_result(await settled)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001
            from harness.permission import BlockedError, CorrectedError, DeclinedError

            if isinstance(exc, (DeclinedError, CorrectedError, BlockedError)):
                raise
            raise ToolError(f"Unable to execute command: {inp.command}: {exc}", exc) from None

    return ToolInfo(NAME, description(Select.name(Select.resolve("compat"))), Input, execute)
