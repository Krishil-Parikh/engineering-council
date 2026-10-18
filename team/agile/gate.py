"""The work gate: the one switch that stops all coding while the team is in a ceremony (or while the human has the floor).

Developers work in *days*. A day ends for a developer when they finish a task or run out of their step budget; they then rest at the gate
until the next day begins. When every working developer is resting, the day is over: the playbook freezes the gate, runs the standup (or any
other ceremony) and begins the next day.

Rules the gate keeps
  * It only ever stops a developer *between* steps, never in the middle of one: a file write or shell command in flight finishes first.
  * Only the developers' work sessions are gated. Consultation sessions (a teammate answering a question over A2A) are not, which is what
    lets a ceremony talk to the developers while coding is frozen.
  * The freeze has holders (a ceremony, the human). Coding resumes only when the last holder lets go.
  * It never deadlocks the team: a developer that does not settle within the timeout is reported as late and the ceremony goes on; their
    next step still waits at the closed gate."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class DayEnd:
    """How a developer's day ended, for the standup."""

    dev: str
    reason: str  # task-done | step-budget | frozen
    steps: int


class WorkGate:
    def __init__(self, steps_per_day: int = 40, on_event: Optional[Callable[[str, dict], None]] = None) -> None:
        self.steps_per_day = steps_per_day
        self.on_event = on_event or (lambda kind, data: None)
        self._changed = asyncio.Condition()
        self._workers: set[str] = set()
        self._resting: dict[str, str] = {}  # dev -> why they are resting
        self._sessions: dict[str, str] = {}  # work session id -> dev
        self._steps: dict[str, int] = {}
        self._holders: set[str] = set()
        self.day = 0
        self._pokes: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ state

    @property
    def frozen(self) -> bool:
        return bool(self._holders)

    @property
    def holders(self) -> set[str]:
        return set(self._holders)

    @property
    def workers(self) -> set[str]:
        return set(self._workers)

    def steps_today(self, dev: str) -> int:
        return self._steps.get(dev, 0)

    def resting(self) -> dict[str, str]:
        return dict(self._resting)

    # ------------------------------------------------------------------ who is working

    async def register(self, dev: str) -> None:
        """A developer starts working on a feature. From now on a day is not over until they rest."""
        async with self._changed:
            self._workers.add(dev)
            self._resting.pop(dev, None)
            self._steps.setdefault(dev, 0)
            self._changed.notify_all()

    async def unregister(self, dev: str) -> None:
        async with self._changed:
            self._workers.discard(dev)
            self._resting.pop(dev, None)
            self._changed.notify_all()

    def _poke(self) -> None:
        """Wakes everything waiting on the gate, from code that is not itself async."""

        async def notify() -> None:
            async with self._changed:
                self._changed.notify_all()

        try:
            task = asyncio.get_running_loop().create_task(notify())
        except RuntimeError:
            return
        self._pokes.add(task)
        task.add_done_callback(self._pokes.discard)

    def register_nowait(self, dev: str) -> None:
        """Like `register`, for the scheduler's own bookkeeping: it must happen in the same breath as a feature starting, with no gap in which
        the team looks idle."""
        self._workers.add(dev)
        self._resting.pop(dev, None)
        self._steps.setdefault(dev, 0)
        self._poke()

    def unregister_nowait(self, dev: str) -> None:
        self._workers.discard(dev)
        self._resting.pop(dev, None)
        self._poke()

    @asynccontextmanager
    async def waiting(self, dev: str, why: str = "waiting"):
        """The developer is waiting for someone (the human, a vote) inside a step. They count as resting meanwhile, so a ceremony need not
        wait for an answer that may take a long time."""
        if dev not in self._workers:
            yield
            return
        async with self._changed:
            self._resting[dev] = why
            self._changed.notify_all()
        try:
            yield
        finally:
            async with self._changed:
                if self._resting.get(dev) == why:
                    self._resting.pop(dev, None)
                self._changed.notify_all()
            await self.checkpoint(dev)  # if the gate froze while they waited, they stop here

    def watch(self, dev: str, session_id: str) -> None:
        """Marks a session as a developer's work session, so the gate stops it between steps."""
        self._sessions[session_id] = dev

    def forget(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    # ------------------------------------------------------------------ at the step boundary

    async def before_step(self, session_id: str) -> None:
        """Awaited by the harness before every step of every session; only watched work sessions are ever held."""
        dev = self._sessions.get(session_id)
        if dev is not None:
            await self.checkpoint(dev, count=True)

    async def checkpoint(self, dev: str, count: bool = False) -> None:
        """Waits here while the gate is frozen or the developer's day budget is spent. `count` counts a step against the budget."""
        if dev not in self._workers:
            return
        while True:
            if self.frozen:
                await self._rest(dev, "frozen")
            elif count and self._steps.get(dev, 0) >= self.steps_per_day:
                await self._rest(dev, "step-budget")
            else:
                break
        if count:
            self._steps[dev] = self._steps.get(dev, 0) + 1

    async def finish_task(self, dev: str) -> None:
        """A task is done: the developer's day is over and they rest until the next one."""
        if dev in self._workers:
            await self._rest(dev, "task-done")

    async def _rest(self, dev: str, reason: str) -> None:
        async with self._changed:
            started_on = self.day
            self._resting[dev] = reason
            self._changed.notify_all()
            if reason == "frozen":
                await self._changed.wait_for(lambda: not self.frozen or dev not in self._workers)
            else:  # the end of a day: wait for the next one, and for any freeze to lift
                await self._changed.wait_for(lambda: (self.day > started_on and not self.frozen) or dev not in self._workers)
            self._resting.pop(dev, None)
            self._changed.notify_all()

    # ------------------------------------------------------------------ the coordinator's side

    async def freeze(self, holder: str) -> None:
        async with self._changed:
            self._holders.add(holder)
            self._changed.notify_all()
        self.on_event("freeze", {"holder": holder})

    async def thaw(self, holder: str) -> None:
        async with self._changed:
            self._holders.discard(holder)
            self._changed.notify_all()
        self.on_event("thaw", {"holder": holder})

    async def begin_day(self) -> int:
        """Starts the next day: step budgets reset and everyone resting for the day goes back to work (unless the gate is frozen)."""
        async with self._changed:
            self.day += 1
            self._steps = {dev: 0 for dev in self._workers}
            if not self.frozen:  # released now, so a wait for the end of this day does not see last day's rests
                self._resting = {d: r for d, r in self._resting.items() if r in ("frozen", "waiting")}
            self._changed.notify_all()
        self.on_event("day-begins", {"day": self.day})
        return self.day

    async def wait_day_over(self, timeout: Optional[float] = None) -> list[str]:
        """Returns once every working developer is resting for the day (or nobody is working). Developers held by a freeze do not count: the
        day is not over just because the human paused it. Returns the developers who did not settle in time (empty normally)."""

        def over() -> bool:
            return not self.frozen and all(self._resting.get(dev, "") in ("task-done", "step-budget", "waiting") for dev in self._workers)

        try:
            async with self._changed:
                await asyncio.wait_for(self._changed.wait_for(over), timeout)
        except asyncio.TimeoutError:
            return sorted(dev for dev in self._workers if dev not in self._resting)
        return []

    async def wait_quiet(self, timeout: Optional[float] = None) -> list[str]:
        """Returns once every working developer is parked at the gate (for any reason). Used after a freeze. Returns the late ones."""
        try:
            async with self._changed:
                await asyncio.wait_for(self._changed.wait_for(lambda: all(dev in self._resting for dev in self._workers)), timeout)
        except asyncio.TimeoutError:
            return sorted(dev for dev in self._workers if dev not in self._resting)
        return []

    def day_report(self) -> dict[str, DayEnd]:
        """How each working developer's day ended (read after `wait_day_over`)."""
        return {dev: DayEnd(dev, self._resting.get(dev, "working"), self._steps.get(dev, 0)) for dev in sorted(self._workers)}

    async def hold(self, holder: str, timeout: Optional[float] = None) -> list[str]:
        """Freeze for a ceremony: close the gate and wait until every developer is parked. Returns developers who were late."""
        await self.freeze(holder)
        return await self.wait_quiet(timeout)
