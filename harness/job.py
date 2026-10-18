"""Background-able jobs (opencode: packages/core/src/job.ts).

A job is started once under an id, can be awaited (`wait`), blocked on by a session (`block`, which returns early when the job is moved to
the background), cancelled, and keeps a bounded history of consumed results. Jobs that carry a `recovery` record also own a pending
"background notification" until the caller acknowledges it with `complete_background`.

Deviation: opencode persists those notification markers in its KV so a restarted process can re-deliver them. Ours are process-local;
a restart also loses the child processes they track, so there is nothing left to recover."""

from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable, Optional

from harness.schema.message import new_message_id

COMPLETED_LIMIT = 25


@dataclass
class Info:
    id: str
    type: str
    status: str  # running | completed | error | cancelled
    started_at: int
    title: Optional[str] = None
    completed_at: Optional[int] = None
    output: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    notification_id: Optional[str] = None


@dataclass
class WaitResult:
    timed_out: bool
    info: Optional[Info] = None


@dataclass
class BlockResult:
    type: str  # finished | backgrounded
    info: Info


@dataclass
class _Active:
    info: Info
    done: asyncio.Future
    backgrounded: asyncio.Future
    task: Optional[asyncio.Task] = None
    blocking: dict[str, int] = field(default_factory=dict)
    is_backgrounded: bool = False
    consumed: bool = False
    recovery: Optional[dict[str, Any]] = None


def _snapshot(job: _Active) -> Info:
    return replace(job.info, metadata=dict(job.info.metadata) if job.info.metadata else job.info.metadata)


def _error_text(exc: BaseException) -> str:
    parts = []
    cur: Optional[BaseException] = exc
    while cur is not None:
        text = str(cur) or type(cur).__name__
        if not parts or text != parts[-1]:
            parts.append(text)
        cur = cur.__cause__
    return parts[0] if len(parts) == 1 else parts[0] + "\nCaused by: " + "\nCaused by: ".join(parts[1:])


def _now() -> int:
    return int(time.time() * 1000)


def _resolve(fut: asyncio.Future, value: Any) -> None:
    if not fut.done():
        fut.set_result(value)


