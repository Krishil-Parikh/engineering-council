"""The ceremonies. Each one gathers real facts, holds the conversation over the A2A network, records the outcome in the agile state and returns
what the playbook needs. The scrum master speaks as the integrator agent; the developers answer as themselves. Nothing here runs while
developers are coding: the playbook only calls these with the work gate frozen.

Conversations that fail (an agent does not answer, an answer is not JSON) never stop the sprint: the ceremony falls back to the facts."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from team.agile import prompts as P
from team.agile import reports as R
from team.agile.docs import AgileDocs
from team.agile.gate import WorkGate
from team.agile.desk import HumanDesk
from team.agile.metrics import forecast_capacity, sprint_metrics, velocity_history
from team.agile.model import Impediment, Sprint, Standup, StandupEntry
from team.agile.pool import FeaturePool
from team.agile.store import AgileStore
from team.plan import Feature, Task

if TYPE_CHECKING:
    from team.engine import TeamEngine

SCRUM_MASTER = "scrum-master"  # the sender name on the network
INTEGRATOR = "integrator"  # the agent that answers for the scrum master
NONE_WORDS = {"", "none", "n/a", "no", "nothing", "-", "no blockers", "none."}


@dataclass
class AgileConfig:
    default_capacity: int = 8  # tasks in the first sprint; later sprints follow the team's velocity
    capacity: Optional[int] = None  # fixed capacity, overriding the forecast
    max_days: int = 4  # work rounds per sprint before the sprint is timeboxed
    steps_per_day: int = 40
    day_timeout: float = 1800.0  # how long a work round may take before the standup goes ahead without the stragglers
    quiesce_timeout: float = 120.0
    max_sprints: int = 12
    retry_failed: int = 1  # how many times a failed feature goes back into a sprint
    approvals: str = "ask"  # ask: the human decides major things; approve: unattended (tests, CI)
    approval_rounds: int = 2  # how often the documents are revised on the human's feedback before the first sprint
    retro: bool = True
    doc_sync: bool = True


def _short(text: str, n: int = 240) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


class Ceremonies:
    def __init__(self, engine: "TeamEngine", store: AgileStore, desk: HumanDesk, gate: WorkGate, pool: FeaturePool, docs: AgileDocs, cfg: AgileConfig) -> None:
        self.engine, self.store, self.desk, self.gate, self.pool, self.docs, self.cfg = engine, store, desk, gate, pool, docs, cfg
        self.sprint_day = 0  # the day within the current sprint (1-based while the sprint runs)
        self.sprint_commitments: dict[str, dict[str, str]] = {}
        self.sprint_rationale: dict[int, str] = {}
        self.carried_in: dict[int, list[str]] = {}
        self.demos: dict[int, dict[str, dict]] = {}
        self.retro_actions: dict[int, list[dict]] = {}

    # ------------------------------------------------------------------ conversation

    @property
    def channel(self):
        return self.engine.channel

    async def ask_sm(self, prompt: str, topic: str) -> str:
        try:
            return await self.channel.ask(SCRUM_MASTER, INTEGRATOR, prompt, topic=topic)
        except Exception as exc:  # noqa: BLE001 - a ceremony goes on without the answer
            self.engine._emit("agile-warning", text=f"the scrum master did not answer ({topic}): {exc}")
            return ""

    async def ask_devs(self, devs: list[str], make_prompt, topic: str) -> dict[str, str]:
        async def one(dev: str) -> str:
            try:
                return await self.channel.ask(SCRUM_MASTER, dev, make_prompt(dev), topic=topic)
            except Exception as exc:  # noqa: BLE001
                self.engine._emit("agile-warning", text=f"{dev} did not answer ({topic}): {exc}")
                return ""

        answers = await asyncio.gather(*(one(d) for d in devs))
        return dict(zip(devs, answers))

    # ------------------------------------------------------------------ facts

    def feature(self, fid: str) -> Optional[Feature]:
        return next((f for f in self.engine.plan.features if f.id == fid), None) if self.engine.plan else None

    def remaining_tasks(self, fid: str) -> int:
        f = self.feature(fid)
        if f is None or fid in self.pool.done or fid in self.pool.dropped:
            return 0
        return max(0, len(f.tasks) - len(R.tasks_done_for(self.store.state, fid)))

    def feature_state(self, fid: str) -> str:
        pool = self.pool
        if fid in pool.done:
            return "merged"
        if fid in pool.dropped:
            return "dropped"
        if fid in pool.failed:
            return f"failed: {_short(pool.failed[fid], 120)}"
        if fid in pool.blocked:
            return f"blocked: {_short(pool.blocked[fid], 120)}"
        if fid in pool.running():
            return "in progress"
        return "waiting"

    def active_devs(self, sprint: Sprint) -> list[str]:
        owners = []
        for fid in sprint.features:
            f = self.feature(fid)
            if f is not None and f.owner and f.owner not in owners:
                owners.append(f.owner)
        return owners

    def progress(self, sprint: Sprint) -> str:
        left = sum(self.remaining_tasks(fid) for fid in sprint.features)
        done = max(0, sprint.planned_tasks - left)
        return f"{done}/{sprint.planned_tasks} tasks done; " + ", ".join(f"{fid} ({self.feature_state(fid)})" for fid in sprint.features)

    def backlog_text(self) -> str:
        lines = []
        for f in self.pool.candidates():
            after = f" — after {', '.join(f.depends_on)}" if f.depends_on else ""
            lines.append(f"- {f.id}: {f.title} [{len(f.tasks)} tasks, owner {f.owner}]{after}. {f.summary}")
        return "\n".join(lines) or "(empty)"

    def standing_text(self) -> str:
        return "\n".join(f"- {d.text}" for d in self.store.state.directives if d.handled and d.kind in ("note", "rethink", "scope")) or "(none)"

    def impediments_text(self) -> str:
        return "\n".join(f"- {i.id} ({i.dev}): {i.text}" for i in self.store.state.open_impediments()) or "(none)"

    async def day_facts(self, dev: str, sprint: Sprint, ended: str, steps: int) -> str:
        eng = self.engine
        state = self.store.state
        today = [t for t in state.tasks if t.sprint == sprint.number and t.day == self.sprint_day and t.dev == dev]
        earlier = [t for t in state.tasks if t.sprint == sprint.number and t.day < self.sprint_day and t.dev == dev]
        cur = eng.current.get(dev)
        lines = [f"- Tasks you finished today: {', '.join(f'{t.feature} #{t.index} {t.title}' for t in today) or 'none'}"]
        if earlier:
            lines.append(f"- Finished on earlier days this sprint: {len(earlier)} task(s)")
        if cur:
            where = f"feature {cur['feature']}, task {cur['index']} of {cur['total']}: {cur['title']}" + (" (in progress)" if cur.get("in_task") else " (just finished)")
            lines.append(f"- You are on: {where}")
        else:
            lines.append("- You are between features.")
        lines.append(f"- Your day used {steps} step(s) and ended because: {ended.replace('-', ' ')}")
        try:
            files = await eng._git(eng.repo.changed_files, dev, eng.integration)
        except Exception:  # noqa: BLE001 - no branch yet
            files = []
        lines.append(f"- Files changed on your branch compared with the integration branch: {', '.join(files[:12]) or 'none'}" + (" …" if len(files) > 12 else ""))
        for fid in sprint.features:
            f = self.feature(fid)
            if f is not None and f.owner == dev and fid in self.pool.failed:
                lines.append(f"- Your feature {fid} FAILED: {_short(self.pool.failed[fid], 200)}")
        said = self.last_said(dev)
        if said:
            lines.append(f"- The last thing you reported: {_short(said, 300)}")
        return "\n".join(lines)

    def last_said(self, dev: str) -> str:
        cur = self.engine.current.get(dev)
        h = self.engine.harnesses.get(dev)
        if not cur or h is None or not cur.get("session"):
            return ""
        try:
            from harness.app import last_text

            return last_text(h.sessions.messages(cur["session"]))
        except Exception:  # noqa: BLE001
            return ""

    # ------------------------------------------------------------------ sprint planning

    async def plan_sprint(self) -> Optional[Sprint]:
        """Pulls work from the backlog into a new sprint. Returns None when nothing is left to do."""
        state = self.store.state
        pool = self.pool
        carried = [fid for fid in pool.admitted if not pool.terminal(fid)]
        candidates = pool.candidates()
        if not candidates and not carried:
            return None
        number = state.sprint + 1
        carried_tasks = sum(self.remaining_tasks(fid) for fid in carried)
        capacity = self.cfg.capacity or forecast_capacity(state, self.cfg.default_capacity)
        room = max(0, capacity - carried_tasks)
        chosen: list[str] = []
        goal, rationale = "", ""
        if candidates:
            prompt = P.PLANNING_PROMPT.format(
                number=number, capacity=capacity, backlog=self.backlog_text(), impediments=self.impediments_text(), directives=self.standing_text(),
                carried=(f"{carried_tasks} task(s) are already in progress from earlier sprints ({', '.join(carried)})." if carried else "Nothing is in progress."), json_only=P.JSON_ONLY,
            )
            data = P.extract_json(await self.ask_sm(prompt, f"sprint {number} planning")) or {}
            chosen = self.valid_selection(data.get("features"), carried, room)
            goal = str(data.get("goal") or "").strip()
            rationale = str(data.get("rationale") or "").strip()
            if not chosen:
                chosen = self.fallback_selection(carried, room)
                rationale = rationale or "chosen in backlog order within the capacity"
        if not chosen and not carried:
            return None
        features = [*carried, *chosen]
        sprint = Sprint(number, goal or self.default_goal(chosen or carried), features, "active", sum(self.remaining_tasks(fid) for fid in features), started_at=time.time())
        state.sprints.append(sprint)
        state.sprint = number
        self.carried_in[number] = carried
        self.sprint_rationale[number] = rationale
        self.sprint_day = 0
        devs = self.active_devs(sprint)
        everyone = "\n".join(f"- {d}: {', '.join(fid for fid in features if (self.feature(fid) and self.feature(fid).owner == d)) or 'nothing'}" for d in devs)
        replies = await self.ask_devs(
            devs,
            lambda d: P.COMMITMENT_PROMPT.format(
                number=number, goal=sprint.goal, dev=d, json_only=P.JSON_ONLY, everyone=everyone,
                mine=", ".join(fid for fid in features if self.feature(fid) and self.feature(fid).owner == d) or "nothing",
            ),
            f"sprint {number} commitment",
        )
        commitments: dict[str, str] = {}
        for dev, reply in replies.items():
            data = P.extract_json(reply) or {}
            commit = data.get("commit", True) is not False
            concerns = str(data.get("concerns") or "").strip()
            commitments[dev] = f"{'yes' if commit else 'no'}|{concerns}"
            if not commit or (concerns and concerns.lower() not in NONE_WORDS):
                self.raise_impediment(dev, f"planning concern: {concerns or 'cannot commit'}", sprint.number, 0)
        self.sprint_commitments[number] = commitments
        self.store.save()
        pool.admit(chosen)
        await self.write_planning_docs(sprint)
        self.engine._emit("sprint-planned", sprint=number, goal=sprint.goal, features=features, tasks=sprint.planned_tasks, carried=carried)
        return sprint

    def valid_selection(self, raw: Any, carried: list[str], room: int) -> list[str]:
        if not isinstance(raw, list):
            return []
        available = {f.id for f in self.pool.candidates()}
        merged = set(self.pool.done) | set(carried)
        chosen: list[str] = []
        spent = 0
        for fid in raw:
            f = self.feature(str(fid))
            if f is None or f.id not in available or f.id in chosen:
                continue
            if not all(d in merged or d in chosen for d in f.depends_on):
                continue
            cost = len(f.tasks)
            if chosen and spent + cost > max(room, 1) * 1.5:
                continue
            chosen.append(f.id)
            spent += cost
        return chosen

    def fallback_selection(self, carried: list[str], room: int) -> list[str]:
        merged = set(self.pool.done) | set(carried)
        chosen: list[str] = []
        spent = 0
        for f in self.pool.candidates():
            if not all(d in merged or d in chosen for d in f.depends_on):
                continue
            cost = len(f.tasks)
            if chosen and spent + cost > max(room, 1):
                continue
            if not chosen and room <= 0 and carried:
                break  # the sprint is already full of carried-over work
            chosen.append(f.id)
            spent += cost
        return chosen

    def default_goal(self, ids: list[str]) -> str:
        titles = [self.feature(fid).title for fid in ids if self.feature(fid)]
        return "Deliver " + ", ".join(titles[:4]) + ("…" if len(titles) > 4 else "")

    async def write_planning_docs(self, sprint: Sprint) -> None:
        state = self.store.state
        base = R.sprint_dir(sprint.number)
        files = {
            f"{base}/sprint_backlog.md": R.render_sprint_backlog(sprint, self.engine.plan, state, self.sprint_commitments.get(sprint.number, {}), self.sprint_rationale.get(sprint.number, ""), self.carried_in.get(sprint.number)),
            f"{R.ROOT}/product_backlog.md": self.render_product_backlog(),
            f"{R.ROOT}/impediments.md": R.render_impediments(state),
        }
        await self.docs.write(files, f"agile: sprint {sprint.number} planning")

    async def refresh_docs(self) -> None:
        """Brings the running documents (backlog, velocity, impediments, directives) up to date."""
        state = self.store.state
        await self.docs.write(
            {f"{R.ROOT}/product_backlog.md": self.render_product_backlog(), f"{R.ROOT}/velocity.md": R.render_velocity(state), f"{R.ROOT}/impediments.md": R.render_impediments(state),
             f"{R.ROOT}/human_directives.md": R.render_directives(state.directives), f"{R.ROOT}/CHANGELOG.md": R.render_changelog(state.changelog)},
            "agile: refresh running documents",
        )

    def render_product_backlog(self) -> str:
        p = self.pool
        return R.render_product_backlog(self.engine.plan, self.store.state, set(p.done), dict(p.failed), dict(p.blocked), set(p.dropped), set(p.running()))

    # ------------------------------------------------------------------ impediments

    def raise_impediment(self, dev: str, text: str, sprint: int, day: int) -> Impediment:
        state = self.store.state
        for known in state.open_impediments():
            if known.dev == dev and known.text.lower() == text.lower():
                return known
        item = Impediment(state.next_id("IMP", state.impediments), sprint, day, dev, text)
        state.impediments.append(item)
        self.engine._emit("impediment", id=item.id, dev=dev, text=text)
        return item

    # ------------------------------------------------------------------ standup

    async def standup(self, sprint: Sprint, day_ended: dict[str, str], late: list[str]) -> Standup:
        state = self.store.state
        number = len([s for s in state.standups if s.sprint == sprint.number]) + 1
        devs = self.active_devs(sprint)
        report = self.gate.day_report()
        facts = {d: await self.day_facts(d, sprint, day_ended.get(d, "finished its feature"), report[d].steps if d in report else 0) for d in devs}
        replies = await self.ask_devs(
            devs, lambda d: P.STANDUP_PROMPT.format(sprint=sprint.number, day=self.sprint_day, dev=d, facts=facts[d], json_only=P.JSON_ONLY), f"standup {number}",
        )
        standup = Standup(sprint.number, number, self.sprint_day)
        raised: list[Impediment] = []
        for dev in devs:
            data = P.extract_json(replies.get(dev, "")) or {}
            blockers = str(data.get("blockers") or "").strip()
            entry = StandupEntry(
                dev, str(data.get("done") or "").strip() or "(no answer; see the facts: " + _short(facts[dev], 160) + ")",
                str(data.get("next") or "").strip(), blockers if blockers.lower() not in NONE_WORDS else "",
            )
            standup.entries.append(entry)
            if entry.blockers:
                raised.append(self.raise_impediment(dev, entry.blockers, sprint.number, self.sprint_day))
            for fid in sprint.features:
                f = self.feature(fid)
                if f is not None and f.owner == dev and fid in self.pool.failed:
                    raised.append(self.raise_impediment(dev, f"feature {fid} failed: {_short(self.pool.failed[fid], 160)}", sprint.number, self.sprint_day))
        for dev in late:
            raised.append(self.raise_impediment(dev, "did not reach a stopping point before the standup (a step took too long)", sprint.number, self.sprint_day))
        standup.impediments = [i.id for i in {i.id: i for i in raised}.values()]
        notes = self.desk.take_notes()
        standup.notes = notes
        entries_text = "\n".join(f"- {e.dev}: done: {e.done} | next: {e.next} | blockers: {e.blockers or 'none'}" for e in standup.entries)
        data = P.extract_json(await self.ask_sm(
            P.STANDUP_SUMMARY_PROMPT.format(sprint=sprint.number, day=self.sprint_day, goal=sprint.goal, progress=self.progress(sprint), entries=entries_text or "(nobody reported)", impediments=self.impediments_text(), json_only=P.JSON_ONLY),
            f"standup {number} summary",
        )) or {}
        standup.summary = str(data.get("summary") or "").strip() or f"Sprint {sprint.number}, day {self.sprint_day}: {self.progress(sprint)}"
        for res in data.get("resolutions") or []:
            if not isinstance(res, dict):
                continue
            item = next((i for i in state.impediments if i.id == res.get("impediment")), None)
            if item is None or item.status != "open":
                continue
            instruction = str(res.get("instruction") or "").strip()
            if res.get("resolved") is True and instruction:
                item.status, item.resolution = "resolved", instruction
                self.engine.brief(item.dev, f"Scrum master, about your blocker ({item.text}): {instruction}")
        for note in notes:
            for dev in self.active_devs(sprint):
                self.engine.brief(dev, f"A note from the human: {note}")
        state.standups.append(standup)
        self.store.save()
        base = R.sprint_dir(sprint.number)
        await self.docs.write(
            {f"{base}/standups/standup-{number:02d}.md": R.render_standup(standup, sprint, self.progress(sprint), state.impediments), f"{R.ROOT}/impediments.md": R.render_impediments(state)},
            f"agile: sprint {sprint.number} standup {number}",
        )
        self.engine._emit("standup", sprint=sprint.number, number=number, day=self.sprint_day, summary=standup.summary, impediments=standup.impediments)
        return standup

    # ------------------------------------------------------------------ review and report

    async def verify(self) -> list[tuple[str, int, str]]:
        eng = self.engine
        commands = [c for c in eng.spec.verification_commands if c.strip() and not c.lower().startswith("proposed")]
        if not commands:
            return []
        from team.engine import run_command

        async with eng.merge_lock:
            await eng.git(INTEGRATOR, f"check out the integration branch {eng.integration}", eng.repo.checkout_branch, INTEGRATOR, eng.integration, branch=eng.integration)
            path = eng.repo.sandbox_path(INTEGRATOR)
            return [(c, *await asyncio.to_thread(run_command, c, path, eng.cfg.verification_timeout)) for c in commands]

    async def review(self, sprint: Sprint) -> dict[str, Any]:
        state = self.store.state
        outcomes = {fid: self.feature_state(fid) for fid in sprint.features}
        verification = await self.verify()
        devs = self.active_devs(sprint)
        replies = await self.ask_devs(
            devs,
            lambda d: P.REVIEW_DEMO_PROMPT.format(
                number=sprint.number, dev=d, goal=sprint.goal, json_only=P.JSON_ONLY,
                mine="\n".join(f"- {fid}: {outcomes[fid]}" for fid in sprint.features if self.feature(fid) and self.feature(fid).owner == d) or "- none",
            ),
            f"sprint {sprint.number} review",
        )
        demos = {d: (P.extract_json(r) or {"demo": _short(r, 300)}) for d, r in replies.items()}
        self.demos[sprint.number] = demos
        data = P.extract_json(await self.ask_sm(
            P.REVIEW_PROMPT.format(
                number=sprint.number, goal=sprint.goal, json_only=P.JSON_ONLY, features="\n".join(f"- {fid}: {o}" for fid, o in outcomes.items()),
                verification="\n".join(f"- `{c}` exited {code}" for c, code, _ in verification) or "(no verification commands)",
                demos="\n".join(f"- {d}: {v.get('demo', '')} | missing: {v.get('missing', '')}" for d, v in demos.items()) or "(none)",
            ),
            f"sprint {sprint.number} review summary",
        )) or {}
        done_all = all(o == "merged" for o in outcomes.values())
        goal_met = bool(data.get("goal_met")) if "goal_met" in data else done_all
        carry = [c for c in (data.get("carry_over") or []) if isinstance(c, dict)] or [{"feature": fid, "why": o} for fid, o in outcomes.items() if o != "merged"]
        summary = str(data.get("summary") or "").strip() or f"{sum(1 for o in outcomes.values() if o == 'merged')} of {len(outcomes)} feature(s) merged."
        sprint.done_features = [fid for fid, o in outcomes.items() if o == "merged"]
        sprint.failed_features = [fid for fid, o in outcomes.items() if o.startswith(("failed", "blocked"))]
        sprint.carried_over = [fid for fid, o in outcomes.items() if o in ("in progress", "waiting")]
        text = R.render_review(sprint, self.engine.plan, outcomes, demos, verification, goal_met, summary, carry)
        await self.docs.write({f"{R.sprint_dir(sprint.number)}/review.md": text}, f"agile: sprint {sprint.number} review")
        self.engine._emit("sprint-review", sprint=sprint.number, goal_met=goal_met, summary=summary)
        return {"goal_met": goal_met, "summary": summary, "outcomes": outcomes, "verification": verification}

    async def report(self, sprint: Sprint, outcomes: dict[str, str]) -> str:
        state = self.store.state
        sprint.ended_at = time.time()
        sprint.days = self.sprint_day
        sprint.velocity = len(state.sprint_tasks(sprint.number))
        metrics = sprint_metrics(state, sprint)
        numbers = (
            f"planned {metrics.planned_tasks} tasks, completed {metrics.completed_tasks} ({int(metrics.commitment_ratio * 100)}%), {metrics.days} day(s); "
            f"per developer: {json.dumps(metrics.per_dev)}; features: " + "; ".join(f"{fid} {o}" for fid, o in outcomes.items())
        )
        standups = "\n".join(f"- day {s.day}: {s.summary}" for s in state.standups if s.sprint == sprint.number) or "(none)"
        data = P.extract_json(await self.ask_sm(P.REPORT_NARRATIVE_PROMPT.format(number=sprint.number, numbers=numbers, standups=standups, json_only=P.JSON_ONLY), f"sprint {sprint.number} report")) or {}
        narrative = str(data.get("narrative") or "").strip() or f"The team completed {metrics.completed_tasks} of {metrics.planned_tasks} planned tasks."
        text = R.render_sprint_report(sprint, metrics, narrative, outcomes, velocity_history(state), [i for i in state.impediments if i.sprint == sprint.number], self.engine.usage())
        await self.docs.write(
            {f"{R.sprint_dir(sprint.number)}/sprint_report.md": text, f"{R.ROOT}/velocity.md": R.render_velocity(state)}, f"agile: sprint {sprint.number} report",
        )
        self.engine._emit("sprint-report", sprint=sprint.number, completed=metrics.completed_tasks, planned=metrics.planned_tasks)
        return narrative

    # ------------------------------------------------------------------ retrospective

    async def retrospective(self, sprint: Sprint, outcomes: dict[str, str]) -> dict[str, Any]:
        state = self.store.state
        eng = self.engine
        metrics = sprint_metrics(state, sprint)
        facts = (
            f"- Sprint goal: {sprint.goal}\n- Delivered {metrics.completed_tasks}/{metrics.planned_tasks} tasks in {metrics.days} day(s)\n"
            + "\n".join(f"- {fid}: {o}" for fid, o in outcomes.items())
            + f"\n- Merge conflicts so far: {len(eng.conflict_log)}\n- Impediments this sprint: {len([i for i in state.impediments if i.sprint == sprint.number])}"
            + "".join(f"\n- The human said: {d.text}" for d in state.directives if d.sprint == sprint.number)
        )
        devs = self.active_devs(sprint)
        replies = await self.ask_devs(devs, lambda d: P.RETRO_PROMPT.format(number=sprint.number, dev=d, facts=facts, json_only=P.JSON_ONLY), f"sprint {sprint.number} retrospective")
        by_dev = {d: (P.extract_json(r) or {"went_badly": _short(r, 200)}) for d, r in replies.items()}
        entries = "\n".join(f"- {d}: went well: {v.get('went_well', '')} | went badly: {v.get('went_badly', '')} | change: {v.get('change', '')}" for d, v in by_dev.items())
        data = P.extract_json(await self.ask_sm(P.RETRO_SUMMARY_PROMPT.format(number=sprint.number, entries=entries or "(nobody answered)", json_only=P.JSON_ONLY), f"sprint {sprint.number} retrospective summary")) or {}
        well = [str(x) for x in (data.get("went_well") or []) if x]
        badly = [str(x) for x in (data.get("went_badly") or []) if x]
        actions = [a for a in (data.get("actions") or []) if isinstance(a, dict) and a.get("action")][:3]
        if not actions:
            actions = [{"action": str(v.get("change")), "owner": d} for d, v in by_dev.items() if v.get("change")][:3]
        lesson = str(data.get("lesson") or "").strip()
        previous = self.retro_actions.get(sprint.number - 1, [])
        self.retro_actions[sprint.number] = actions
        for a in actions:  # working agreements: every developer sees them in their next task
            agreement = f"{a['action']}" + (f" (owner: {a['owner']})" if a.get("owner") not in (None, "", "team") else "")
            if agreement not in state.agreements:
                state.agreements.append(agreement)
        state.agreements = state.agreements[-8:]
        if lesson and eng.lessons is not None:
            eng.lessons.add(lesson, "", ["retrospective", "process"], eng.spec.project_name, "retrospective")
            eng.lessons.save()
        self.store.save()
        text = R.render_retrospective(sprint, by_dev, well, badly, actions, lesson, previous)
        await self.docs.write({f"{R.sprint_dir(sprint.number)}/retrospective.md": text}, f"agile: sprint {sprint.number} retrospective")
        eng._emit("sprint-retro", sprint=sprint.number, actions=[a["action"] for a in actions])
        return {"actions": actions, "lesson": lesson}

    # ------------------------------------------------------------------ documents

    async def doc_sync(self, sprint: Sprint) -> list[dict]:
        """After a sprint, the PRD, technical approach and design are brought in line with what was built. Routine fixes are applied and logged; a
        major change (scope, architecture, stack, contract, data model) needs the human's yes first."""
        state = self.store.state
        eng = self.engine
        changed = "\n".join(f"- {fid}: {self.feature_state(fid)}" + (f" ({self.feature(fid).summary})" if self.feature(fid) and self.feature(fid).summary else "") for fid in sprint.features)
        decisions = "\n".join([f"- design decision '{d.title}': {'approved' if d.approved else 'rejected'}" for d in eng.board.decisions] + [f"- the human: {d.text}" for d in state.directives if d.sprint == sprint.number])
        data = P.extract_json(await self.ask_sm(P.DOCSYNC_PROMPT.format(number=sprint.number, changes=changed, decisions=decisions or "(none)", json_only=P.JSON_ONLY), f"sprint {sprint.number} document sync")) or {}
        amendments = [a for a in (data.get("amendments") or []) if isinstance(a, dict) and a.get("change") and a.get("doc") in ("PRD.md", "Technical_Approach.md", "Design.md")]
        approved: list[dict] = []
        for a in amendments:
            if a.get("major") is True:
                answer = await self.desk.approval(f"{a['doc']}: {_short(a['change'], 80)}", f"{a['change']}\n\nWhy: {a.get('why', '')}", kind="docs")
                by = "the human" if answer.status == "approved" else "rejected by the human"
                if answer.status != "approved":
                    state.changelog.append({"at": time.time(), "sprint": sprint.number, "doc": a["doc"], "change": a["change"], "why": a.get("why", ""), "by": by})
                    continue
                a["by"] = "the human"
            else:
                a["by"] = "scrum master (routine)"
            approved.append(a)
        if approved:
            await self.apply_amendments(approved)
            for a in approved:
                state.changelog.append({"at": time.time(), "sprint": sprint.number, "doc": a["doc"], "change": a["change"], "why": a.get("why", ""), "by": a["by"]})
        self.store.save()
        await self.docs.write(
            {f"{R.ROOT}/CHANGELOG.md": R.render_changelog(state.changelog), f"{R.ROOT}/product_backlog.md": self.render_product_backlog(), f"{R.ROOT}/human_directives.md": R.render_directives(state.directives)},
            f"agile: sprint {sprint.number} document sync",
        )
        eng._emit("doc-sync", sprint=sprint.number, applied=[a["doc"] for a in approved], proposed=len(amendments))
        return approved

    async def apply_amendments(self, amendments: list[dict]) -> None:
        """The integrator edits the documents on the integration branch."""
        eng = self.engine
        listing = "\n".join(f"- {a['doc']}: {a['change']} (because {a.get('why', 'it changed')})" for a in amendments)
        async with eng.merge_lock:
            await eng.git(INTEGRATOR, f"check out the integration branch {eng.integration}", eng.repo.checkout_branch, INTEGRATOR, eng.integration, branch=eng.integration)
            h = eng.harness(INTEGRATOR)
            session = h.new_session(agent=eng_agent_id(INTEGRATOR), title="document sync")
            await asyncio.wait_for(h.prompt(P.APPLY_DOCS_PROMPT.format(amendments=listing), session_id=session.id), eng.cfg.task_timeout)
            if await eng.git(INTEGRATOR, "commit the document amendments", eng.repo.commit_all, INTEGRATOR, "docs: apply agreed amendments"):
                await eng.git(INTEGRATOR, f"publish {eng.integration} with the amended documents", eng.repo.push, INTEGRATOR, eng.integration, branch=eng.integration)


def eng_agent_id(name: str) -> str:
    from team.persona import agent_id

    return agent_id(name)
