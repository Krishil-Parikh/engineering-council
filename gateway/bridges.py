"""Backend to browser: the meeting's reporter and the team engine's events, translated into the frontend contract.

Both bridges only *listen*: they use the meeting's `Reporter` hooks and the team engine's `on_event` stream, plus read-only access to files and engine
state. They never change how a run behaves."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from gateway.models import Question
from gateway.narrator import SCRUM_MASTER_ID, SME_ID, ROLE_TITLES, Narrator, agent_id, clip
from meetings.meeting import Reporter
from meetings.models import Answer, HumanQuestion

if TYPE_CHECKING:
    from gateway.runner import WorkspaceRun

log = logging.getLogger("gateway.bridges")
KICKOFF = "01"  # the meeting's own conversation
DOCUMENTS = (("art-prd", "Product Requirements", "PRD.md"), ("art-tech", "Technical Approach", "Technical_Approach.md"), ("art-design", "Design", "Design.md"))


# ---------------------------------------------------------------------------------------------- questions waiting for the human


@dataclass
class Pending:
    id: str
    kind: str  # meeting | approval | documents
    resolve: Callable[[str], None]
    meet_key: str


class Questions:
    """What the human has been asked and has not answered yet. Each one is a card in the transcript; answering it resolves whatever is waiting."""

    def __init__(self, narrator: Narrator) -> None:
        self.n, self.pending, self._count = narrator, {}, 0  # type: ignore[var-annotated]

    def open(self, meet_key: str, kind: str, text: str, context: str, options: list[str], recommended: Optional[str], resolve: Callable[[str], None], qid: Optional[str] = None) -> str:
        self._count += 1
        qid = qid or f"q-{self.n.prefix}{self._count}"
        self.pending[qid] = Pending(qid, kind, resolve, meet_key)
        card = Question(id=qid, context=clip(context, 1500), kind=kind, options=options, recommended=recommended)  # type: ignore[arg-type]
        self.n.say(meet_key, "scrum-master", text, kind="question", question=card)
        self.n.agent("human", status="speaking", activeTask="Waiting for your answer")
        return qid

    def find(self, question_id: Optional[str] = None, kind: Optional[str] = None) -> Optional[Pending]:
        if question_id:
            return self.pending.get(question_id)
        candidates = [q for q in self.pending.values() if kind is None or q.kind == kind]
        return candidates[0] if candidates else None

    def answer(self, text: str, question_id: Optional[str] = None, kind: Optional[str] = None) -> Optional[Pending]:
        item = self.find(question_id, kind)
        if item is None:
            return None
        self.pending.pop(item.id, None)
        self.n.say(item.meet_key, "human", text, kind="answer", answers=item.id)
        if not self.pending:
            self.n.agent("human", status="idle", activeTask=None)
        item.resolve(text)
        return item

    def drop(self, question_id: str) -> None:
        self.pending.pop(question_id, None)
        if not self.pending:
            self.n.agent("human", status="idle", activeTask=None)


# ---------------------------------------------------------------------------------------------- the documents


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def reviewers_who_agreed(meeting_dir: Path) -> list[str]:
    """The developers whose last design-review round was satisfied with the directory structure and the architecture."""
    try:
        data = json.loads((meeting_dir / "design_review.json").read_text(encoding="utf-8"))
        last = (data.get("rounds") or [[]])[-1]
    except (OSError, ValueError):
        return []
    return [f"DEV_{str(r['agent_id']).split('_')[-1]}" for r in last if r.get("directory_ok") and r.get("architecture_ok")]


def publish_documents(run: "WorkspaceRun", status: str, human_accepted: bool = False) -> None:
    """Shows PRD.md, Technical_Approach.md and Design.md as artifacts, with their text, who has agreed, and whether you have accepted."""
    n, meeting_dir = run.narrator, run.meeting_dir
    if meeting_dir is None:
        return
    agreed = reviewers_who_agreed(meeting_dir)
    developers = [a for a in n.p.agents.values() if a["id"].startswith("agent-") and a["id"] != SCRUM_MASTER_ID]
    for art_id, title, filename in DOCUMENTS:
        text = read_text(meeting_dir / filename)
        if not text:
            continue
        accepted = [*agreed, *(["SME-01"] if human_accepted else [])]
        created = time.strftime("%H:%M:%S")
        payload = {
            "id": art_id, "title": title, "filename": filename, "status": status, "currentVersion": f"v{run.document_revisions + 1}.0",
            "acceptedCount": len(accepted), "totalRequired": max(len(developers), len(agreed)) + 1, "acceptedBy": accepted, "markdownContent": text,
            "versions": [{"version": f"v{i + 1}.0", "timestamp": created, "author": "Scrum Master", "summary": "Written by the pod meeting" if i == 0 else "Revised after your feedback",
                          "diffAdditions": [], "diffDeletions": [], "acceptedBy": accepted if i == run.document_revisions else []} for i in range(run.document_revisions + 1)],
        }
        n.p.emit("artifact.updated", payload)


# ---------------------------------------------------------------------------------------------- the meeting


class MeetingBridge(Reporter):
    """Stands in for the terminal reporter: every line the meeting prints becomes a message, every question a card, every stage a step."""

    def __init__(self, run: "WorkspaceRun") -> None:
        super().__init__(verbose=False, out=lambda text: None)
        self.run, self.n = run, run.narrator
        self.objections = self.decisions = 0

    def _meet(self, status: str = "live") -> None:
        total = self.objections + self.decisions
        consensus = round(100 * self.decisions / total, 1) if total else 0
        self.n.meet(KICKOFF, f"Kickoff meeting: {self.run.project_name}", status, consensus=consensus, debate=min(100, 12 * self.objections))

    def stage(self, n: int, label: str) -> None:
        self.run.set_phase("brainstorm")
        self._meet("live")
        self.n.system(KICKOFF, f"[{n}/10] {label}")

    def say(self, who: str, text: str) -> None:
        self.n.say(KICKOFF, who, text)

    def publish(self, kind: str, who: str, title: str, body: str) -> None:
        if kind in ("objection", "rebuttal", "dispute"):
            self.objections += 1
        elif kind == "decision":
            self.decisions += 1
        self._meet("live")
        self.n.say(KICKOFF, who, f"{title}\n\n{body}" if body and body.strip() != title.strip() else title)

    def roster(self, skills: dict[str, str]) -> None:
        counts: dict[str, int] = {}
        for dev, skill in skills.items():
            counts[skill] = counts.get(skill, 0) + 1
            self.n.agent(dev, role=ROLE_TITLES.get(skill, skill.title() + " Developer"), claimedSkill=skill.title(), status="idle")
            self.n.edge("scrum-master", dev, "Delegation")
        for skill, count in counts.items():
            self.n.p.emit("skill.updated", {"id": f"skill-{skill.lower()}", "name": skill.title(), "claimedCount": count})
        self.n.system(KICKOFF, "Skills taken: " + ", ".join(f"{dev} → {skill.title()}" for dev, skill in skills.items()))

    def note(self, text: str) -> None:
        self.n.system(KICKOFF, text)

    def warn(self, text: str) -> None:
        self.n.system(KICKOFF, f"Warning: {text}")

    async def ask(self, questions: list[HumanQuestion], interactive: bool, input_fn: Callable[[str], str]) -> list[Answer]:
        answers: list[Answer] = []
        loop = asyncio.get_running_loop()
        for index, q in enumerate(questions, 1):
            if not interactive:
                answers.append(Answer(question=q.question, answer=q.recommended_default, source="non_interactive_default"))
                continue
            future: asyncio.Future[str] = loop.create_future()
            body = f"Question {index} of {len(questions)}: {q.question}"
            context = f"Why it matters: {q.why_it_matters}\n\n" + "\n".join(f"- {opt}{'  (recommended)' if opt == q.recommended_default else ''}" for opt in q.options)
            self.run.questions.open(KICKOFF, "meeting", body, context, list(q.options), q.recommended_default, lambda text, f=future: f.done() or f.set_result(text))
            text = (await future).strip()
            if not text:
                answers.append(Answer(question=q.question, answer=q.recommended_default, source="default"))
            elif text in q.options:
                answers.append(Answer(question=q.question, answer=text, source="option"))
            else:
                answers.append(Answer(question=q.question, answer=text, source="custom"))
        return answers

    def finished(self, passed: bool) -> None:
        self._meet("completed")
        self.n.system(KICKOFF, "The meeting is done. The documents are ready for you to read." if passed else "The meeting finished with verification failures; read the documents carefully.")


# ---------------------------------------------------------------------------------------------- the team


def pretty_reply(text: str) -> str:
    """Developers answer ceremonies in JSON; the transcript reads better as short labelled lines."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return "\n".join(f"{key.replace('_', ' ').capitalize()}: {value}" for key, value in data.items() if value not in ("", None, [], {}))
        except ValueError:
            pass
    return text


