"""Serializes execution for each key while letting different keys run at once (opencode: packages/core/src/session/run-coordinator.py's
original, session/run-coordinator.ts).

One *execution* is a busy period for one key: one task that drains from the first wake until the key would stay idle. `pending_wake` is the
doorbell: work that arrives during the execution rings it with the scope that work needs, and the execution drains again instead of ending.
The doorbell closes the gap between a drain's last eligibility check and the idle transition, which cannot be one atomic step.

          wake | run
    idle ──────────────▶ execution (one task)
                           drain ⟲ doorbell rung mid-drain
                           │ exit (settled hook runs)
    doorbell quiet ◀───────┴───────▶ doorbell rung
    idle, waiters get exit          successor execution, waiters get this exit

Joiners (`run` on a key that is already executing) wait for the execution's exit; cancelling a joiner never cancels the execution. An
interrupt is acknowledged at once and does not wait for cleanup: the execution finishes its cleanup and its `settled` hook on its own time."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Generic, Hashable, Optional, TypeVar

Key = TypeVar("Key", bound=Hashable)
PROMOTABLE = ("input", "steer")  # "input" subsumes "steer": a coalesced wake keeps the wider scope


class ExecutionInterrupted(Exception):
    """What a joiner receives when the execution it was waiting for was interrupted."""

    def __init__(self, reason: Any = None) -> None:
        super().__init__(f"execution interrupted{': ' + str(reason) if reason else ''}")
        self.reason = reason


@dataclass
class _Execution:
    done: "asyncio.Future[None]"
    scope: str
    owner: Optional[asyncio.Task] = None
    pending_wake: Optional[str] = None
    stopping: bool = False
    interruption_reason: Any = None


Drain = Callable[[Any, bool, str], Awaitable[None]]
Started = Callable[[Any], Awaitable[None]]
Settled = Callable[[Any, Optional[BaseException], Any], Awaitable[None]]  # (key, exit, reason): exit is None for success


class RunCoordinator(Generic[Key]):
    def __init__(self, drain: Drain, started: Optional[Started] = None, settled: Optional[Settled] = None) -> None:
        self._drain, self._started, self._settled = drain, started, settled
        self._executions: dict[Any, _Execution] = {}
        self._background: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ the loop

    async def _loop(self, key: Any, execution: _Execution, force: bool) -> None:
        while True:
            await self._drain(key, force, execution.scope)
            if execution.stopping or execution.pending_wake is None:
                return
            execution.scope, execution.pending_wake, force = execution.pending_wake, None, False
            await asyncio.sleep(0)  # trampoline: drains that complete synchronously cannot starve the loop

    async def _execute(self, key: Any, execution: _Execution, force: bool) -> None:
        exit_: Optional[BaseException] = None
        try:
            await asyncio.sleep(0)  # lets `owner` be assigned before the drain can settle
            if self._started is not None:
                await asyncio.shield(self._started(key))  # uninterruptible
            await self._loop(key, execution, force)
        except BaseException as exc:  # noqa: BLE001 - the exit is reported to joiners and the settled hook, not raised from the task
            exit_ = exc
        execution.owner = None
        if self._settled is not None:
            try:
                await self._settled(key, exit_, execution.interruption_reason)
            except BaseException as exc:  # noqa: BLE001 - a hook failure never leaves the key owned
                exit_ = exit_ or exc
        self._settle(key, execution, exit_)

    def _start(self, key: Any, force: bool, scope: str) -> _Execution:
        execution = _Execution(asyncio.get_running_loop().create_future(), scope)
        self._executions[key] = execution
        execution.owner = asyncio.ensure_future(self._execute(key, execution, force))
        return execution

    def _settle(self, key: Any, execution: _Execution, exit_: Optional[BaseException]) -> None:
        """A doorbell that outlived the loop (rung after it decided to end, or during cleanup) starts a fresh execution for the remaining work."""
        if execution.pending_wake:
            self._start(key, False, execution.pending_wake)
        else:
            self._executions.pop(key, None)
        if exit_ is None:
            execution.done.set_result(None)
        else:
            error = ExecutionInterrupted(execution.interruption_reason) if isinstance(exit_, asyncio.CancelledError) else exit_
            execution.done.set_exception(error)
            execution.done.exception()  # mark retrieved: nobody may be waiting

    # ------------------------------------------------------------------ interface

    def active(self) -> set[Any]:
        """Keys with an execution owned by this coordinator."""
        return set(self._executions)

    def is_active(self, key: Any) -> bool:
        """Includes cleanup and terminal settlement."""
        return key in self._executions

    async def run(self, key: Any) -> None:
        """Starts an execution while idle, or joins the active one and returns its exit (raising its failure)."""
        execution = self._executions.get(key)
        if execution is not None:
            if execution.stopping:  # a stopping execution refuses joiners: wait out its cleanup, then run fresh
                try:
                    await asyncio.shield(execution.done)
                except Exception:  # noqa: BLE001
                    pass
                return await self.run(key)
            return await asyncio.shield(execution.done)
        await asyncio.shield(self._start(key, True, "input").done)

    def wake(self, key: Any, scope: str = "input") -> None:
        """Rings the doorbell: an idle key starts an execution; an active one drains again before settling."""
        execution = self._executions.get(key)
        if execution is not None:
            execution.pending_wake = "input" if execution.pending_wake == "input" else scope
            return
        self._start(key, False, scope)

    def _interrupt(self, key: Any, reason: Any) -> bool:
        execution = self._executions.get(key)
        if execution is None or execution.stopping:
            return False
        if execution.owner is None:
            # Settlement window: the owner exited but the settled hook has not finished. The terminal outcome is already decided, so no
            # reason attaches, but the interrupt still claims the recorded wakes so settle starts no successor for a dead intent.
            execution.pending_wake = None
            return False
        execution.stopping = True
        execution.pending_wake = None  # wakes so far belong to the interrupted intent; ones arriving during cleanup restart normally
        execution.interruption_reason = reason
        execution.owner.cancel()
        return True

    async def interrupt(self, key: Any, reason: Any = None, await_settlement: bool = False) -> bool:
        """Stops the active execution and clears its doorbell; a no-op when idle. Resolves once the interruption is accepted, not when
        cleanup settles, unless `await_settlement` (which waits for this execution's cleanup and settled hook, not for successors).
        Returns whether an active execution was interrupted."""
        execution = self._executions.get(key)
        interrupted = self._interrupt(key, reason)
        if await_settlement and execution is not None:
            try:
                await asyncio.shield(execution.done)
            except Exception:  # noqa: BLE001
                pass
        return interrupted

    async def await_idle(self, key: Any) -> None:
        """Resolves once no execution is active for the key, following successors. Returns at once when idle and never starts work."""
        while (execution := self._executions.get(key)) is not None:
            try:
                await asyncio.shield(execution.done)
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0)

    async def close(self) -> None:
        """Interrupts everything and waits for it to settle."""
        for key in list(self._executions):
            await self.interrupt(key, "shutdown", await_settlement=True)
        for key in list(self._executions):
            await self.await_idle(key)
