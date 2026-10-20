"""Standup, inside the gateway: records the FORMAL meetings of a run as a structured, replayable event stream.

It listens to the workspace's own event stream (the narrator's meets, messages and documents, which are exactly the conversations meant to be seen), so nothing
in `meetings/` or `team/` changes. Merge talk, tool calls and a developer's chatter never reach it: only the meetings named in `classify` do.

Each recorded event is stored first (standup/), then announced on the workspace stream as `standup.event`, and to anyone watching one meeting."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from gateway.narrator import SCRUM_MASTER_ID, SME_ID, clip
from standup import MeetingService, MeetingType
from standup.adapters.files import FileProjections
from standup.adapters.jsonl_store import JsonlEventStore
from standup.enums import TERMINAL_STATUSES, ControlMode, ParticipantStatus
from standup.errors import StandupError
from standup.events import MeetingEvent

if TYPE_CHECKING:
    from gateway.runner import WorkspaceRun

log = logging.getLogger("gateway.standup")

CLASSES = (  # which narrator conversations are formal meetings
    (re.compile(r"^01$"), MeetingType.DISCOVERY, "kickoff"),
    (re.compile(r"^plan$"), MeetingType.SPRINT_PLANNING, "work-plan"),
    (re.compile(r"^prd$"), MeetingType.PRD_REVIEW, "document-review"),
    (re.compile(r"^decisions$"), MeetingType.SME_CHECKPOINT, "decisions"),
    (re.compile(r"^directives$"), MeetingType.SME_CHECKPOINT, "directives"),
    (re.compile(r"^(s\d+-planning)$"), MeetingType.SPRINT_PLANNING, None),
    (re.compile(r"^(s\d+-standup\d+)$"), MeetingType.DAILY_STANDUP, None),
    (re.compile(r"^(s\d+-review)$"), MeetingType.SPRINT_REVIEW, None),
    (re.compile(r"^(s\d+-retro)$"), MeetingType.SPRINT_RETROSPECTIVE, None),
    (re.compile(r"^(s\d+-report)$"), MeetingType.CUSTOM, None),
    (re.compile(r"^(s\d+-docs)$"), MeetingType.CUSTOM, None),
    (re.compile(r"^(design-.+)$"), MeetingType.DESIGN_REVIEW, None),
)
DOCUMENT_FILES = {"PRD.md", "Technical_Approach.md", "Design.md"}
HINTS = {"objection": "challenge", "dispute": "challenge", "rebuttal": "counterargument", "reconsideration": "counterargument", "proposal": "proposal", "blind": "brainstorm"}
APPROVE = re.compile(r"^(approve|approved|accept|yes|y|ok|okay|lgtm)\b", re.I)
QUICK = {"kickoff", "document-review", "decisions", "directives"}  # meetings that are over when they say so
GRACE_QUICK = 1.5
GRACE_CEREMONY = 20.0  # the team marks a sprint ceremony completed and then keeps talking in it: it stays open until it has been quiet this long


def classify(meet_id: str) -> Optional[tuple[MeetingType, str]]:
    """(meeting type, standup meeting id) for a narrator conversation, or None when it is not a formal meeting (merge talk, team chatter, briefings)."""
    key = meet_id[5:] if meet_id.startswith("meet-") else meet_id
    for pattern, kind, fixed in CLASSES:
        m = pattern.match(key)
        if m:
            return kind, fixed or m.group(1)
    return None


class StandupHub:
    def __init__(self, run: "WorkspaceRun") -> None:
        self.run = run
        self.base = Path(run.settings.data_dir) / run.workspace_id / "standup"
        self.hint: Optional[str] = None  # set by the meeting bridge around one message: what kind of contribution it is
        self.autopilot = False
        self.autopilot_answers: set[str] = set()  # question ids the autopilot SME answered (so the record says so)
        self.dropped = 0
        self._lock = threading.RLock()
        self._queue: deque[dict[str, Any]] = deque()
        self._closing: dict[str, float] = {}
        self._subscribers: dict[asyncio.Queue, Optional[str]] = {}
        self._readers: dict[str, MeetingService] = {}
        self.tag = self._saved_tag() or self._new_tag()
        self.service = self._service(self.tag)
        self._write_tag()
        run.p.listeners.append(self.on_event)

    # ------------------------------------------------------------------ where the record lives

    def _saved_tag(self) -> Optional[str]:
        try:
            tag = (self.base / "current.txt").read_text(encoding="utf-8").strip()
            return tag if tag and (self.base / tag).is_dir() else None
        except OSError:
            return None

    @staticmethod
    def _new_tag() -> str:
        return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]

    def _write_tag(self) -> None:
        try:
            self.base.mkdir(parents=True, exist_ok=True)
            (self.base / "current.txt").write_text(self.tag, encoding="utf-8")
        except OSError:
            log.warning("could not remember which standup folder is current")

    def _service(self, tag: str, live: bool = True) -> MeetingService:
        root = self.base / tag
        return MeetingService(
            self.run.workspace_id, JsonlEventStore(root), writers=[FileProjections(root)] if live else [], publishers=[self] if live else [],
        )

    def runs(self) -> list[str]:
        """Every earlier run's record, newest first (the current one included)."""
        try:
            return sorted((p.name for p in self.base.iterdir() if p.is_dir()), reverse=True)
        except OSError:
            return []

    def reader(self, tag: Optional[str]) -> MeetingService:
        """The service for the current run, or a read-only one for an earlier run (replay after a restart or a new project)."""
        if not tag or tag == self.tag:
            return self.service
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", tag) or not (self.base / tag).is_dir():
            raise StandupError(f"no standup record named {tag!r}")
        return self._readers.setdefault(tag, self._service(tag, live=False))

    def folder(self, meeting_id: str, tag: Optional[str] = None) -> Path:
        return self.base / (tag or self.tag) / self.run.workspace_id / meeting_id

    def reset(self) -> None:
        """A new project starts a new record; the old one stays on disk and can still be replayed."""
        self._sweep(force=True)  # close the old project's meetings (what is queued after this belongs to the new project and must not be touched)
        with self._lock:
            self._closing.clear()
            self.autopilot_answers.clear()
            self.autopilot = False
            self.tag = self._new_tag()
            self.service = self._service(self.tag)
            self._write_tag()

    # ------------------------------------------------------------------ listening to the run

    def on_event(self, ev: dict[str, Any]) -> None:
        if ev.get("type") == "standup.event":
            return
        with self._lock:
            self._queue.append(ev)
        loop = self.run.loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._drain)  # after the current event has reached the browsers, so the two streams stay in order
        else:
            self._drain()

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    break
                ev = self._queue.popleft()
            try:
                self._handle(ev)
            except StandupError as exc:
                self.dropped += 1
                log.warning("standup: left out %s: %s", ev.get("type"), exc)
            except Exception:  # noqa: BLE001 - recording a meeting must never stop the run
                self.dropped += 1
                log.exception("standup: could not record %s", ev.get("type"))
        self._sweep()

    def flush(self) -> None:
        """Records whatever is queued and closes the meetings that were marked completed."""
        self._drain()
        self._sweep(force=True)

    def _handle(self, ev: dict[str, Any]) -> None:
        kind, p = ev["type"], ev["payload"]
        if kind == "workspace.reset":
            self.reset()
        elif kind == "meet.updated":
            self._on_meet(p)
        elif kind == "message.created":
            self._on_message(p)
        elif kind == "artifact.updated":
            self._on_artifact(p)
        elif kind == "agent.updated":
            self._on_agent(p)

    # ------------------------------------------------------------------ meetings

    def _control(self) -> ControlMode:
        return ControlMode.AUTOPILOT if self.autopilot else ControlMode.HUMAN

    def _ensure(self, meet_id: str, title: str = "") -> Optional[str]:
        found = classify(meet_id)
        if found is None:
            return None
        kind, mid = found
        svc = self.service
        try:
            svc.state(mid)
        except StandupError:
            svc.create_meeting(title or meet_id, kind, meeting_id=mid, control_mode=self._control(), created_by="gateway")
            self._join(mid, SME_ID, "Business SME", "business_sme")
            self._join(mid, SCRUM_MASTER_ID, "Scrum Master", "scrum_master")
        return mid

    def _live(self, mid: str) -> bool:
        st = self.service.state(mid)
        return st.meeting is not None and st.meeting.status not in TERMINAL_STATUSES

    def _start(self, mid: str) -> None:
        st = self.service.state(mid)
        if st.meeting is not None and st.meeting.started_at is None and self._live(mid):
            self.service.publish(mid, "meeting_started", actor_id="system", idempotency_key=f"start:{mid}")

    def _join(self, mid: str, pid: str, name: str, kind: str) -> None:
        st = self.service.state(mid)
        person = st.participants.get(pid)
        if person is not None and person.status != ParticipantStatus.LEFT:
            return
        agent = self.run.p.agents.get(pid, {})
        payload: dict[str, Any] = {"participant_id": pid, "display_name": agent.get("name") or name, "participant_type": kind, "agent_id": pid}
        if agent.get("claimedSkill"):
            payload["skill"] = str(agent["claimedSkill"]).lower()
        self.service.publish(mid, "participant_joined", payload, actor_id="system")

    def _person(self, mid: str, pid: str, name: str) -> None:
        kind = "business_sme" if pid == SME_ID else "scrum_master" if pid == SCRUM_MASTER_ID else "developer"
        self._join(mid, pid, name, kind)

    def _on_meet(self, p: dict[str, Any]) -> None:
        mid = self._ensure(p["id"], p.get("title", ""))
        if mid is None:
            return
        if p.get("status") == "live":
            self._start(mid)
            self._closing.pop(mid, None)
        elif p.get("status") == "completed" and self._live(mid):
            self._start(mid)
            self._close_soon(mid)

    def _close_soon(self, mid: str) -> None:
        grace = GRACE_QUICK if mid in QUICK else GRACE_CEREMONY
        self._closing[mid] = time.monotonic() + grace
        loop = self.run.loop
        if loop is not None and loop.is_running():
            loop.call_later(grace + 0.1, self._sweep)

    def _sweep(self, force: bool = False) -> None:
        now = time.monotonic()
        for mid in [m for m, deadline in self._closing.items() if force or deadline <= now]:
            self._closing.pop(mid, None)
            try:
                if self._live(mid):
                    self.service.publish(mid, "meeting_ended", actor_id="system", idempotency_key=f"end:{mid}")
            except StandupError as exc:
                log.warning("standup: could not end %s: %s", mid, exc)

    def _followup(self, mid: str) -> Optional[str]:
        """A meeting that has ended gets a follow-up when something more is said in it (the team marks a ceremony completed and carries on talking)."""
        follow = f"{mid}-followup"[:80]
        svc = self.service
        try:
            state = svc.state(follow)
        except StandupError:
            title = svc.state(mid).meeting.title if svc.state(mid).meeting else mid  # type: ignore[union-attr]
            svc.create_meeting(f"{title} (follow-up)", MeetingType.CUSTOM, meeting_id=follow, control_mode=self._control(), created_by="gateway")
            self._join(follow, SME_ID, "Business SME", "business_sme")
            self._join(follow, SCRUM_MASTER_ID, "Scrum Master", "scrum_master")
            self._start(follow)
            self._close_soon(follow)
            return follow
        return follow if state.meeting is not None and state.meeting.status not in TERMINAL_STATUSES else None

    def _on_message(self, p: dict[str, Any]) -> None:
        mid = self._ensure(p["meetId"])
        if mid is None:
            return
        if not self._live(mid):
            mid = self._followup(mid)  # real content that came after the meeting went quiet is kept, in a follow-up
            if mid is None:
                self.dropped += 1
                log.warning("standup: a late message was not recorded: %s", clip(p.get("text", ""), 120))
                return
        self._start(mid)
        if mid in self._closing:
            self._close_soon(mid)  # it is still being talked in
        sender = p["senderId"]
        self._person(mid, sender, p.get("senderName") or sender)
        svc, text, key = self.service, (p.get("text") or "").strip(), f"msg:{p['id']}"
        hint, self.hint = self.hint, None
        card = p.get("question")
        if p.get("kind") == "question" and card:
            qid = card["id"]
            if card.get("kind", "meeting") == "meeting":
                svc.publish(mid, "clarification_requested", {"question_id": qid, "text": text or card.get("context", "?"), "context": card.get("context", ""), "options": card.get("options", []),
                                                             "recommended": card.get("recommended")}, actor_id=sender, idempotency_key=key)
            else:
                svc.publish(mid, "sme_approval_requested", {"request_id": qid, "subject": text or "approval", "context": card.get("context", ""), "kind": card.get("kind"),
                                                            "options": card.get("options", [])}, actor_id=sender, idempotency_key=key)
        elif p.get("kind") == "answer" and p.get("answersQuestion"):
            qid, st = p["answersQuestion"], svc.state(mid)
            source = "autopilot" if qid in self.autopilot_answers else "human"
            if qid in st.questions:
                svc.publish(mid, "clarification_answered", {"question_id": qid, "answer": text or "(no answer)", "source": source}, actor_id=sender, idempotency_key=key)
            elif qid in st.approvals:
                svc.publish(mid, "sme_approved" if APPROVE.match(text) else "sme_rejected", {"request_id": qid, "comment": text, "source": source}, actor_id=sender, idempotency_key=key)
        elif p.get("kind") == "system":
            if re.match(r"^\[\d+/\d+\]", text):
                svc.publish(mid, "topic_started", {"topic": text}, actor_id="system", idempotency_key=key)
            else:
                svc.publish(mid, "facilitator_intervention", {"text": text}, actor_id=SCRUM_MASTER_ID, idempotency_key=key)
        elif text and hint == "decision":
            title = text.split("\n", 1)[0]
            did = "dec-" + re.sub(r"[^A-Za-z0-9]+", "-", p["id"]).strip("-")
            svc.publish(mid, "decision_proposed", {"decision_id": did, "title": clip(title, 200), "context": text}, actor_id=sender, idempotency_key=f"{key}:p")
            svc.publish(mid, "decision_accepted", {"decision_id": did}, actor_id=sender, idempotency_key=f"{key}:a")
        elif text:
            svc.publish(mid, HINTS.get(hint or "", "statement"), {"text": text}, actor_id=sender, idempotency_key=key)

    def _on_artifact(self, p: dict[str, Any]) -> None:
        path = p.get("filename")
        if path not in DOCUMENT_FILES:
            return
        mid = self._ensure("meet-prd", "Document review")
        if mid is None or not self._live(mid):
            return
        self._start(mid)
        version = p.get("currentVersion", "v1.0")
        svc, st = self.service, self.service.state(mid)
        if path not in st.documents:
            svc.publish(mid, "document_created", {"path": path, "title": p.get("title"), "version": version}, actor_id=SCRUM_MASTER_ID, idempotency_key=f"doc:{path}:{version}")
        status = p.get("status")
        review = st.reviews.get(path)
        if status == "in_review" and (review is None or review.status.value != "in_review"):
            svc.publish(mid, "document_review_started", {"path": path, "reviewer_id": SME_ID, "version": version}, actor_id=SCRUM_MASTER_ID, idempotency_key=f"review:{path}:{version}")
        elif status == "approved":
            if review is None or review.status.value != "in_review":
                svc.publish(mid, "document_review_started", {"path": path, "reviewer_id": SME_ID, "version": version}, actor_id=SCRUM_MASTER_ID, idempotency_key=f"review:{path}:{version}")
            svc.publish(mid, "document_approved", {"path": path, "version": version}, actor_id=SME_ID, idempotency_key=f"approve:{path}:{version}")

    def _on_agent(self, p: dict[str, Any]) -> None:
        skill = p.get("claimedSkill")
        if not skill:
            return
        for meeting in self.service.meetings():
            if meeting.status in TERMINAL_STATUSES:
                continue
            person = self.service.state(meeting.meeting_id).participants.get(p["id"])
            if person is not None and person.status != ParticipantStatus.LEFT and person.skill != str(skill).lower():
                self.service.publish(meeting.meeting_id, "skill_selected", {"participant_id": p["id"], "skill": str(skill).lower()}, actor_id="system")

    # ------------------------------------------------------------------ control

    def set_control(self, autopilot: bool) -> int:
        """The Business SME hands the meetings to the autopilot, or takes them back. Returns how many open meetings were told."""
        self.autopilot = autopilot
        told = 0
        for meeting in self.service.meetings():
            if meeting.status in TERMINAL_STATUSES or (meeting.control_mode == ControlMode.AUTOPILOT) == autopilot:
                continue
            self.service.publish(meeting.meeting_id, "autopilot_enabled" if autopilot else "human_takeover", {}, actor_id="system")
            told += 1
        return told

    # ------------------------------------------------------------------ watching

    def publish(self, event: MeetingEvent) -> None:
        """StreamPublisher: tell the workspace stream, and anyone watching this meeting."""
        self.run.p.emit("standup.event", event.wire())
        for queue, only in list(self._subscribers.items()):
            if only is None or only == event.meeting_id:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    self._subscribers.pop(queue, None)  # too slow: dropped; it reconnects from its last sequence number and misses nothing
                    try:
                        queue.put_nowait(None)  # type: ignore[arg-type]
                    except asyncio.QueueFull:
                        pass

    def subscribe(self, meeting_id: Optional[str] = None) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers[queue] = meeting_id
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.pop(queue, None)
