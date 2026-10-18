"""The facts of an agile run: the sprints, what each day achieved, impediments, standups, and the human's directives.

Everything here is plain data that round-trips through JSON, so a stopped run resumes where it was and the reports are generated from facts
(never from what a model remembers). `AgileState` is the single record; `team/agile/store.py` saves it."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# phases of a whole run, in order
PHASES = ("kickoff", "approval", "sprinting", "closing", "done")

# a backlog item's life
BACKLOG, PLANNED, ACTIVE, DONE, BLOCKED, DROPPED = "backlog", "planned", "active", "done", "blocked", "dropped"


@dataclass
class TaskDone:
    """One task finished by one developer on one day."""

    sprint: int
    day: int
    feature: str
    dev: str
    index: int
    title: str
    steps: int = 0
    at: float = field(default_factory=time.time)


@dataclass
class DayRecord:
    sprint: int
    day: int
    ended: dict[str, str] = field(default_factory=dict)  # dev -> task-done | step-budget | late
    remaining_tasks: int = 0  # tasks still open in the sprint when the day ended (the burndown)
    late: list[str] = field(default_factory=list)


@dataclass
class Impediment:
    id: str
    sprint: int
    day: int
    dev: str
    text: str
    status: str = "open"  # open | resolved
    resolution: str = ""


@dataclass
class StandupEntry:
    dev: str
    done: str = ""
    next: str = ""
    blockers: str = ""


@dataclass
class Standup:
    sprint: int
    number: int  # the standup's number within the sprint
    day: int
    entries: list[StandupEntry] = field(default_factory=list)
    summary: str = ""  # the scrum master's consolidation
    impediments: list[str] = field(default_factory=list)  # ids raised or still open
    notes: list[str] = field(default_factory=list)  # the human's notes delivered at this standup


@dataclass
class Sprint:
    number: int
    goal: str = ""
    features: list[str] = field(default_factory=list)  # feature ids pulled into the sprint
    status: str = "planning"  # planning | active | review | closed
    planned_tasks: int = 0
    days: int = 0
    done_features: list[str] = field(default_factory=list)
    carried_over: list[str] = field(default_factory=list)
    failed_features: list[str] = field(default_factory=list)
    started_at: float = 0.0
    ended_at: float = 0.0
    velocity: int = 0  # tasks completed in the sprint


@dataclass
class Directive:
    """Something the human said while the team was working."""

    id: str
    text: str
    kind: str = "note"  # note | scope | rethink
    at: float = field(default_factory=time.time)
    sprint: int = 0
    day: int = 0
    handled: bool = False
    effect: str = ""


@dataclass
class Approval:
    """A decision waiting for the human, or already answered."""

    id: str
    title: str
    detail: str
    kind: str = "decision"  # docs | decision | scope
    status: str = "pending"  # pending | approved | rejected
    answer: str = ""
    sprint: int = 0
    at: float = field(default_factory=time.time)


@dataclass
class AgileState:
    run_id: str = ""
    phase: str = "kickoff"
    sprint: int = 0  # the current sprint's number (0 before the first)
    sprints: list[Sprint] = field(default_factory=list)
    days: list[DayRecord] = field(default_factory=list)
    tasks: list[TaskDone] = field(default_factory=list)
    standups: list[Standup] = field(default_factory=list)
    impediments: list[Impediment] = field(default_factory=list)
    directives: list[Directive] = field(default_factory=list)
    approvals: list[Approval] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)  # feature ids the human removed from scope
    changelog: list[dict] = field(default_factory=list)  # changes to the project documents: at, sprint, doc, change, why, by
    agreements: list[str] = field(default_factory=list)  # working agreements from the retrospectives, in force for every sprint after
    docs_accepted: bool = False

    # ------------------------------------------------------------------ lookups

    def current(self) -> Optional[Sprint]:
        return next((s for s in self.sprints if s.number == self.sprint), None)

    def sprint_tasks(self, number: int) -> list[TaskDone]:
        return [t for t in self.tasks if t.sprint == number]

    def open_impediments(self) -> list[Impediment]:
        return [i for i in self.impediments if i.status == "open"]

    def pending_approvals(self) -> list[Approval]:
        return [a for a in self.approvals if a.status == "pending"]

    def next_id(self, prefix: str, items: list[Any]) -> str:
        return f"{prefix}-{len(items) + 1:03d}"

    # ------------------------------------------------------------------ JSON

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AgileState":
        def many(cls, key):
            return [cls(**row) for row in data.get(key, [])]

        def standups() -> list[Standup]:
            out = []
            for row in data.get("standups", []):
                row = dict(row)
                row["entries"] = [StandupEntry(**e) for e in row.get("entries", [])]
                out.append(Standup(**row))
            return out

        return AgileState(
            run_id=data.get("run_id", ""), phase=data.get("phase", "kickoff"), sprint=data.get("sprint", 0), sprints=many(Sprint, "sprints"),
            days=many(DayRecord, "days"), tasks=many(TaskDone, "tasks"), standups=standups(), impediments=many(Impediment, "impediments"),
            directives=many(Directive, "directives"), approvals=many(Approval, "approvals"), dropped=list(data.get("dropped", [])),
            docs_accepted=bool(data.get("docs_accepted", False)), changelog=list(data.get("changelog", [])), agreements=list(data.get("agreements", [])),
        )
