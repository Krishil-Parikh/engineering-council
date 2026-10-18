"""Runs a plan: features go in parallel when nothing stops them, one at a time per developer, each after the features it depends on.

A feature is *done* when its runner returns ok (the runner includes merging it into the integration branch). If a feature fails, the
features that depend on it are *blocked* rather than started on top of missing work; independent features carry on."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from team.plan import Feature, Plan


@dataclass
class FeatureOutcome:
    ok: bool
    summary: str = ""


Runner = Callable[[Feature], Awaitable[FeatureOutcome]]
Listener = Callable[[str, Feature, str], None]  # (event, feature, detail): started | done | failed | blocked


class Scheduler:
    def __init__(self, plan: Plan, run_feature: Runner, max_parallel: int = 6, on_event: Optional[Listener] = None, done: Optional[set[str]] = None) -> None:
        self.plan, self.run_feature, self.max_parallel = plan, run_feature, max_parallel
        self.on_event = on_event or (lambda event, feature, detail: None)
        self.done: set[str] = set(done or ())  # features already merged by an earlier run are not run again
        self.failed: dict[str, str] = {}
        self.blocked: dict[str, str] = {}
        self.outcomes: dict[str, FeatureOutcome] = {}

    def _block_dependents(self) -> None:
        changed = True
        while changed:
            changed = False
            for f in self.plan.features:
                if f.id in self.blocked or f.id in self.failed or f.id in self.done:
                    continue
                bad = [d for d in f.depends_on if d in self.failed or d in self.blocked]
                if bad:
                    self.blocked[f.id] = f"waiting on {', '.join(bad)}, which did not finish"
                    self.on_event("blocked", f, self.blocked[f.id])
                    changed = True

    async def run(self) -> dict[str, FeatureOutcome]:
        running: dict[asyncio.Task, Feature] = {}
        started: set[str] = set()
        busy: set[str] = set()

        def launch() -> None:
            self._block_dependents()
            for f in self.plan.ready(self.done, started | self.done | set(self.blocked) | set(self.failed)):
                owner = f.owner or ""
                if owner in busy or len(running) >= self.max_parallel:
                    continue
                started.add(f.id)
                busy.add(owner)
                self.on_event("started", f, owner)
                running[asyncio.ensure_future(self._guard(f))] = f

        launch()
        while running:
            finished, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for task in finished:
                f = running.pop(task)
                busy.discard(f.owner or "")
                outcome = task.result()
                self.outcomes[f.id] = outcome
                if outcome.ok:
                    self.done.add(f.id)
                    self.on_event("done", f, outcome.summary)
                else:
                    self.failed[f.id] = outcome.summary
                    self.on_event("failed", f, outcome.summary)
            launch()
        return self.outcomes

    async def _guard(self, feature: Feature) -> FeatureOutcome:
        try:
            return await self.run_feature(feature)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one feature's crash must not stop the others
            return FeatureOutcome(False, f"crashed: {type(exc).__name__}: {exc}")
