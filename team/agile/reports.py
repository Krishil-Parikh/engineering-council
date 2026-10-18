"""The agile documents, written as Markdown. Tables and numbers come straight from the recorded facts; a model only supplies the sentences
that go around them (the narrative, the summaries), and those arrive here as plain strings."""

from __future__ import annotations

import time
from typing import Optional

from team.agile.metrics import SprintMetrics, bar, velocity_history
from team.agile.model import AgileState, Directive, Impediment, Sprint, Standup
from team.plan import Feature, Plan

ROOT = "docs/agile"


def sprint_dir(number: int) -> str:
    return f"{ROOT}/sprint-{number:02d}"


def _cell(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split()).replace("|", "/")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _when(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "-"


def feature_status(f: Feature, state: AgileState, done: set[str], failed: dict[str, str], blocked: dict[str, str], dropped: set[str], running: set[str]) -> str:
    if f.id in done:
        return "done"
    if f.id in dropped:
        return "dropped"
    if f.id in failed:
        return "failed"
    if f.id in blocked:
        return "blocked"
    if f.id in running:
        return "in progress"
    return "backlog"


def tasks_done_for(state: AgileState, feature_id: str) -> set[int]:
    return {t.index for t in state.tasks if t.feature == feature_id}


# ---------------------------------------------------------------------------- backlogs

def render_product_backlog(plan: Plan, state: AgileState, done: set[str], failed: dict[str, str], blocked: dict[str, str], dropped: set[str], running: set[str]) -> str:
    sprint_of = {fid: s.number for s in state.sprints for fid in s.features}
    s = "# Product Backlog\n\nThe whole plan in priority order. Updated after every sprint and whenever the scope changes.\n\n"
    s += "| # | Feature | Owner | Tasks | After | Status | Sprint |\n|---|---|---|---|---|---|---|\n"
    for rank, f in enumerate(plan.features, 1):
        status = feature_status(f, state, done, failed, blocked, dropped, running)
        s += f"| {rank} | `{f.id}` {_cell(f.title, 70)} | {f.owner or '-'} | {len(f.tasks)} | {', '.join(f.depends_on) or '-'} | {status} | {sprint_of.get(f.id, '-')} |\n"
    total = sum(len(f.tasks) for f in plan.features if f.id not in dropped)
    finished = sum(len(f.tasks) for f in plan.features if f.id in done)
    s += f"\n**Progress:** {finished}/{total} tasks `{bar(finished, total)}`\n"
    if dropped:
        s += "\n**Removed from scope:** " + ", ".join(f"`{d}`" for d in sorted(dropped)) + "\n"
    return s


def render_sprint_backlog(sprint: Sprint, plan: Plan, state: AgileState, commitments: dict[str, str], rationale: str = "", carried: Optional[list[str]] = None) -> str:
    s = f"# Sprint {sprint.number} Backlog\n\n**Goal:** {sprint.goal or '(none stated)'}  \n**Planned:** {sprint.planned_tasks} tasks across {len(sprint.features)} feature(s)  \n"
    s += f"**Planned on:** {_when(sprint.started_at)}\n"
    if rationale:
        s += f"\n**Why these:** {rationale}\n"
    if carried:
        s += "\n**Carried over from the last sprint (already in progress):** " + ", ".join(f"`{c}`" for c in carried) + "\n"
    for fid in sprint.features:
        f = next((x for x in plan.features if x.id == fid), None)
        if f is None:
            continue
        done = tasks_done_for(state, fid)
        s += f"\n## `{f.id}` {f.title}\n\n**Owner:** {f.owner or '-'}" + (f"  \n**After:** {', '.join(f.depends_on)}" if f.depends_on else "") + "\n\n"
        if f.summary:
            s += f"{f.summary}\n\n"
        for i, t in enumerate(f.tasks, 1):
            s += f"- [{'x' if i in done else ' '}] {t.title}" + (f" — {_cell(t.details, 140)}" if t.details else "") + "\n"
    if commitments:
        s += "\n## Commitments\n\n| Developer | Commit | Concerns |\n|---|---|---|\n"
        for dev, text in commitments.items():
            yes, _, concerns = text.partition("|")
            s += f"| {dev} | {yes} | {_cell(concerns, 200) or '-'} |\n"
    return s


# ---------------------------------------------------------------------------- standup

def render_standup(standup: Standup, sprint: Sprint, progress: str, impediments: list[Impediment]) -> str:
    s = f"# Standup {standup.number} — Sprint {sprint.number}, day {standup.day}\n\n**Sprint goal:** {sprint.goal or '-'}  \n**Progress:** {progress}\n"
    s += f"\n## Summary\n\n{standup.summary or '(none)'}\n\n## Reports\n"
    for e in standup.entries:
        s += f"\n### {e.dev}\n\n- **Done:** {e.done or '-'}\n- **Next:** {e.next or '-'}\n- **Blockers:** {e.blockers or 'none'}\n"
    if standup.notes:
        s += "\n## Notes from the human\n\n" + "\n".join(f"- {n}" for n in standup.notes) + "\n"
    listed = [i for i in impediments if i.id in standup.impediments]
    if listed:
        s += "\n## Impediments\n\n| Id | Developer | Impediment | Status | Resolution |\n|---|---|---|---|---|\n"
        for i in listed:
            s += f"| {i.id} | {i.dev} | {_cell(i.text, 140)} | {i.status} | {_cell(i.resolution, 140) or '-'} |\n"
    return s


# ---------------------------------------------------------------------------- review, report, retrospective

def render_review(sprint: Sprint, plan: Plan, outcomes: dict[str, str], demos: dict[str, dict], verification: list[tuple[str, int, str]], goal_met: bool, summary: str, carry: list[dict]) -> str:
    s = f"# Sprint {sprint.number} Review\n\n**Sprint goal:** {sprint.goal or '-'}  \n**Goal met:** {'yes' if goal_met else 'no'}\n\n## Increment\n\n{summary or '(none)'}\n"
    s += "\n## Features\n\n| Feature | Owner | Outcome |\n|---|---|---|\n"
    for fid in sprint.features:
        f = next((x for x in plan.features if x.id == fid), None)
        s += f"| `{fid}` {_cell(f.title if f else '', 60)} | {f.owner if f else '-'} | {outcomes.get(fid, '-')} |\n"
    if demos:
        s += "\n## Demos\n"
        for dev, d in demos.items():
            s += f"\n### {dev}\n\n- **Works now:** {d.get('demo') or '-'}\n- **Missing:** {d.get('missing') or '-'}\n- **Warning:** {d.get('warning') or '-'}\n"
    if verification:
        s += "\n## Verification on the integration branch\n\n| Command | Exit |\n|---|---|\n" + "".join(f"| `{_cell(c, 100)}` | {code} |\n" for c, code, _ in verification)
    if carry:
        s += "\n## Carried over\n\n" + "\n".join(f"- `{c.get('feature')}`: {c.get('why', '')}" for c in carry) + "\n"
    return s


def render_sprint_report(sprint: Sprint, m: SprintMetrics, narrative: str, outcomes: dict[str, str], history: list[tuple[int, int, int]], impediments: list[Impediment], usage: Optional[dict[str, dict[str, float]]] = None) -> str:
    s = f"# Sprint {sprint.number} Report\n\n**Goal:** {sprint.goal or '-'}  \n**Duration:** {m.days} day(s)  \n"
    s += f"**Delivered:** {m.completed_tasks}/{m.planned_tasks} tasks `{bar(m.completed_tasks, m.planned_tasks)}` ({int(m.commitment_ratio * 100)}% of the commitment)\n"
    s += f"\n## Narrative\n\n{narrative or '(none)'}\n"
    s += "\n## Features\n\n| Feature | Outcome |\n|---|---|\n" + "".join(f"| `{fid}` | {outcomes.get(fid, '-')} |\n" for fid in sprint.features)
    s += "\n## Burndown (tasks remaining at the end of each day)\n\n| Day | Remaining | |\n|---|---|---|\n"
    for day, left in m.burndown:
        s += f"| {day} | {left} | `{bar(left, m.planned_tasks)}` |\n"
    s += "\n## Who delivered what\n\n| Developer | Tasks completed |\n|---|---|\n" + "".join(f"| {d} | {n} |\n" for d, n in sorted(m.per_dev.items())) if m.per_dev else ""
    s += "\n## Velocity so far\n\n| Sprint | Planned | Completed |\n|---|---|---|\n" + "".join(f"| {n} | {p} | {c} |\n" for n, p, c in history)
    open_ = [i for i in impediments if i.sprint == sprint.number]
    if open_:
        s += "\n## Impediments\n\n| Id | Developer | Impediment | Status |\n|---|---|---|---|\n" + "".join(f"| {i.id} | {i.dev} | {_cell(i.text, 120)} | {i.status} |\n" for i in open_)
    if usage:
        s += "\n## Model use (whole run so far)\n\n| Developer | Input tokens | Output tokens | Cost (USD) |\n|---|---|---|---|\n"
        for dev, u in usage.items():
            s += f"| {dev} | {int(u.get('input_tokens', 0)):,} | {int(u.get('output_tokens', 0)):,} | {u.get('cost', 0):.4f} |\n"
    return s


def render_retrospective(sprint: Sprint, by_dev: dict[str, dict], went_well: list[str], went_badly: list[str], actions: list[dict], lesson: str, previous_actions: list[dict]) -> str:
    s = f"# Sprint {sprint.number} Retrospective\n"
    if previous_actions:
        s += "\n## Actions from the last retrospective\n\n" + "\n".join(f"- {a.get('action', '')} ({a.get('owner', 'team')})" for a in previous_actions) + "\n"
    s += "\n## Went well\n\n" + ("\n".join(f"- {x}" for x in went_well) or "- (nothing recorded)") + "\n"
    s += "\n## Went badly\n\n" + ("\n".join(f"- {x}" for x in went_badly) or "- (nothing recorded)") + "\n"
    s += "\n## Actions for the next sprint\n\n" + ("\n".join(f"- [ ] {a.get('action', '')} — **{a.get('owner', 'team')}**" for a in actions) or "- (none)") + "\n"
    if lesson:
        s += f"\n## Lesson for the team's memory\n\n{lesson}\n"
    if by_dev:
        s += "\n## What each developer said\n"
        for dev, r in by_dev.items():
            s += f"\n### {dev}\n\n- **Went well:** {r.get('went_well') or '-'}\n- **Went badly:** {r.get('went_badly') or '-'}\n- **Change:** {r.get('change') or '-'}\n"
    return s


# ---------------------------------------------------------------------------- running logs

def render_velocity(state: AgileState) -> str:
    s = "# Velocity\n\nTasks planned and completed in each sprint.\n\n| Sprint | Planned | Completed | |\n|---|---|---|---|\n"
    for n, planned, done in velocity_history(state):
        s += f"| {n} | {planned} | {done} | `{bar(done, max(planned, 1))}` |\n"
    return s


def render_impediments(state: AgileState) -> str:
    s = "# Impediments\n\n| Id | Sprint | Day | Developer | Impediment | Status | Resolution |\n|---|---|---|---|---|---|---|\n"
    for i in state.impediments:
        s += f"| {i.id} | {i.sprint} | {i.day} | {i.dev} | {_cell(i.text, 140)} | {i.status} | {_cell(i.resolution, 140) or '-'} |\n"
    return s if state.impediments else "# Impediments\n\nNone raised.\n"


def render_directives(directives: list[Directive]) -> str:
    s = "# Human Directives\n\nEverything the human told the team while it worked, and what the team did about it. These outrank the team's own decisions.\n\n"
    if not directives:
        return s + "None yet.\n"
    s += "| Id | When | Sprint/day | Kind | Instruction | Effect |\n|---|---|---|---|---|---|\n"
    for d in directives:
        s += f"| {d.id} | {_when(d.at)} | {d.sprint}/{d.day} | {d.kind} | {_cell(d.text, 160)} | {_cell(d.effect, 160) or ('pending' if not d.handled else '-')} |\n"
    return s


def render_changelog(entries: list[dict]) -> str:
    s = "# Documentation Changelog\n\nEvery change to the PRD, the technical approach and the design, with the reason and who decided it.\n\n"
    if not entries:
        return s + "No changes since the documents were accepted.\n"
    s += "| When | Sprint | Document | Change | Why | Decided by |\n|---|---|---|---|---|---|\n"
    for e in entries:
        s += f"| {_when(e.get('at', 0))} | {e.get('sprint', '-')} | {e.get('doc', '-')} | {_cell(e.get('change', ''), 160)} | {_cell(e.get('why', ''), 120)} | {e.get('by', '-')} |\n"
    return s
