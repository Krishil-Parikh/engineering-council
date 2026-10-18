"""The playbook: the sprint loop, and what the team does when the human speaks.

    plan the sprint  ->  [ work a day  ->  standup ]  x N  ->  review  ->  report  ->  retrospective  ->  document sync  ->  next sprint

Coding and ceremonies never overlap. A sprint's planning and everything after the last standup happen with the work gate frozen; each
standup freezes it for as long as it takes. The human can freeze it at any moment (`HumanDesk.interrupt`) and what they say is turned
into a directive here: a note for everyone, a change of scope (emergency replanning), or a stop-and-rethink.

Major things never happen without the human: the first set of documents, scope and architecture changes, and changes to the PRD all
wait for an answer at the desk."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Optional

from team.agile import prompts as P
from team.agile import reports as R
from team.agile.ceremonies import AgileConfig, Ceremonies, SCRUM_MASTER, INTEGRATOR
from team.agile.desk import HumanDesk
from team.agile.docs import AgileDocs
from team.agile.gate import WorkGate
from team.agile.model import DayRecord, Directive, Sprint, TaskDone
from team.agile.pool import FeaturePool
from team.agile.store import AgileStore
from team.plan import Feature, PlanError, Task
from team.repo import slugify

if TYPE_CHECKING:
    from team.engine import TeamEngine

DOC_NAMES = ("PRD.md", "Technical_Approach.md", "Design.md")


class AgileStopped(Exception):
    """The human declined the documents, so there is nothing to build."""


class Playbook:
    def __init__(self, engine: "TeamEngine", cfg: AgileConfig) -> None:
        self.engine, self.cfg = engine, cfg
        self.store = AgileStore(engine.root / "agile" / "state.json", engine.cfg.run_id, on_change=lambda s: engine._emit("agile-state", phase=s.phase, sprint=s.sprint))
        self.gate = WorkGate(cfg.steps_per_day, on_event=lambda kind, data: engine.on_event(f"gate-{kind}", data))
        self.desk = HumanDesk(self.gate, self.store, lambda kind, data: engine.on_event(kind, data), cfg.approvals, cfg.quiesce_timeout)
        self.desk.handler = self.handle_directive
        self.docs = AgileDocs(engine)
        self.pool: Optional[FeaturePool] = None
        self.ceremonies: Optional[Ceremonies] = None
        self.lock = asyncio.Lock()  # one ceremony or directive at a time

    # ------------------------------------------------------------------ wiring

    def bind(self, merged: set[str], listener) -> None:
        eng = self.engine
        self.pool = FeaturePool(eng.plan, eng.run_feature, self.gate, eng.cfg.max_parallel, listener, done=merged)
        self.pool.dropped.update(self.store.state.dropped)
        self.ceremonies = Ceremonies(eng, self.store, self.desk, self.gate, self.pool, self.docs, self.cfg)

    @property
    def sprint_day(self) -> int:
        return self.ceremonies.sprint_day if self.ceremonies else 0

    def task_finished(self, dev: str, feature: Feature, index: int, task: Task) -> None:
        state = self.store.state
        state.tasks.append(TaskDone(state.sprint, self.sprint_day, feature.id, dev, index, task.title, self.gate.steps_today(dev)))
        self.store.save()

    # ------------------------------------------------------------------ the first documents

    async def approve_first_documents(self) -> None:
        """The first PRD, Technical_Approach and Design are never accepted automatically: the human reads them and says yes (or asks for changes)."""
        state = self.store.state
        if state.docs_accepted:
            return
        eng = self.engine
        state.phase = "approval"
        self.store.save()
        paths = [str(eng.meeting_dir / name) for name in DOC_NAMES if (eng.meeting_dir / name).exists()]
        for attempt in range(self.cfg.approval_rounds + 1):
            detail = "Read these before development starts:\n" + "\n".join(f"- {p}" for p in paths)
            answer = await self.desk.approval("Accept the project documents?", detail, kind="docs")
            if answer.status == "approved":
                state.docs_accepted = True
                self.store.save()
                return
            if attempt == self.cfg.approval_rounds:
                break
            await self.revise_documents(answer.answer or "(no details given)")
        raise AgileStopped("the documents were not accepted")

    async def revise_documents(self, feedback: str) -> None:
        eng = self.engine
        async with eng.merge_lock:
            await eng.git(INTEGRATOR, f"check out the integration branch {eng.integration}", eng.repo.checkout_branch, INTEGRATOR, eng.integration, branch=eng.integration)
            h = eng.harness(INTEGRATOR)
            from team.persona import agent_id

            session = h.new_session(agent=agent_id(INTEGRATOR), title="revise documents")
            await asyncio.wait_for(h.prompt(P.REVISE_DOCS_PROMPT.format(feedback=feedback), session_id=session.id), eng.cfg.task_timeout)
            sandbox = eng.repo.sandbox_path(INTEGRATOR)
            for name in DOC_NAMES:  # the human reads the originals in the meeting folder, so keep them in step
                src = sandbox / "docs" / name
                if src.exists():
                    (eng.meeting_dir / name).write_bytes(src.read_bytes())
            if await eng.git(INTEGRATOR, "commit the revised documents", eng.repo.commit_all, INTEGRATOR, "docs: revise after the human's review"):
                await eng.git(INTEGRATOR, f"publish {eng.integration} with the revised documents", eng.repo.push, INTEGRATOR, eng.integration, branch=eng.integration)
        self.store.state.changelog.append({"at": time.time(), "sprint": 0, "doc": "PRD/Technical_Approach/Design", "change": feedback, "why": "the human's review before development", "by": "the human"})
        self.store.save()

    # ------------------------------------------------------------------ the sprint loop

    async def run(self) -> None:
        state = self.store.state
        cer, pool, gate = self.ceremonies, self.pool, self.gate
        assert cer is not None and pool is not None
        state.phase = "sprinting"
        for stale in state.sprints:  # a sprint left open by an earlier, stopped run is closed without ceremonies; its unmerged features are planned again
            if stale.status == "active":
                stale.status = "closed"
        self.store.save()
        await gate.freeze("ceremony")  # planning is a ceremony: nothing is being coded yet
        try:
            while state.sprint < self.cfg.max_sprints:
                await self.desk.hold_point()
                async with self.lock:
                    sprint = await cer.plan_sprint()
                if sprint is None:
                    break
                await self.run_sprint(sprint)
                async with self.lock:
                    await self.close_sprint(sprint)
            else:
                self.engine.result.warnings.append(f"stopped after {self.cfg.max_sprints} sprints with work left")
        finally:
            await gate.thaw("ceremony")
            await pool.cancel_all()
            state.phase = "closing"
            self.store.save()

    async def run_sprint(self, sprint: Sprint) -> None:
        cer, pool, gate, eng = self.ceremonies, self.pool, self.gate, self.engine
        assert cer is not None and pool is not None
        while True:
            await self.desk.hold_point()
            await gate.thaw("ceremony")
            await gate.begin_day()
            cer.sprint_day += 1
            had_work = bool(pool.running())
            eng._emit("day-start", sprint=sprint.number, day=cer.sprint_day, working=sorted(gate.workers))
            late = await gate.wait_day_over(self.cfg.day_timeout)
            await self.desk.hold_point()  # the human may have the floor
            late = sorted(set(late) | set(await gate.hold("ceremony", self.cfg.quiesce_timeout)))
            ended = {dev: r.reason for dev, r in gate.day_report().items()}
            async with self.lock:
                remaining = sum(cer.remaining_tasks(fid) for fid in sprint.features)
                self.store.state.days.append(DayRecord(sprint.number, cer.sprint_day, ended, remaining, late))
                self.store.save()
                if had_work or pool.running():
                    await cer.standup(sprint, ended, late)
            unfinished = pool.unfinished(sprint.features)
            stuck = bool(unfinished) and not pool.running()
            if stuck:
                eng.result.warnings.append(f"sprint {sprint.number}: {', '.join(unfinished)} could not start (waiting on work that is not in the sprint)")
            if not unfinished or stuck or cer.sprint_day >= self.cfg.max_days:
                return

    async def close_sprint(self, sprint: Sprint) -> None:
        cer, pool, state = self.ceremonies, self.pool, self.store.state
        assert cer is not None and pool is not None
        sprint.status = "review"
        await self.desk.hold_point()
        result = await cer.review(sprint)
        await self.desk.hold_point()
        await cer.report(sprint, result["outcomes"])
        if self.cfg.retro:
            await self.desk.hold_point()
            await cer.retrospective(sprint, result["outcomes"])
        if self.cfg.doc_sync:
            await self.desk.hold_point()
            await cer.doc_sync(sprint)
        for fid in list(sprint.failed_features):  # a failed feature gets another go in a later sprint
            if fid in pool.failed and pool.attempts.get(fid, 1) <= self.cfg.retry_failed:
                pool.requeue(fid)
                self.engine._emit("feature-requeued", feature=fid)
        sprint.status = "closed"
        self.store.save()
        await cer.refresh_docs()

    # ------------------------------------------------------------------ the human

    async def handle_directive(self, d: Directive) -> None:
        """Acts on what the human said. Runs with the gate frozen, after any ceremony in progress has finished its step."""
        cer = self.ceremonies
        async with self.lock:
            if d.kind not in ("note", "scope", "rethink"):
                data = P.extract_json(await cer.ask_sm(P.CLASSIFY_PROMPT.format(text=d.text, json_only=P.JSON_ONLY), "human directive")) if cer else None
                d.kind = (data or {}).get("kind") if (data or {}).get("kind") in ("note", "scope", "rethink") else "note"
            if d.kind == "scope":
                d.effect = await self.replan(d)
            elif d.kind == "rethink":
                d.effect = await self.rethink(d)
            else:
                d.effect = await self.apply_note(d)
            d.handled = True
            self.store.save()
            if cer is not None:
                await self.docs.write({f"{R.ROOT}/human_directives.md": R.render_directives(self.store.state.directives), f"{R.ROOT}/product_backlog.md": cer.render_product_backlog()}, f"agile: human directive {d.id}")

    def current_devs(self) -> list[str]:
        sprint = self.store.state.current()
        if sprint is None or self.ceremonies is None:
            return list(self.engine.developers)
        return self.ceremonies.active_devs(sprint) or list(self.engine.developers)

    async def apply_note(self, d: Directive) -> str:
        devs = self.current_devs()
        for dev in devs:
            await self.engine.brief(dev, f"Instruction from the human (it outranks the team's own decisions): {d.text}", sender="human")
        return f"given to {', '.join(devs)}"

    async def replan(self, d: Directive) -> str:
        """Emergency replanning: the scrum master turns the human's change of scope into drops, additions and a new priority order."""
        cer, pool, eng, state = self.ceremonies, self.pool, self.engine, self.store.state
        assert cer is not None and pool is not None
        backlog = "\n".join(f"- {f.id}: {f.title} [{cer.feature_state(f.id) if f.id in pool.admitted or pool.terminal(f.id) else 'backlog'}; {len(f.tasks)} tasks; owner {f.owner}]" for f in eng.plan.features)
        data = P.extract_json(await cer.ask_sm(P.REPLAN_PROMPT.format(text=d.text, backlog=backlog, team=", ".join(eng.developers), json_only=P.JSON_ONLY), "emergency replanning")) or {}
        notes: list[str] = []
        for fid in [str(x) for x in (data.get("drop") or [])]:
            f = cer.feature(fid)
            if f is None or fid in pool.done:
                continue
            owner = f.owner
            await pool.drop(fid, d.text)
            if owner and owner in eng.harnesses:
                await asyncio.to_thread(eng.repo.discard_work, owner)
            if fid not in state.dropped:
                state.dropped.append(fid)
            notes.append(f"dropped {fid}")
        added: list[str] = []
        for raw in data.get("add") or []:
            try:
                fid = slugify(str(raw["id"]))
                if cer.feature(fid) is not None:
                    continue
                tasks = [Task(str(t["title"]), str(t.get("details", ""))) if isinstance(t, dict) else Task(str(t)) for t in raw.get("tasks", [])]
                owner = raw.get("owner") if raw.get("owner") in eng.developers else None
                feature = Feature(fid, str(raw.get("title") or fid), tasks, owner, [slugify(str(x)) for x in raw.get("depends_on", [])], str(raw.get("summary", "")))
                eng.plan.features.append(feature)
                eng.plan.validate(eng.developers)
                eng.plan.assign_owners(eng.spec, eng.roster)
                added.append(fid)
            except (KeyError, TypeError, ValueError, PlanError) as exc:
                if eng.plan.features and eng.plan.features[-1].id == fid:
                    eng.plan.features.pop()
                notes.append(f"could not add {raw.get('id') if isinstance(raw, dict) else raw}: {exc}")
        order = [slugify(str(x)) for x in (data.get("priority") or [])]
        if order:
            rank = {fid: i for i, fid in enumerate(order)}
            eng.plan.features.sort(key=lambda f: rank.get(f.id, len(rank)))
        sprint = state.current()
        if sprint is not None and added:
            sprint.features.extend(added)
            sprint.planned_tasks += sum(len(cer.feature(a).tasks) for a in added)
            pool.admit(added)
            notes.append("added " + ", ".join(added) + " to the sprint")
        eng._save_state(set(pool.done))
        if data.get("docs"):
            amendment = {"doc": "PRD.md, Technical_Approach.md or Design.md (whichever apply)", "change": str(data["docs"]), "why": f"the human's change of scope: {d.text}", "by": "the human"}
            await cer.apply_amendments([amendment])
            state.changelog.append({"at": time.time(), "sprint": state.sprint, "doc": "PRD/Technical_Approach/Design", "change": str(data["docs"]), "why": amendment["why"], "by": "the human"})
            notes.append("documents updated")
        for dev in self.current_devs():
            await eng.brief(dev, f"The human changed the scope: {d.text}. " + (data.get("rationale") or ""), sender="human")
        return "; ".join(notes) or str(data.get("rationale") or "no change was needed")

    async def rethink(self, d: Directive) -> str:
        """The human says the team is going the wrong way: the developers say what is wrong, the scrum master proposes a course correction and
        the human approves it before anything changes."""
        cer, pool, eng = self.ceremonies, self.pool, self.engine
        assert cer is not None and pool is not None
        sprint = self.store.state.current()
        devs = self.current_devs()
        progress = cer.progress(sprint) if sprint else "(no sprint yet)"
        replies = await cer.ask_devs(devs, lambda dev: P.RETHINK_PROMPT.format(text=d.text, sprint=sprint.number if sprint else 0, goal=sprint.goal if sprint else "", progress=progress), "stop and rethink")
        entries = "\n".join(f"- {dev}: {' '.join(r.split())[:400]}" for dev, r in replies.items())
        data = P.extract_json(await cer.ask_sm(P.RETHINK_SUMMARY_PROMPT.format(text=d.text, entries=entries or "(nobody answered)", json_only=P.JSON_ONLY), "course correction")) or {}
        summary = str(data.get("summary") or "").strip() or "The team will take the human's direction into account."
        instruction = str(data.get("instruction") or d.text).strip()
        answer = await self.desk.approval("Course correction", f"{summary}\n\nWhat changes for the team: {instruction}\nDrop: {', '.join(data.get('drop') or []) or 'nothing'}", kind="scope")
        if answer.status != "approved":
            return "the proposed course correction was declined: " + (answer.answer or "no reason given")
        notes: list[str] = []
        for fid in [str(x) for x in (data.get("drop") or [])]:
            f = cer.feature(fid)
            if f is not None and fid not in pool.done:
                owner = f.owner
                await pool.drop(fid, d.text)
                if owner and owner in eng.harnesses:
                    await asyncio.to_thread(eng.repo.discard_work, owner)
                if fid not in self.store.state.dropped:
                    self.store.state.dropped.append(fid)
                notes.append(f"dropped {fid}")
        for dev in devs:
            await eng.brief(dev, f"Course correction agreed with the human: {instruction}", sender="human")
        if data.get("docs"):
            await cer.apply_amendments([{"doc": "PRD.md, Technical_Approach.md or Design.md (whichever apply)", "change": str(data["docs"]), "why": f"the human: {d.text}", "by": "the human"}])
            self.store.state.changelog.append({"at": time.time(), "sprint": self.store.state.sprint, "doc": "PRD/Technical_Approach/Design", "change": str(data["docs"]), "why": d.text, "by": "the human"})
            notes.append("documents updated")
        eng._save_state(set(pool.done))
        return "; ".join([summary, *notes])

    # ------------------------------------------------------------------ design decisions

    async def human_design_gate(self, proposer: str, title: str, reason: str, change: str, votes: list) -> tuple[bool, str]:
        """The team voted yes to a design change. A change to the architecture is a major decision, so the human has the last word."""
        detail = f"{proposer} proposes: {change}\n\nWhy: {reason}\n\nThe team voted: " + "; ".join(f"{v.voter} {v.vote}" for v in votes)
        answer = await self.desk.approval(f"Design change: {title}", detail, kind="decision", dev=proposer)
        return answer.status == "approved", answer.answer