class TeamBridge:
    """Turns the team engine's events (and the agile state behind them) into agents, messages, meets, sprints, artifacts and metrics."""

    def __init__(self, run: "WorkspaceRun") -> None:
        self.run, self.n = run, run.narrator
        self.sprint_phase: dict[int, str] = {}
        self.merges: dict[str, int] = {}
        self.verifying = False

    # -- helpers
    @property
    def engine(self):
        return self.run.engine

    def state(self):
        return self.engine.agile.store.state if self.engine is not None and self.engine.agile is not None else None

    def update_sprints(self) -> None:
        state = self.state()
        if state is None:
            return
        for s in state.sprints:
            done = len(state.sprint_tasks(s.number))
            progress = round(100 * min(done, s.planned_tasks) / s.planned_tasks) if s.planned_tasks else 0
            closed = s.status == "closed"
            payload = {
                "id": f"sprint-{self.n.prefix}{s.number}", "number": f"{s.number:02d}", "title": f"Sprint {s.number:02d}: {s.goal or 'planning'}",
                "phase": "Closed" if closed else self.sprint_phase.get(s.number, "Work"), "progress": 100 if closed and s.planned_tasks == done else progress,
                "status": "completed" if closed else "active",
            }
            if self.n.p.sprints.get(payload["id"]) != payload:
                self.n.p.emit("sprint.updated", payload)

    def metrics(self) -> None:
        history = list(self.n.p.metrics.get("prHistory", []))
        hour = time.strftime("%H:00")
        if history and history[-1]["time"] == hour:
            history[-1] = {"time": hour, "prs": history[-1]["prs"] + 1}
        else:
            history.append({"time": hour, "prs": 1})
        merged = sum(self.merges.values())
        self.n.p.emit("metrics.updated", {"totalMessagesToday": len(self.n.p.messages), "totalPRs": merged, "prHistory": history})

    def meet_for(self, topic: str) -> tuple[str, str]:
        """Which conversation a message belongs to, from the topic of the A2A exchange."""
        state = self.state()
        sprint = state.sprint if state else 0
        t = (topic or "").lower()
        if m := re.search(r"standup (\d+)", t):
            return f"s{sprint}-standup{m.group(1)}", f"Sprint {sprint} standup {m.group(1)}"
        for word, key, title in (("planning", "planning", "planning"), ("commitment", "planning", "planning"), ("review", "review", "review"), ("report", "report", "report"),
                                 ("retrospective", "retro", "retrospective"), ("document sync", "docs", "document sync")):
            if word in t and "sprint" in t:
                return f"s{sprint}-{key}", f"Sprint {sprint} {title}"
        if t.startswith("design change"):
            slug = re.sub(r"[^a-z0-9]+", "-", t.replace("design change:", "")).strip("-")[:30] or "vote"
            return f"design-{slug}", "Design change: " + topic.split(":", 1)[-1].strip()
        if "work plan" in t:
            return "plan", "Work plan"
        if "merge conflict" in t:
            return "merge", "Merge conflicts"
        if "briefing" in t:
            return "briefings", "Briefings from the scrum master and you"
        if "human directive" in t or "stop and rethink" in t or "course correction" in t or "emergency" in t:
            return "directives", "Your directions to the team"
        return "team", "Team conversation"

    def deactivate_later(self, a: str, b: str, label: str) -> None:
        loop = self.run.loop
        if loop is not None:
            loop.call_later(6.0, lambda: self.n.edge(a, b, label, active=False))

    # -- the stream
    def handle(self, kind: str, data: dict) -> None:
        if ":" in kind and kind.split(":", 1)[0].upper().startswith(("DEV_", "INTEGRATOR")):
            return  # a developer's harness chatter (every message and tool call); the ceremonies and tasks above are what the browser shows
        try:
            self._handle(kind, data)
        except Exception:  # noqa: BLE001 - a display problem must never stop the build
            log.exception("could not translate %s", kind)

    def _handle(self, kind: str, d: dict) -> None:
        n, run = self.n, self.run
        if kind == "plan":
            features = d["plan"]["features"]
            for f in features:
                n.edge("scrum-master", f["owner"] or "DEV_1", f"Owns {f['id']}")
            n.meet("plan", "Work plan", "completed")
            n.system("plan", "Work plan: " + "; ".join(f"{f['id']} → {f['owner']}" + (f" (after {', '.join(f['depends_on'])})" if f["depends_on"] else "") for f in features))
        elif kind == "feature-started":
            n.agent(d["owner"], status="active", activeTask=f"Starting {d['feature']}", activeBranch=f"feature/{d['feature']}")
            n.edge("scrum-master", d["owner"], f"Owns {d['feature']}", active=True)
        elif kind == "task":
            n.agent(d["owner"], status="active", activeTask=f"{d['feature']}: {d['title']} ({d['index']}/{d['total']})")
            self.update_sprints()
        elif kind == "feature-done":
            n.agent(d["owner"], status="complete", activeTask=None)
            n.edge("scrum-master", d["owner"], f"Owns {d['feature']}", active=False)
            self.merges[d["feature"]] = 1
            self.metrics()
            n.system("team", f"Merged {d['feature']} ({d['owner']}): {d.get('detail', '')}")
            self.update_sprints()
        elif kind == "feature-failed":
            n.agent(d["owner"], status="blocked", activeTask=f"{d['feature']} failed")
            n.system("team", f"Feature {d['feature']} failed: {clip(d.get('detail', ''), 300)}")
        elif kind in ("feature-blocked", "feature-dropped", "feature-requeued"):
            n.system("team", f"{kind.replace('feature-', 'Feature ')} {d['feature']}: {clip(d.get('detail', ''), 200)}".strip())
        elif kind == "conflict":
            n.system("merge", f"Merge conflict for {d['feature']} in {', '.join(d['files'])}")
        elif kind == "talk":
            self.talk(d)
        elif kind in ("git-trouble", "git-gave-up"):
            n.system("team", f"git: {d.get('goal', '')} failed ({clip(d.get('error', ''), 160)})")
        elif kind == "sprint-planned":
            self.sprint_phase[d["sprint"]] = "Planning"
            key, title = f"s{d['sprint']}-planning", f"Sprint {d['sprint']} planning"
            n.meet(key, title, "live")
            n.say(key, "scrum-master", f"Sprint {d['sprint']} planned: {d['goal']}\n{d['tasks']} task(s) in {len(d['features'])} feature(s): {', '.join(d['features'])}"
                  + (f"\nCarried over: {', '.join(d['carried'])}" if d.get("carried") else ""))
            n.meet(key, title, "completed")
            self.update_sprints()
        elif kind == "day-start":
            self.sprint_phase[d["sprint"]] = f"Work, day {d['day']}"
            self.update_sprints()
        elif kind == "standup":
            self.sprint_phase[d["sprint"]] = f"Standup {d['number']}"
            key = f"s{d['sprint']}-standup{d['number']}"
            n.meet(key, f"Sprint {d['sprint']} standup {d['number']}", "completed")
            n.say(key, "scrum-master", f"Standup {d['number']}, day {d['day']}: {d['summary']}")
            self.update_sprints()
        elif kind == "impediment":
            n.agent(d["dev"], status="blocked")
            n.system("team", f"Impediment {d['id']} ({d['dev']}): {clip(d['text'], 300)}")
        elif kind == "sprint-review":
            self.sprint_phase[d["sprint"]] = "Review"
            key = f"s{d['sprint']}-review"
            n.meet(key, f"Sprint {d['sprint']} review", "completed")
            n.say(key, "scrum-master", f"Review: goal {'met' if d['goal_met'] else 'not met'}. {d['summary']}")
            self.update_sprints()
        elif kind == "sprint-report":
            self.sprint_phase[d["sprint"]] = "Report"
            n.say(f"s{d['sprint']}-report", "scrum-master", f"Sprint {d['sprint']} delivered {d['completed']} of {d['planned']} planned tasks.")
            n.meet(f"s{d['sprint']}-report", f"Sprint {d['sprint']} report", "completed")
        elif kind == "sprint-retro":
            self.sprint_phase[d["sprint"]] = "Retrospective"
            n.meet(f"s{d['sprint']}-retro", f"Sprint {d['sprint']} retrospective", "completed")
            n.say(f"s{d['sprint']}-retro", "scrum-master", "Actions for the next sprint: " + ("; ".join(d["actions"]) or "none"))
            self.update_sprints()
        elif kind == "doc-sync":
            n.say(f"s{self.state().sprint if self.state() else 0}-docs", "scrum-master", f"Documents: {len(d['applied'])} of {d['proposed']} proposed change(s) applied.")
        elif kind == "agile-docs":
            self.agile_artifacts(d.get("files", []))
        elif kind == "approval-requested":
            self.approval_requested(d)
        elif kind == "approval-answered":
            self.approval_answered(d)
        elif kind == "verification":
            self.verifying = True
            run.set_phase("review")
            n.system("team", f"Final verification: {d['failing']} failing command(s) (attempt {d['attempt'] + 1})")
        elif kind == "final":
            run.set_phase("ship")
            n.system("team", f"The final branch {d['branch']} is ready for you to review. Nothing has been merged into main.")
        elif kind == "published":
            n.system("team", f"Pushed {', '.join(d['branches'])} to {d['target']}")
        elif kind == "pull-request":
            n.system("team", f"Pull request opened: {d['url']}")
        elif kind == "interrupted":
            n.system("directives", "The team is paused for you.")
        elif kind == "resumed":
            n.system("directives", "Work resumes.")
        elif kind == "directive-handled":
            n.say("directives", "scrum-master", f"{d['kind']}: {clip(d['effect'], 600)}")
        elif kind == "agile-warning":
            n.system("team", clip(d["text"], 300))
        elif kind == "agile-state":
            self.update_sprints()

    def talk(self, d: dict) -> None:
        n = self.n
        key, title = self.meet_for(d.get("topic", ""))
        sender, recipient = d.get("sender", "system"), d.get("recipient", "")
        n.meet(key, title, "live")
        reply = d.get("reply") or ""
        if agent_id(sender) != agent_id(recipient):
            n.edge(sender, recipient, clip(d.get("topic", ""), 40), active=True)
            self.deactivate_later(sender, recipient, clip(d.get("topic", ""), 40))
        if reply:
            n.say(key, recipient, pretty_reply(reply))

    def agile_artifacts(self, files: list[str]) -> None:
        engine = self.engine
        if engine is None:
            return
        sandbox = engine.repo.sandbox_path("integrator")
        for path in files:
            if not path.endswith(".md") or not path.startswith("docs/agile/"):
                continue
            text = read_text(sandbox / path)
            if not text:
                continue
            heading = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), Path(path).stem)
            art_id = "art-" + re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
            self.n.p.emit("artifact.updated", {
                "id": art_id, "title": heading, "filename": path, "status": "approved", "currentVersion": "v1.0", "acceptedCount": 0, "totalRequired": 0,
                "markdownContent": text, "acceptedBy": [],
            })

    def approval_requested(self, d: dict) -> None:
        run, n = self.run, self.n
        qid = d["id"]
        is_docs = d.get("kind") == "docs" and "documents" in d["title"].lower()
        if is_docs:
            run.docs_approval_ids.add(qid)
            run.set_phase("prd")
            publish_documents(run, "in_review")
        options = ["Approve", "Decline"]
        run.questions.open(
            "prd" if is_docs else "decisions", "documents" if is_docs else "approval",
            d["title"], d.get("detail", ""), options, "Approve" if is_docs else None,
            lambda text, approval=qid: run.resolve_approval(approval, text), qid=qid,
        )
        n.meet("prd" if is_docs else "decisions", "Document review" if is_docs else "Decisions waiting for you", "live")

    def approval_answered(self, d: dict) -> None:
        run = self.run
        if d["id"] in run.questions.pending:
            run.questions.drop(d["id"])
        if d["id"] in run.docs_approval_ids:
            if d["approved"]:
                run.document_accepted = True
                publish_documents(run, "approved", human_accepted=True)
                run.set_phase("build")
                self.n.system("prd", "You accepted the documents. Development starts now.")
            else:
                run.document_revisions += 1
                publish_documents(run, "in_review")
                self.n.system("prd", "You asked for changes; the documents are being revised.")
