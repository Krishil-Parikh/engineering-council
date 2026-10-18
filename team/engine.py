"""Agent mode: the developers build the project from a finished meeting, in parallel, each in their own clone.

The flow
  1. A shared remote is created from the target repository (or an empty one). `main` is protected; only the human updates it.
  2. The integrator seeds `integration/<run>` with the specification and project memory.
  3. The scrum master turns the specification into a plan of features (a dependency graph). Each feature gets a branch `feature/<id>` and one owner.
  4. Features run in parallel, one per developer at a time, each only after the features it depends on are merged. A developer works in their
     sandbox with the full harness, does the tasks in order, commits, and the engine pushes the branch.
  5. A finished feature is merged into the integration branch, one at a time. On a conflict the integrator talks to the feature's owner and to
     the developers who wrote the code it clashes with, resolves it, and only then completes the merge.
  6. Any developer can call a design-change meeting; the team votes and the decision is recorded as an ADR.
  7. The specification's verification commands run on the integration branch; failures go back to a developer for repair.
  8. `final/<run>` is pushed for the human to review and merge into main. Nothing here ever updates main.

The integrator works in a sandbox of its own, so merging never disturbs a developer's feature work."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from harness.app import Harness
from harness.shell import select as ShellSelect
from meetings.errors import MeetingError
from meetings.models import Roster, Spec
from meetings.storage import write_text
from memory import CHECKPOINT_PROMPT, DISTILL_PROMPT, LessonStore, ProjectLog, RunFacts, describe_events, facts_to_lessons, parse_lessons, relevant, update_codemap
from team.build import GITIGNORE, agents_md
from team.channel import Channel, LocalChannel
from team.design import Decision, DesignBoard, design_change_tool
from team.persona import DEVELOPER_RULES, agent_id, developer_agent
from team.plan import PLAN_PROMPT, Feature, Plan, PlanError, fallback_plan
from team.prompts import conflict_ask, conflict_resolution, repair_prompt, spec_brief, task_prompt
from team.repo import RepoError, TeamRepo, slugify
from team.scheduler import FeatureOutcome, Scheduler

INTEGRATOR = "integrator"


@dataclass
class TeamConfig:
    run_id: str = field(default_factory=lambda: time.strftime("%Y%m%d-%H%M%S"))
    max_parallel: int = 6
    planning_attempts: int = 3
    conflict_rounds: int = 3
    repair_rounds: int = 2
    task_timeout: float = 1800.0
    verification_timeout: int = 300
    snapshots: bool = False
    resume: bool = True
    transport: str = "a2a"  # "a2a" (gRPC between agents) or "local" (in-process)
    memory_dir: Optional[Path] = None  # cross-project memory (lessons, profiles, learned skills); None turns it off
    distill: bool = True  # also ask the scrum master to reflect on the run in its own words


@dataclass
class FeatureReport:
    id: str
    owner: str
    branch: str
    status: str  # merged | failed | blocked
    summary: str = ""
    conflicts: int = 0


@dataclass
class TeamResult:
    run_id: str
    root: Path
    integration_branch: str
    final_branch: Optional[str] = None
    features: list[FeatureReport] = field(default_factory=list)
    verification: list[tuple[str, int, str]] = field(default_factory=list)
    passed: bool = False
    warnings: list[str] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    lessons_learned: int = 0


def run_command(command: str, cwd: Path, timeout: int) -> tuple[int, str]:
    import subprocess

    shell = ShellSelect.resolve("compat")
    try:
        out = subprocess.run([shell, *ShellSelect.args(shell, command)], cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return out.returncode, (out.stdout + out.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as exc:
        return 127, str(exc)


class TeamEngine:
    def __init__(
        self, meeting_dir: Path, root: Path, *, llm: Any = None, api_key: Optional[str] = None, model: Optional[str] = None, source: Optional[Path] = None,
        config: Optional[TeamConfig] = None, harness_factory: Optional[Callable[..., Harness]] = None, channel: Optional[Channel] = None,
        on_event: Optional[Callable[[str, dict[str, Any]], None]] = None,
    ) -> None:
        spec_path = Path(meeting_dir) / "specification.json"
        if not spec_path.exists():
            raise MeetingError(f"{meeting_dir} has no specification.json; finish the meeting first.")
        roster_path = Path(meeting_dir) / "roster.json"
        self.roster = Roster.model_validate_json(roster_path.read_text(encoding="utf-8")).skills if roster_path.exists() else {}
        if not self.roster:
            raise MeetingError("roster.json is missing: the developers' skills are unknown.")
        self.meeting_dir = Path(meeting_dir)
        self.spec = Spec.model_validate_json(spec_path.read_text(encoding="utf-8"))
        self.root = Path(root).resolve()
        self.cfg = config or TeamConfig()
        self.source = source
        self.llm, self.api_key, self.model = llm, api_key, model
        self.on_event = on_event or (lambda kind, data: None)
        self.repo = TeamRepo(self.root / "remote")
        self.integration = f"integration/{self.cfg.run_id}"
        self.final = f"final/{self.cfg.run_id}"
        self.developers = list(self.roster)
        self.harnesses: dict[str, Harness] = {}
        self._factory = harness_factory or self._default_harness
        self.merge_lock = asyncio.Lock()
        self._own_channel = channel is None
        self.channel: Channel = channel or LocalChannel(self.harness, lambda d: self.roster.get(d, d.upper()))
        self._network = None
        self.board = DesignBoard(self.channel, [*self.developers, INTEGRATOR], self.repo.sandbox_path, INTEGRATOR)
        self.result = TeamResult(self.cfg.run_id, self.root, self.integration)
        self.conflict_counts: dict[str, int] = {}
        self.plan: Optional[Plan] = None
        self.conflict_log: list[dict] = []
        self.lessons = LessonStore(self.cfg.memory_dir) if self.cfg.memory_dir else None
        self.project_log = ProjectLog(self.repo.sandbox_path(INTEGRATOR), self.spec.project_name)

    # ------------------------------------------------------------------ people

    def _default_harness(self, dev: str, sandbox: Path, agent: Any) -> Harness:
        data = self.root / "data" / slugify(dev)
        if self.lessons is not None and self.lessons.skills_dir.is_dir():  # skills the team has learned on earlier projects
            shutil.copytree(self.lessons.skills_dir, data / "skills", dirs_exist_ok=True)
        return Harness(
            sandbox, llm=self.llm, api_key=self.api_key, model=self.model, data_root=data, home=self.root / "home", db_path=data / "sessions.db",
            snapshots=self.cfg.snapshots, agents=[agent], rules=DEVELOPER_RULES, default_agent=agent.id,
            on_event=lambda kind, d, dev=dev: self.on_event(f"{dev}:{kind}", d),
        )

    def harness(self, dev: str) -> Harness:
        """The developer's harness, working in their own sandbox clone (created on first use)."""
        if dev not in self.harnesses:
            sandbox = self.repo.sandbox(dev)
            skill = self.roster.get(dev, "INTEGRATOR")
            experience = self.lessons.describe(skill) if self.lessons is not None else ""
            agent = developer_agent(dev, skill, experience) if dev != INTEGRATOR else _integrator_agent()
            h = self._factory(dev, sandbox, agent)
            h.registry.add(design_change_tool(h.deps, self.board, dev))
            self.harnesses[dev] = h
        return self.harnesses[dev]

    async def _git(self, fn, *args, **kw):
        return await asyncio.to_thread(fn, *args, **kw)

    def _emit(self, kind: str, **data: Any) -> None:
        self.on_event(kind, data)

    # ------------------------------------------------------------------ setup

    async def setup(self) -> None:
        await self._git(self.repo.init, self.source)
        await self._git(self.repo.checkout_branch, INTEGRATOR, self.integration)
        sandbox = self.repo.sandbox(INTEGRATOR)
        docs = sandbox / "docs"
        docs.mkdir(exist_ok=True)
        for doc in ("PRD.md", "Technical_Approach.md", "Design.md"):
            if (self.meeting_dir / doc).exists() and not (docs / doc).exists():
                shutil.copy2(self.meeting_dir / doc, docs / doc)
        if not (sandbox / ".gitignore").exists():
            write_text(sandbox / ".gitignore", GITIGNORE)
        if not (sandbox / "AGENTS.md").exists():
            write_text(sandbox / "AGENTS.md", agents_md(self.spec))
        if await self._git(self.repo.commit_all, INTEGRATOR, "Add specification and project memory"):
            self._emit("seeded", branch=self.integration)
        await self._git(self.repo.push, INTEGRATOR, self.integration)

    # ------------------------------------------------------------------ planning

    async def make_plan(self) -> Plan:
        state = self.root / "state.json"
        if self.cfg.resume and state.exists():
            saved = json.loads(state.read_text(encoding="utf-8"))
            if saved.get("run_id") == self.cfg.run_id:
                plan = Plan.from_json(json.dumps(saved["plan"]))
                plan.validate(self.developers)
                self.result.warnings.append("resumed an earlier run") if saved.get("merged") else None
                self._merged_at_start = set(saved.get("merged", []))
                return plan
        feedback = ""
        plan: Optional[Plan] = None
        for attempt in range(self.cfg.planning_attempts):
            prompt = PLAN_PROMPT.format(roster=", ".join(f"{d} ({s.title()})" for d, s in self.roster.items()), spec=spec_brief(self.spec)) + self.recalled("plan split work parallel merge conflict owner interface verification tests integration design " + self.spec.project_name, None, 6) + feedback
            reply = await self.channel.ask("system", INTEGRATOR, prompt, topic="work plan")
            try:
                match = re.search(r"\{.*\}", reply, re.S)
                plan = Plan.from_json(match.group(0) if match else reply)
                for f in plan.features:
                    if f.owner and f.owner not in self.developers:
                        f.owner = None  # the model invented a name; staffing decides
                plan.validate(self.developers)
                break
            except PlanError as exc:
                feedback = f"\n\nYour previous plan was rejected: {exc}. Fix it and answer with the complete corrected JSON."
                plan = None
        if plan is None:
            self.result.warnings.append("The scrum master's plan was unusable; using the specification's implementation sequence.")
            plan = fallback_plan(self.spec)
            plan.validate()
        plan.assign_owners(self.spec, self.roster)
        self._merged_at_start = set()
        return plan

    def _save_state(self, merged: set[str]) -> None:
        if self.plan is not None:
            (self.root).mkdir(parents=True, exist_ok=True)
            (self.root / "state.json").write_text(
                json.dumps({"run_id": self.cfg.run_id, "plan": json.loads(self.plan.to_json()), "merged": sorted(merged)}, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ one feature

    async def run_feature(self, feature: Feature) -> FeatureOutcome:
        dev = feature.owner or self.developers[0]
        h = self.harness(dev)
        await self._git(self.repo.checkout_branch, dev, feature.branch, self.integration)
        session = h.new_session(agent=agent_id(dev), title=feature.title)
        other = [f"{f.owner}: {f.title}" for f in (self.plan.features if self.plan else []) if f.id != feature.id]
        for index, task in enumerate(feature.tasks, 1):
            self._emit("task", feature=feature.id, owner=dev, index=index, total=len(feature.tasks), title=task.title)
            prompt = task_prompt(self.spec, feature, task, index, other, self.memory_for(dev, feature, task))
            try:
                result = await asyncio.wait_for(h.prompt(prompt, session_id=session.id), self.cfg.task_timeout)
            except asyncio.TimeoutError:
                await h.sessions.interrupt(session.id)
                return FeatureOutcome(False, f"task '{task.title}' timed out after {self.cfg.task_timeout:.0f}s")
            await self._git(self.repo.commit_all, dev, f"{feature.id}: {task.title}")  # whatever the developer left uncommitted
            if result.outcome != "succeeded":
                return FeatureOutcome(False, f"task '{task.title}' did not finish ({result.outcome}): {result.error or result.text[:200]}")
        if not await self._git(self.repo.changed_files, dev, self.integration):
            self.result.warnings.append(f"{feature.id}: {dev} made no changes")
        await self._git(self.repo.push, dev, feature.branch)
        merged, note = await self.merge_feature(feature)
        return FeatureOutcome(merged, note)

    # ------------------------------------------------------------------ merging

    async def merge_feature(self, feature: Feature, source_branch: Optional[str] = None) -> tuple[bool, str]:
        """Merges a pushed branch into the integration branch, one merge at a time."""
        branch = source_branch or feature.branch
        async with self.merge_lock:
            await self._git(self.repo.checkout_branch, INTEGRATOR, self.integration)
            before = await self._git(self.repo.head, INTEGRATOR)
            merge = await self._git(self.repo.merge, INTEGRATOR, branch, f"Merge {branch}")
            if merge.status == "conflict":
                self.conflict_counts[feature.id] = self.conflict_counts.get(feature.id, 0) + 1
                self._emit("conflict", feature=feature.id, files=merge.files)
                self.conflict_log.append({"feature": feature.id, "files": list(merge.files), "with": [], "resolved": False})
                if not await self.resolve_conflict(feature, branch):
                    await self._git(self.repo.abort_merge, INTEGRATOR)
                    return False, f"merge conflict in {', '.join(merge.files)} could not be resolved"
                self.conflict_log[-1]["resolved"] = True
            await self.remember_merge(feature, branch, before)
            await self._git(self.repo.push, INTEGRATOR, self.integration)
        return True, f"merged {branch}" + (" after resolving a conflict" if feature.id in self.conflict_counts else "")

    # ------------------------------------------------------------------ memory

    def recalled(self, query: str, skill: Optional[str], k: int = 5) -> str:
        """Lessons from earlier projects that fit the query, ready to append to a prompt ('' when there are none)."""
        if self.lessons is None:
            return ""
        text = self.lessons.render(self.lessons.recall(query, skill, k))
        return f"\n\n{text}" if text else ""

    def memory_for(self, dev: str, feature: Feature, task: Any) -> str:
        """What the developer should know before starting: the parts of the code map and project log about this work, plus lessons."""
        query = f"{feature.title} {feature.summary} {task.title} {task.details}"
        sandbox = self.repo.sandbox_path(dev)
        parts = []
        for name, label in (("docs/CODEMAP.md", "Code map (what exists already)"), ("docs/MEMORY.md", "Project history and decisions")):
            try:
                text = relevant((sandbox / name).read_text(encoding="utf-8"), query, 2500)
            except OSError:
                continue
            if text.strip():
                parts.append(f"{label}:\n{text.strip()}")
        parts.append(self.recalled(query, self.roster.get(dev), 4).strip())
        return "\n\n".join(p for p in parts if p)

    async def _summarize(self, previous: str, folded: str) -> str:
        return await self.channel.ask("system", INTEGRATOR, CHECKPOINT_PROMPT.format(previous=previous or "(none)", entries=folded), topic="memory checkpoint")

    async def remember_merge(self, feature: Feature, branch: str, before: str) -> None:
        """After a merge, in the integrator's clone: refresh the code map and add the merge to the project log, then commit both."""
        files = await self._git(self.repo.files_between, INTEGRATOR, before, "HEAD")
        sandbox = self.repo.sandbox_path(INTEGRATOR)
        await asyncio.to_thread(update_codemap, sandbox, self.spec.project_name)
        lines = [f"owner {feature.owner}", f"branch {branch}", "files: " + (", ".join(files[:12]) + (" …" if len(files) > 12 else "") if files else "(none)")]
        if feature.summary:
            lines.append(feature.summary[:160])
        if feature.id in self.conflict_counts:
            lines.append("merged after a conflict that was resolved by conversation")
        await self.project_log.add(f"Merged {feature.title}", lines, self._summarize)
        await self._git(self.repo.commit_all, INTEGRATOR, f"memory: after {branch}")

    async def learn(self) -> None:
        """At the end of a run: turn what happened into lessons, update the developers' experience and promote lessons seen on several projects to skills."""
        if self.lessons is None:
            return
        failed = [f for f in self.result.features if f.status != "merged"]
        facts = RunFacts(
            self.spec.project_name, features=len(self.result.features),
            conflicts=self.conflict_log,
            failed_features=[{"feature": f.id, "owner": f.owner, "skill": self.roster.get(f.owner, ""), "reason": f.summary} for f in failed],
            verification_failures=[{"command": c, "tail": out} for c, code, out in self.result.verification if code != 0],
            decisions=[{"title": d.title, "approved": d.approved, "proposer_skill": self.roster.get(d.proposer, "")} for d in self.board.decisions],
            unresolved_merges=sum(1 for c in self.conflict_log if not c["resolved"]),
        )
        found = facts_to_lessons(facts)
        if self.cfg.distill:
            try:
                reply = await self.channel.ask("system", INTEGRATOR, DISTILL_PROMPT.format(project=facts.project, features=facts.features, events=describe_events(facts)), topic="lessons")
                found += parse_lessons(reply)
            except Exception as exc:  # noqa: BLE001 - reflection is a bonus; the deterministic lessons are already in hand
                self.result.warnings.append(f"could not ask the scrum master to reflect: {exc}")
        for lesson in found:
            self.lessons.add(lesson["text"], lesson["skill"], lesson["tags"], facts.project, lesson["source"])
        by_skill: dict[str, list[FeatureReport]] = {}
        for f in self.result.features:
            by_skill.setdefault(self.roster.get(f.owner, ""), []).append(f)
        for skill, items in by_skill.items():
            if skill:
                self.lessons.record_run(skill, features=sum(1 for i in items if i.status == "merged"), conversations=sum(i.conflicts for i in items), failures=sum(1 for i in items if i.status != "merged"))
        self.lessons.prune()
        self.lessons.save()
        self.lessons.write_skills()
        self.result.lessons_learned = len(found)

    async def authors_of(self, files: list[str], exclude: set[str]) -> list[str]:
        """Developers whose commits touched these files on the integration branch (the owners of what is being merged into)."""

        def collect() -> list[str]:
            from harness.git import run

            names: list[str] = []
            path = self.repo.sandbox(INTEGRATOR)
            for f in files:
                out = run(["log", "--format=%an", "HEAD", "--", f], str(path)).text.splitlines()
                for n in out:
                    dev = re.sub(r" \(Council\)$", "", n.strip())
                    if dev in self.developers and dev not in exclude and dev not in names:
                        names.append(dev)
            return names

        return await asyncio.to_thread(collect)

    async def resolve_conflict(self, feature: Feature, source_branch: str) -> bool:
        owner = feature.owner or self.developers[0]
        h = self.harness(INTEGRATOR)
        session = h.new_session(agent=agent_id(INTEGRATOR), title=f"merge {source_branch}")
        feedback = ""
        for round_no in range(1, self.cfg.conflict_rounds + 1):
            files = await self._git(self.repo.conflicted_files, INTEGRATOR)
            texts = await self._git(self.repo.conflict_text, INTEGRATOR)
            clashing = await self.authors_of(files, {owner})
            ask = conflict_ask(source_branch, owner, files, texts, feedback)
            replies = await self.channel.broadcast(INTEGRATOR, [owner, *clashing], ask, topic=f"merge conflict in {', '.join(files)}")
            self._emit("conflict-talk", feature=feature.id, round=round_no, with_=list(replies))
            prompt = conflict_resolution(source_branch, files, texts, replies, feedback)
            result = await asyncio.wait_for(h.prompt(prompt, session_id=session.id), self.cfg.task_timeout)
            unresolved = await self._git(self.repo.unresolved, INTEGRATOR)
            if result.outcome == "succeeded" and not unresolved:
                try:
                    await self._git(self.repo.finish_merge, INTEGRATOR, f"Merge {source_branch} (conflict resolved with {', '.join(replies)})")
                    return True
                except RepoError as exc:
                    feedback = str(exc)
                    continue
            feedback = f"Conflict markers remain in: {', '.join(unresolved)}." if unresolved else (result.error or "The resolution did not finish.")
        return False

    # ------------------------------------------------------------------ the whole run

    async def run(self) -> TeamResult:
        self.root.mkdir(parents=True, exist_ok=True)
        if self._own_channel and self.cfg.transport == "a2a":
            from team.a2a_channel import open_network

            self._network = await open_network(self, self.root / "a2a-audit.jsonl")
            self.channel = self.board.channel = self._network
        try:
            return await self._run()
        finally:
            if self._network is not None:
                await self._network.close()
                self._network = None

    async def _run(self) -> TeamResult:
        await self.setup()
        self.plan = await self.make_plan()
        self._emit("plan", plan=json.loads(self.plan.to_json()))
        merged_so_far = set(self._merged_at_start)
        self._save_state(merged_so_far)

        def listener(event: str, feature: Feature, detail: str) -> None:
            if event == "done":
                merged_so_far.add(feature.id)
                self._save_state(merged_so_far)
            self._emit(f"feature-{event}", feature=feature.id, owner=feature.owner, detail=detail)

        scheduler = Scheduler(self.plan, self.run_feature, self.cfg.max_parallel, listener, done=set(self._merged_at_start))
        try:
            outcomes = await scheduler.run()
            for f in self.plan.features:
                status = "merged" if f.id in scheduler.done else "blocked" if f.id in scheduler.blocked else "failed"
                summary = scheduler.blocked.get(f.id) or (outcomes[f.id].summary if f.id in outcomes else "already merged in an earlier run")
                self.result.features.append(FeatureReport(f.id, f.owner or "", f.branch, status, summary, self.conflict_counts.get(f.id, 0)))
                if status != "merged":
                    self.result.warnings.append(f"{f.id} ({f.owner}): {status}: {summary}")
            await self.verify_and_repair()
            await self.finish()
            await self.learn()
        finally:
            self.result.decisions = list(self.board.decisions)
            for h in self.harnesses.values():
                await h.close()
        write_text(self.meeting_dir / "team_report.md", render_report(self.spec, self.result, self.roster))
        return self.result

    async def verify_and_repair(self) -> None:
        commands = [c for c in self.spec.verification_commands if c.strip() and not c.lower().startswith("proposed")]
        integ = self.repo.sandbox(INTEGRATOR)
        for attempt in range(self.cfg.repair_rounds + 1):
            await self._git(self.repo.checkout_branch, INTEGRATOR, self.integration)
            self.result.verification = [(c, *await asyncio.to_thread(run_command, c, integ, self.cfg.verification_timeout)) for c in commands]
            failing = [(c, code, out) for c, code, out in self.result.verification if code != 0]
            self._emit("verification", failing=len(failing), attempt=attempt)
            if not failing:
                self.result.passed = bool(commands) and all(f.status == "merged" for f in self.result.features)
                return
            if attempt == self.cfg.repair_rounds:
                self.result.warnings.append("Verification still failing after the repair rounds: " + ", ".join(c for c, _, _ in failing))
                return
            from meetings.models import Step
            from team.staffing import pick_developer

            dev = pick_developer(Step(order=0, title="fix failing verification", details=" ".join(c for c, _, _ in failing)), self.spec, self.roster, {})
            branch = f"fix/{self.cfg.run_id}-{attempt + 1}"
            await self._git(self.repo.checkout_branch, dev, branch, self.integration)
            h = self.harness(dev)
            result = await asyncio.wait_for(h.prompt(repair_prompt(failing), agent=agent_id(dev)), self.cfg.task_timeout)
            await self._git(self.repo.commit_all, dev, "fix: verification")
            if result.outcome != "succeeded":
                self.result.warnings.append(f"repair by {dev} did not finish: {result.error or result.outcome}")
                return
            await self._git(self.repo.push, dev, branch)
            ok, note = await self.merge_feature(Feature(f"fix-{attempt + 1}", "fix verification", [], owner=dev), source_branch=branch)
            if not ok:
                self.result.warnings.append(f"repair merge failed: {note}")
                return

    async def finish(self) -> None:
        """Publishes the final branch for the human. Never touches main."""
        await self._git(self.repo.checkout_branch, INTEGRATOR, self.final, self.integration)
        await self._git(self.repo.push, INTEGRATOR, self.final)
        self.result.final_branch = self.final
        self._emit("final", branch=self.final)


def _integrator_agent():
    from harness.agent import Agent
    from harness.schema.permission import Rule

    system = """You are the integrator on a small autonomous engineering team. Developers work in parallel on feature branches; you merge them into the integration branch and keep it working.

When a merge conflicts: understand what each side intended (the developers' explanations are in the message), edit the conflicted files so both intentions survive, remove every conflict marker (<<<<<<<, =======, >>>>>>>), run the project's tests, and fix what the merge broke. Do not commit and do not push: the engine completes the merge. Never discard one side's work without saying why."""
    return Agent(id=agent_id(INTEGRATOR), name="Integrator", mode="primary", description="Integrator", system=system, permissions=[Rule("question", "*", "deny")])


def render_report(spec: Spec, res: TeamResult, roster: dict[str, str]) -> str:
    s = f"# Team Report — {spec.project_name}\n\n**Run:** `{res.run_id}`  \n**Result:** {'verification passed' if res.passed else 'NOT verified'}  \n"
    s += f"**Integration branch:** `{res.integration_branch}`  \n**Final branch for you to review:** `{res.final_branch or '(not produced)'}`\n\n"
    s += "## Features\n\n| Feature | Owner | Branch | Result | Conflicts | Notes |\n|---|---|---|---|---|---|\n"
    for f in res.features:
        note = re.sub(r"[|\n]+", " ", f.summary)[:200]
        s += f"| {f.id} | {f.owner} ({roster.get(f.owner, '').title()}) | `{f.branch}` | {f.status} | {f.conflicts} | {note} |\n"
    if res.verification:
        s += "\n## Verification\n\n| Command | Exit |\n|---|---|\n" + "".join(f"| `{c}` | {code} |\n" for c, code, _ in res.verification)
    if res.decisions:
        s += "\n## Design decisions\n\n" + "\n".join(f"- {d.title} ({d.proposer}): {'approved' if d.approved else 'rejected'}" + (f", see `{d.adr}`" if d.adr else "") for d in res.decisions) + "\n"
    if res.warnings:
        s += "\n## Warnings\n\n" + "\n".join(f"- {w}" for w in res.warnings) + "\n"
    s += (
        f"\n## Your turn\n\nNothing has been merged into main. Review `{res.final_branch}` and, when you are happy, merge it yourself:\n\n"
        f"```text\ngit fetch <team remote> {res.final_branch}\ngit merge {res.final_branch}\n```\n"
    )
    return s
