"""Numbers for the reports, worked out from the recorded facts alone (no model involved)."""

from __future__ import annotations

from dataclasses import dataclass

from team.agile.model import AgileState, Sprint


@dataclass
class SprintMetrics:
    number: int
    planned_tasks: int
    completed_tasks: int
    velocity: int
    commitment_ratio: float  # completed / planned (1.0 when the plan was met; 0 when nothing was planned)
    burndown: list[tuple[int, int]]  # (day, tasks remaining at the end of that day), starting from (0, planned)
    per_dev: dict[str, int]  # tasks completed by each developer
    days: int


def sprint_metrics(state: AgileState, sprint: Sprint) -> SprintMetrics:
    done = state.sprint_tasks(sprint.number)
    per_dev: dict[str, int] = {}
    for t in done:
        per_dev[t.dev] = per_dev.get(t.dev, 0) + 1
    burn = [(0, sprint.planned_tasks)] + [(d.day, d.remaining_tasks) for d in state.days if d.sprint == sprint.number]
    ratio = round(len(done) / sprint.planned_tasks, 2) if sprint.planned_tasks else 0.0
    return SprintMetrics(sprint.number, sprint.planned_tasks, len(done), len(done), ratio, burn, per_dev, len([d for d in state.days if d.sprint == sprint.number]))


def velocity_history(state: AgileState) -> list[tuple[int, int, int]]:
    """(sprint, planned tasks, completed tasks) for every sprint so far."""
    return [(s.number, s.planned_tasks, len(state.sprint_tasks(s.number))) for s in state.sprints]


def forecast_capacity(state: AgileState, default: int = 8) -> int:
    """How many tasks the next sprint can sensibly take: the average of the last three completed sprints, never below 3."""
    recent = [done for _, _, done in velocity_history(state) if done > 0][-3:]
    if not recent:
        return default
    return max(3, round(sum(recent) / len(recent)))


def bar(value: int, total: int, width: int = 20) -> str:
    """A text bar for the reports: ████░░░░"""
    if total <= 0:
        return "░" * width
    filled = max(0, min(width, round(width * value / total)))
    return "█" * filled + "░" * (width - filled)
