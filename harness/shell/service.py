"""Non-interactive shell command processes (opencode: packages/core/src/shell.ts).

Each `create` spawns one shell command, streams its combined stdout/stderr to a file, and returns an id. Callers poll `get`, `wait` for the
terminal state, or read `output` by byte cursor. No session or permission state lives here; the shell tool owns that association.

Deviations: the bus events (Created/Exited/Deleted) are optional callbacks; per-session environments and the plugin `create.before` hook
are replaced by the `before` callback."""

from __future__ import annotations

import asyncio
import os
import signal as signal_mod
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from harness.schema.message import ascending
from harness.shell import select as Select
from harness.tool import output as ToolOutput

EXITED_LIMIT = 25
RETENTION_SECONDS = 7 * 24 * 3600
DIRECTORY = "shell"
KILL_GRACE_SECONDS = 3


class NotFoundError(Exception):
    def __init__(self, id: str) -> None:
        super().__init__(f"Shell {id} not found")
        self.id = id


@dataclass
class ShellInfo:
    id: str
    status: str  # running | exited | timeout | killed
    command: str
    cwd: str
    shell: str
    file: str
    metadata: dict[str, Any]
    started: int
    completed: Optional[int] = None
    pid: Optional[int] = None
    exit: Optional[int] = None
    signal: Optional[str] = None


@dataclass
class Invocation:
    """Mutable: `before` may rewrite any field before the process is spawned."""

    command: str
    cwd: str
    timeout: int
    shell: str
    env: dict[str, str]


@dataclass
class ShellResult:
    info: ShellInfo
    capture: Optional[dict[str, Any]]


@dataclass
class _Active:
    info: ShellInfo
    file: str
    done: asyncio.Future
    proc: Optional[asyncio.subprocess.Process] = None
    size: int = 0
    newlines: int = 0
    timeout_task: Optional[asyncio.Task] = None
    pump: Optional[asyncio.Task] = None
    output_done: asyncio.Event = field(default_factory=asyncio.Event)


def _now() -> int:
    return int(time.time() * 1000)


def _signal_name(code: int) -> Optional[str]:
    if code >= 0:
        return None
    try:
        return signal_mod.Signals(-code).name
    except ValueError:
        return f"SIG{-code}"


