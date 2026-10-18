"""The feature pool: the scheduler for a run made of sprints.

`team/scheduler.py` runs a whole plan to the end. A sprint-based run needs the same rules (one feature per developer at a time, a feature
starts only after the features it depends on are merged, a failed feature blocks its dependents) but with the work admitted a sprint at a
time and the loop owned by the playbook. Features keep running across sprint boundaries: a feature admitted in sprint 1 and not finished
is simply still running in sprint 2 (it is *carried over*).

The pool also keeps the gate's list of working developers, in the same breath as a feature starting or ending, so the team never looks
idle for a moment between one feature and the next."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from team.agile.gate import WorkGate
from team.plan import Feature, Plan
from team.scheduler import FeatureOutcome

Runner = Callable[[Feature], Awaitable[FeatureOutcome]]
Listener = Callable[[str, Feature, str], None]  # (event, feature, detail): started | done | failed | blocked | dropped


class FeaturePool:
    def __init__(self, plan: Plan, run_feature: Runner, gate: WorkGate, max_parallel: int = 6, on_event: Optional[Listener] = None, done: Optional[set[str]] = None) -> None:
        self.plan, self.run_feature, self.gate, self.max_parallel = plan, run_feature, gate, max_parallel
        self.on_event = on_event or (lambda event, feature, detail: None)
        self.done: set[str] = set(done or ())
        self.failed: dict[str, str] = {}
        self.blocked: dict[str, str] = {}
        self.dropped: set[str] = set()
        self.outcomes: dict[str, FeatureOutcome] = {}
        self.attempts: dict[str, int] = {}
        self.admitted: set[str] = set()  # features the playbook has let in (this sprint or an earlier one)
        self._running: dict[str, asyncio.Task] = {}
        self._busy: set[str] = set()

    # ------------------------------------------------------------------ what is where

    def running(self) -> list[str]:
        return [fid for fid, task in self._running.items() if not task.done()]

    def terminal(self, fid: str) -> bool:
        return fid in self.done or fid in self.failed or fid in self.blocked or fid in self.dropped

    def waiting(self) -> list[str]:
        """Admitted, not started, not finished (waiting for a dependency or for their developer)."""
        return [fid for fid in self.admitted if fid not in self._running and not self.terminal(fid)]

    def unfinished(self, ids: list[str]) -> list[str]:
        return [fid for fid in ids if not self.terminal(fid)]

    def candidates(self) -> list[Feature]:
        """Features that could be pulled into a sprint: not admitted, not finished, in plan order."""
        return [f for f in self.plan.features if f.id not in self.admitted and not self.terminal(f.id)]

    # ------------------------------------------------------------------ running

    def admit(self, ids: list[str]) -> None:
        for fid in ids:
            if fid in {f.id for f in self.plan.features} and not self.terminal(fid):
                self.admitted.add(fid)
        self.launch()

    def _block_dependents(self) -> None:
        changed = True
        while changed:
            changed = False
            for f in self.plan.features:
                if self.terminal(f.id):
                    continue
                bad = [d for d in f.depends_on if d in self.failed or d in self.blocked or d in self.dropped]
                if bad:
                    self.blocked[f.id] = f"waiting on {', '.join(bad)}, which did not finish"
                    self.on_event("blocked", f, self.blocked[f.id])
                    changed = True

    def launch(self) -> None:
        self._block_dependents()
        for f in self.plan.features:
            if f.id not in self.admitted or f.id in self._running or self.terminal(f.id):
                continue
            if not all(d in self.done for d in f.depends_on):
                continue
            owner = f.owner or ""
            if owner in self._busy or len(self._running) >= self.max_parallel:
                continue
            self._busy.add(owner)
            self.attempts[f.id] = self.attempts.get(f.id, 0) + 1
            self.gate.register_nowait(owner)
            self.on_event("started", f, owner)
            task = asyncio.ensure_future(self._guard(f))
            self._running[f.id] = task
            task.add_done_callback(lambda t, feature=f: self._finished(feature, t))

    def _finished(self, feature: Feature, task: asyncio.Task) -> None:
        self._running.pop(feature.id, None)
        owner = feature.owner or ""
        self._busy.discard(owner)
        if not task.cancelled():
            outcome = task.result()
            self.outcomes[feature.id] = outcome
            if outcome.ok:
                self.done.add(feature.id)
                self.on_event("done", feature, outcome.summary)
            else:
                self.failed[feature.id] = outcome.summary
                self.on_event("failed", feature, outcome.summary)
        self.launch()  # successors first, so the owner is registered again before the gate hears they left
        if owner not in self._busy:
            self.gate.unregister_nowait(owner)

    async def _guard(self, feature: Feature) -> FeatureOutcome:
        try:
            return await self.run_feature(feature)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one feature's crash must not stop the others
            return FeatureOutcome(False, f"crashed: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------ changes of mind

    async def drop(self, fid: str, reason: str = "") -> None:
        """Takes a feature out of scope. A running one is cancelled; the features that needed it are blocked."""
        feature = next((f for f in self.plan.features if f.id == fid), None)
        if feature is None or fid in self.done:
            return
        task = self._running.get(fid)
        self.dropped.add(fid)
        self.admitted.discard(fid)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except BaseException:  # noqa: BLE001 - cancelled on purpose
                pass
        self.on_event("dropped", feature, reason)
        self.launch()

    def requeue(self, fid: str) -> bool:
        """Gives a failed feature another go: it leaves the failed list (and unblocks what waited on it) and must be admitted again."""
        if fid not in self.failed:
            return False
        del self.failed[fid]
        self.outcomes.pop(fid, None)
        self.admitted.discard(fid)
        for other, why in list(self.blocked.items()):
            if fid in why:
                del self.blocked[other]
        return True

    async def cancel_all(self) -> None:
        tasks = [t for t in self._running.values() if not t.done()]
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except BaseException:  # noqa: BLE001
                pass
        self._running.clear()