class JobService:
    def __init__(self) -> None:
        self._jobs: dict[str, _Active] = {}
        self._pending: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ internals

    def _consume(self, job_id: str, job: _Active) -> None:
        cur = self._jobs.get(job_id)
        if cur is not job or job.info.status == "running" or job.consumed:
            return
        job.consumed = True
        del self._jobs[job_id]  # history is ordered by first consumption
        self._jobs[job_id] = job
        completed = [k for k, j in self._jobs.items() if j.consumed and not j.info.notification_id]
        for k in completed[:-COMPLETED_LIMIT] if len(completed) > COMPLETED_LIMIT else []:
            del self._jobs[k]

    def _persist(self, job: _Active) -> None:
        if job.recovery and job.info.notification_id:
            self._pending[job.info.notification_id] = {
                "id": job.info.id, "notificationID": job.info.notification_id, "recovery": job.recovery, "status": job.info.status,
                **({"output": job.info.output} if job.info.output is not None else {}),
                **({"error": job.info.error} if job.info.error is not None else {}),
            }

    def _settle(self, job: _Active, status: str, output: Optional[str] = None, error: Optional[str] = None) -> None:
        if job.info.status != "running":
            return
        job.blocking.clear()
        job.info = replace(job.info, status=status, completed_at=_now(), output=output if status == "completed" else None, error=error)
        if status != "cancelled":
            self._persist(job)
        _resolve(job.done, _snapshot(job))

    async def _drive(self, job: _Active, run: Callable[[], Awaitable[str]]) -> None:
        try:
            self._settle(job, "completed", output=await run())
        except asyncio.CancelledError:
            self._settle(job, "cancelled")
            raise
        except BaseException as exc:  # noqa: BLE001
            traceback.clear_frames(exc.__traceback__)
            self._settle(job, "error", error=_error_text(exc))

    # ------------------------------------------------------------------ interface

    def get(self, job_id: str) -> Optional[Info]:
        job = self._jobs.get(job_id)
        return _snapshot(job) if job else None

    async def start(
        self, id: str, type: str, run: Callable[[], Awaitable[str]], title: Optional[str] = None, metadata: Optional[dict[str, Any]] = None,
        recovery: Optional[dict[str, Any]] = None, notification_id: Optional[str] = None,
    ) -> Info:
        existing = self._jobs.get(id)
        if existing and existing.info.status == "running":
            return _snapshot(existing)
        loop = asyncio.get_running_loop()
        job = _Active(
            Info(id, type, "running", _now(), title, metadata=metadata, notification_id=notification_id),
            loop.create_future(), loop.create_future(), recovery=recovery,
        )
        self._jobs[id] = job
        job.task = asyncio.ensure_future(self._drive(job, run))
        await asyncio.sleep(0)  # let the job begin before the caller continues
        return _snapshot(job)

    async def wait(self, id: str, timeout: Optional[float] = None) -> WaitResult:
        """timeout in milliseconds."""
        job = self._jobs.get(id)
        if not job:
            return WaitResult(False)
        if job.info.status != "running":
            result = WaitResult(False, _snapshot(job))
        elif timeout is None:
            result = WaitResult(False, await asyncio.shield(job.done))
        elif timeout <= 0:
            result = WaitResult(True, _snapshot(job))
        else:
            try:
                result = WaitResult(False, await asyncio.wait_for(asyncio.shield(job.done), timeout / 1000))
            except asyncio.TimeoutError:
                result = WaitResult(True, _snapshot(job))
        # Recoverable wait -> background is a supported handoff, even after failure.
        if result.info and result.info.status != "running" and not job.recovery:
            self._consume(id, job)
        return result

    async def block(self, id: str, session_id: str) -> Optional[BlockResult]:
        job = self._jobs.get(id)
        if not job:
            return None
        if job.info.status != "running":
            self._consume(id, job)
            return BlockResult("finished", _snapshot(job))
        if job.is_backgrounded:
            return BlockResult("backgrounded", _snapshot(job))
        job.blocking[session_id] = job.blocking.get(session_id, 0) + 1
        try:
            done = asyncio.ensure_future(asyncio.shield(job.done))
            bg = asyncio.ensure_future(asyncio.shield(job.backgrounded))
            try:
                await asyncio.wait({done, bg}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                done.cancel()
                bg.cancel()
            if job.done.done():
                self._consume(id, job)
                return BlockResult("finished", job.done.result())
            return BlockResult("backgrounded", bg.result() if bg.done() and not bg.cancelled() else _snapshot(job))
        finally:
            count = job.blocking.get(session_id)
            if count is not None and job.info.status == "running" and not job.is_backgrounded:
                if count <= 1:
                    del job.blocking[session_id]
                else:
                    job.blocking[session_id] = count - 1

    def _mark_background(self, job: _Active) -> None:
        job.is_backgrounded = True
        job.blocking.clear()
        if job.recovery and not job.info.notification_id:
            job.info = replace(job.info, notification_id=new_message_id())
        self._persist(job)

    def background(self, id: str) -> Optional[Info]:
        job = self._jobs.get(id)
        # Recoverable work may finish before the caller backgrounds it.
        if not job or (job.info.status != "running" and not job.recovery):
            return None
        if job.is_backgrounded:
            return _snapshot(job)
        self._mark_background(job)
        _resolve(job.backgrounded, _snapshot(job))
        return _snapshot(job)

    def background_all(self, session_id: str, type: Optional[str] = None) -> list[Info]:
        out = []
        for job in list(self._jobs.values()):
            if job.info.status != "running" or job.is_backgrounded:
                continue
            if type is not None and job.info.type != type:
                continue
            if session_id not in job.blocking:
                continue
            self._mark_background(job)
            _resolve(job.backgrounded, _snapshot(job))
            out.append(_snapshot(job))
        return out

    async def cancel(self, id: str) -> Optional[Info]:
        job = self._jobs.get(id)
        if not job:
            return None
        if job.info.status != "running":
            self._consume(id, job)
            return _snapshot(job)
        job.blocking.clear()
        job.info = replace(job.info, status="cancelled", completed_at=_now())
        self._persist(job)
        info = _snapshot(job)
        _resolve(job.done, info)
        if job.task and not job.task.done():
            job.task.cancel()
            try:
                await job.task
            except asyncio.CancelledError:
                pass
        self._consume(id, job)
        return info

    def pending_background(self) -> list[dict[str, Any]]:
        return list(self._pending.values())

    def complete_background(self, notification_id: str) -> None:
        self._pending.pop(notification_id, None)
        for k, j in list(self._jobs.items()):
            if j.info.notification_id == notification_id and j.info.status != "running":
                del self._jobs[k]
                break