def _kill_tree(proc: asyncio.subprocess.Process, force: bool) -> None:
    if proc.returncode is not None:
        return
    pid = proc.pid
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    try:
        os.killpg(os.getpgid(pid), signal_mod.SIGKILL if force else signal_mod.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


class ShellService:
    def __init__(
        self, directory: Path, default_cwd: str, on_event: Optional[Callable[[str, dict[str, Any]], None]] = None,
        output_limits: Optional[ToolOutput.ToolOutput] = None,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.default_cwd = default_cwd
        self.on_event = on_event or (lambda kind, data: None)
        self.max_lines = output_limits.max_lines if output_limits else ToolOutput.MAX_LINES
        self.max_bytes = output_limits.max_bytes if output_limits else ToolOutput.MAX_BYTES
        self._commands: dict[str, _Active] = {}
        self._exit_order: list[str] = []

    # ------------------------------------------------------------------ lookups

    def _require(self, id: str) -> _Active:
        command = self._commands.get(id)
        if not command:
            raise NotFoundError(id)
        return command

    def list(self) -> list[ShellInfo]:
        return [c.info for c in self._commands.values() if c.info.status == "running"]

    def get(self, id: str) -> ShellInfo:
        return self._require(id).info

    async def wait(self, id: str) -> ShellInfo:
        """Resolves at the terminal state. Raises NotFoundError if unknown or removed before it terminated."""
        return await asyncio.shield(self._require(id).done)

    def timeout(self, id: str, duration_ms: int) -> ShellInfo:
        """Replaces the running command's timeout from now; zero clears it."""
        command = self._require(id)
        if command.info.status != "running":
            return command.info
        self._arm_timeout(command, duration_ms)
        return command.info

    # ------------------------------------------------------------------ output

    def output(self, id: str, cursor: int = 0, limit: int = 65536) -> dict[str, Any]:
        command = self._require(id)
        if cursor >= command.size:
            return {"output": "", "cursor": command.size, "size": command.size, "truncated": False}
        start = max(0, cursor)
        length = min(limit, command.size - start)
        try:
            with open(command.file, "rb") as fh:
                fh.seek(start)
                data = fh.read(length)
        except OSError:
            data = b""
        return {"output": data.decode("utf-8", "replace"), "cursor": start + len(data), "size": command.size, "truncated": False}

    async def result(self, started: ShellInfo) -> ShellResult:
        """Terminal state plus a bounded tail of the output. A missing capture stays distinct from the exit status."""
        try:
            info = await self.wait(started.id)
        except NotFoundError:
            info = replace(started, status="killed", completed=_now())
        try:
            latest = self.output(info.id, cursor=2**53)
            page = self.output(info.id, cursor=max(0, latest["size"] - self.max_bytes), limit=self.max_bytes)
            lines = page["output"].split("\n")
            if page["output"].endswith("\n"):
                lines.pop()
            truncated = latest["size"] > self.max_bytes or len(lines) > self.max_lines
            text = "\n".join(lines[-self.max_lines :]) if len(lines) > self.max_lines else page["output"]
            total = self._require(info.id).newlines + (0 if page["output"].endswith("\n") else 1)
            shown = min(len(lines), self.max_lines)
            notice = f"\n\n[showing lines {total - shown + 1}-{total} of {total}; full output saved to {info.file}]" if truncated else ""
            capture: Optional[dict[str, Any]] = {"output": f"{text or '(no output)'}{notice}", "truncated": truncated}
        except NotFoundError:
            capture = None
        return ShellResult(info, capture)

    # ------------------------------------------------------------------ lifecycle

    def _arm_timeout(self, command: _Active, duration_ms: int) -> None:
        if command.timeout_task:
            command.timeout_task.cancel()
            command.timeout_task = None
        if duration_ms == 0 or command.info.status != "running":
            return

        async def fire() -> None:
            await asyncio.sleep(duration_ms / 1000)
            await self._finish(command, "timeout", kill=True)

        command.timeout_task = asyncio.ensure_future(fire())

    async def _finish(self, command: _Active, status: str, exit: Optional[int] = None, sig: Optional[str] = None, kill: bool = False) -> None:
        if command.info.status != "running":
            return
        info = command.info
        command.info = replace(info, status=status, exit=exit if exit is not None else info.exit, signal=sig if sig is not None else info.signal, completed=_now())
        if kill and command.proc:
            _kill_tree(command.proc, force=False)
            try:
                await asyncio.wait_for(command.proc.wait(), KILL_GRACE_SECONDS)
            except asyncio.TimeoutError:
                _kill_tree(command.proc, force=True)
        if command.pump:
            try:
                await asyncio.wait_for(asyncio.shield(command.pump), KILL_GRACE_SECONDS)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001 — a pipe held open by a grandchild must not hang the result
                command.pump.cancel()
        if not command.done.done():
            command.done.set_result(command.info)
        self.on_event("exited", {"id": command.info.id, "status": status, "exit": command.info.exit})
        self._exit_order.append(command.info.id)
        while len(self._exit_order) > EXITED_LIMIT:
            self._remove(self._exit_order[0])
        task, command.timeout_task = command.timeout_task, None
        if task and task is not asyncio.current_task():
            task.cancel()

    async def create(self, command: str, cwd: Optional[str] = None, timeout: int = 0, shell: Optional[str] = None,
                     metadata: Optional[dict[str, Any]] = None, before: Optional[Callable[[Invocation], Awaitable[None]]] = None) -> ShellInfo:
        inv = Invocation(command, cwd or self.default_cwd, timeout or 0, shell or Select.resolve("config"), {**os.environ, "TERM": "xterm-256color", "HARNESS_TERMINAL": "1"})
        if before:
            await before(inv)
        id = "sh_" + ascending()[:12]
        file = str(self.directory / f"{id}.out")
        info = ShellInfo(id, "running", inv.command, inv.cwd, inv.shell, file, metadata or {}, _now())
        kwargs: dict[str, Any] = {}
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        proc = await asyncio.create_subprocess_exec(
            inv.shell, *Select.args(inv.shell, inv.command), cwd=inv.cwd, env=inv.env,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, **kwargs,
        )
        info = replace(info, pid=proc.pid)
        active = _Active(info, file, asyncio.get_running_loop().create_future(), proc)
        self._commands[id] = active

        async def pump() -> None:
            try:
                with open(file, "wb") as fh:
                    assert proc.stdout is not None
                    while chunk := await proc.stdout.read(65536):
                        fh.write(chunk)
                        fh.flush()
                        active.size += len(chunk)
                        active.newlines += chunk.count(b"\n")
            finally:
                active.output_done.set()

        active.pump = asyncio.ensure_future(pump())

        async def reap() -> None:
            code = await proc.wait()
            await self._finish(active, "exited", exit=code if code >= 0 else None, sig=_signal_name(code))

        asyncio.ensure_future(reap())
        self._arm_timeout(active, inv.timeout)
        self.on_event("created", {"info": info})
        await asyncio.sleep(0)
        return active.info

    # ------------------------------------------------------------------ removal

    def _remove(self, id: str) -> None:
        command = self._commands.pop(id, None)
        if id in self._exit_order:
            self._exit_order.remove(id)
        if not command:
            return
        if command.timeout_task:
            command.timeout_task.cancel()
        if not command.done.done():
            command.done.set_exception(NotFoundError(id))
            command.done.exception()  # mark retrieved when nobody waits
        try:
            os.unlink(command.file)
        except OSError:
            pass
        self.on_event("deleted", {"id": id})

    async def remove(self, id: str) -> None:
        """Kills the command if running, forgets it and deletes its output file."""
        command = self._require(id)
        if command.info.status == "running" and command.proc:
            _kill_tree(command.proc, force=True)
        if command.pump and not command.pump.done():
            command.pump.cancel()  # the file must be closed before it can be deleted on Windows
            try:
                await command.pump
            except BaseException:  # noqa: BLE001
                pass
        self._remove(id)

    async def close(self) -> None:
        for command in list(self._commands.values()):
            if command.timeout_task:
                command.timeout_task.cancel()
            if command.info.status == "running" and command.proc:
                _kill_tree(command.proc, force=True)
        self._commands.clear()
        self._exit_order.clear()


def cleanup(directory: Path, retention_seconds: int = RETENTION_SECONDS, now: Optional[float] = None) -> list[str]:
    """Deletes output files left behind (e.g. by a restart) that are older than the retention window."""
    removed: list[str] = []
    cutoff = (now if now is not None else time.time()) - retention_seconds
    if not directory.is_dir():
        return removed
    for project in directory.iterdir():
        if not project.is_dir():
            continue
        for f in project.glob("sh_*.out"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed.append(str(f))
            except OSError:
                pass
    return removed
