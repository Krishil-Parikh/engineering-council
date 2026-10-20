"""The state of one meeting, and the rules for changing it.

`MeetingState.apply(event)` is the only way state changes, and it is the same code whether the event is live or replayed from disk, so a replay always ends
where the live meeting did. It never trusts its input: a malformed or impossible event is refused and leaves the state untouched; an event it has already
applied is ignored; an event of a kind it does not know (written by a newer version) moves the sequence on and changes nothing else."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from standup.enums import (
    TERMINAL_STATUSES,
    ActionStatus,
    ControlMode,
    DecisionStatus,
    MeetingStatus,
    ParticipantStatus,
    ParticipantType,
    QuestionStatus,
    ReviewStatus,
)
from standup.errors import InvalidEvent, InvalidTransition, OutOfOrder
from standup.events import KNOWN_TYPES, MeetingEvent, check_id, validate_for_publish
from standup.models import (
    ActionItem,
    ApprovalRequest,
    Decision,
    Dependency,
    DocumentReview,
    Meeting,
    Participant,
    Question,
    Risk,
)

SME_TARGETS = frozenset({"business_sme", "sme"})
SYSTEM_ACTORS = frozenset({"system"})
SPOKEN = frozenset({"statement", "brainstorm", "proposal", "challenge", "counterargument", "facilitator_intervention"})
LIVE = frozenset({MeetingStatus.ACTIVE, MeetingStatus.WAITING_FOR_SME, MeetingStatus.REVIEWING, MeetingStatus.AWAITING_APPROVAL})
BEFORE_START = frozenset({"meeting_created", "participant_joined", "participant_left", "skill_selected", "role_assigned", "human_takeover", "autopilot_enabled", "meeting_started", "meeting_cancelled"})
WHILE_PAUSED = frozenset({"meeting_resumed", "meeting_ended", "meeting_cancelled", "meeting_timed_out", "human_takeover", "autopilot_enabled", "participant_joined", "participant_left",
                          "skill_selected", "role_assigned", "clarification_answered", "sme_approved", "sme_rejected"})
WINDOW = 256  # how many recent event ids are remembered to recognise a duplicate; older ones are told apart by their sequence number alone
RECENT = 200  # how many recent events are kept for screens


def _as_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


class MeetingState:
    def __init__(self) -> None:
        self.meeting: Optional[Meeting] = None
        self.participants: dict[str, Participant] = {}
        self.decisions: dict[str, Decision] = {}
        self.questions: dict[str, Question] = {}
        self.actions: dict[str, ActionItem] = {}
        self.reviews: dict[str, DocumentReview] = {}
        self.documents: dict[str, str] = {}
        self.risks: dict[str, Risk] = {}
        self.dependencies: dict[str, Dependency] = {}
        self.approvals: dict[str, ApprovalRequest] = {}
        self.topics_done: list[str] = []
        self.summary: str = ""
        self.speaker: Optional[str] = None
        self.last_sequence = 0
        self.last_elapsed = 0.0
        self.last_timestamp: Optional[datetime] = None
        self.paused = False
        self.paused_at: Optional[datetime] = None
        self.paused_total = timedelta(0)
        self.idempotency: dict[str, str] = {}
        self._ids: deque[tuple[int, str]] = deque(maxlen=WINDOW)
        self.recent: deque[MeetingEvent] = deque(maxlen=RECENT)
        self.unknown_events = 0

    # ------------------------------------------------------------------ applying

    def validate(self, event: MeetingEvent) -> bool:
        """Checks every rule without changing anything. True when the event has already been applied; raises when it cannot be applied."""
        if self._is_duplicate(event):
            return True
        if event.sequence_number != self.last_sequence + 1:
            raise OutOfOrder(f"event {event.sequence_number} arrived but {self.last_sequence + 1} was expected", self.last_sequence + 1)
        if event.elapsed_seconds + 1e-9 < self.last_elapsed:
            raise InvalidEvent(f"elapsed time went backwards ({event.elapsed_seconds} after {self.last_elapsed})")
        if self.meeting is not None and event.meeting_id != self.meeting.meeting_id:
            raise InvalidEvent(f"event belongs to meeting {event.meeting_id}, not {self.meeting.meeting_id}")
        if event.event_type in KNOWN_TYPES:
            self._handle(event, mutate=False)
        return False

    def apply(self, event: MeetingEvent) -> bool:
        """True when the event changed the meeting; False when it had already been applied. Raises (and changes nothing) when it cannot be applied."""
        if self.validate(event):
            return False
        if event.event_type in KNOWN_TYPES:
            self._handle(event, mutate=True)
        else:
            self.unknown_events += 1  # written by a newer version: kept in the stream, ignored here
        self.last_sequence, self.last_elapsed, self.last_timestamp = event.sequence_number, event.elapsed_seconds, event.timestamp
        self._ids.append((event.sequence_number, event.event_id))
        self.recent.append(event)
        if event.idempotency_key:
            self.idempotency[event.idempotency_key] = event.event_id
        if self.meeting is not None:
            self.meeting.version = event.sequence_number
            self._recompute()
        return True

    def apply_all(self, events: Iterable[MeetingEvent]) -> int:
        return sum(1 for e in events if self.apply(e))

    def _is_duplicate(self, event: MeetingEvent) -> bool:
        if event.sequence_number > self.last_sequence:
            return False
        if (event.sequence_number, event.event_id) in self._ids or event.event_id in {i for _, i in self._ids}:
            return True
        if event.sequence_number <= self.last_sequence - WINDOW:
            return True  # too old to compare ids; the sequence number says it has been applied
        raise InvalidEvent(f"sequence {event.sequence_number} is already used by another event")

    # ------------------------------------------------------------------ rules

    def _handle(self, e: MeetingEvent, mutate: bool) -> None:
        t, p = e.event_type, e.payload
        if self.meeting is None:
            if t != "meeting_created":
                raise InvalidTransition(f"{t} before the meeting was created")
            validate_for_publish(t, p)
            if not mutate:
                return
            self.meeting = Meeting(
                meeting_id=e.meeting_id, workspace_id=e.workspace_id, sprint_id=p.get("sprint_id"), meeting_type=p["meeting_type"], title=str(p["title"]),
                duration_limit_seconds=p.get("duration_limit_seconds"), control_mode=ControlMode(p.get("control_mode", "human")),
                created_by=str(p.get("created_by") or e.actor_id or "system"), status=MeetingStatus.CREATED,
            )
            return
        m = self.meeting
        if t == "meeting_created":
            raise InvalidTransition("the meeting already exists")
        if m.status in TERMINAL_STATUSES:
            raise InvalidTransition(f"the meeting is {m.status.value}; {t} is too late")
        started = m.started_at is not None
        if not started and t not in BEFORE_START:
            raise InvalidTransition(f"{t} before the meeting started")
        if self.paused and t not in WHILE_PAUSED:
            raise InvalidTransition(f"the meeting is paused; {t} has to wait")
        validate_for_publish(t, p)
        if e.actor_id and e.actor_id not in SYSTEM_ACTORS and t != "participant_joined":
            actor = self.participants.get(e.actor_id)
            if actor is None or actor.status == ParticipantStatus.LEFT:
                raise InvalidEvent(f"{e.actor_id} is not in the meeting")
        handler = getattr(self, f"_on_{t}", None)
        if handler is not None:
            handler(e, mutate)
        elif t in SPOKEN:
            self._on_spoken(e, mutate)

    def _joined(self, pid: str) -> Participant:
        person = self.participants.get(pid)
        if person is None or person.status == ParticipantStatus.LEFT:
            raise InvalidEvent(f"{pid} is not in the meeting")
        return person

    # -- the meeting itself
    def _on_meeting_started(self, e: MeetingEvent, mutate: bool) -> None:
        if self.meeting.started_at is not None:  # type: ignore[union-attr]
            raise InvalidTransition("the meeting already started")
        if mutate:
            self.meeting.started_at = e.timestamp  # type: ignore[union-attr]

    def _on_meeting_paused(self, e: MeetingEvent, mutate: bool) -> None:
        if self.paused:
            raise InvalidTransition("the meeting is already paused")
        if mutate:
            self.paused, self.paused_at = True, e.timestamp

    def _on_meeting_resumed(self, e: MeetingEvent, mutate: bool) -> None:
        if not self.paused:
            raise InvalidTransition("the meeting is not paused")
        if mutate:
            if self.paused_at is not None:
                self.paused_total += max(timedelta(0), e.timestamp - self.paused_at)
            self.paused, self.paused_at = False, None

    def _finish(self, e: MeetingEvent, status: MeetingStatus, mutate: bool) -> None:
        if status in (MeetingStatus.COMPLETED, MeetingStatus.TIMED_OUT) and self.meeting.started_at is None:  # type: ignore[union-attr]
            raise InvalidTransition("a meeting that never started cannot end")
        if mutate:
            m = self.meeting
            m.status, m.ended_at = status, e.timestamp  # type: ignore[union-attr]
            if self.paused and self.paused_at is not None:
                self.paused_total += max(timedelta(0), e.timestamp - self.paused_at)
            self.paused, self.paused_at, self.speaker = False, None, None
            for person in self.participants.values():
                if person.status != ParticipantStatus.LEFT:
                    person.status = ParticipantStatus.FINISHED

    def _on_meeting_ended(self, e: MeetingEvent, mutate: bool) -> None:
        self._finish(e, MeetingStatus.COMPLETED, mutate)

    def _on_meeting_timed_out(self, e: MeetingEvent, mutate: bool) -> None:
        self._finish(e, MeetingStatus.TIMED_OUT, mutate)

    def _on_meeting_cancelled(self, e: MeetingEvent, mutate: bool) -> None:
        self._finish(e, MeetingStatus.CANCELLED, mutate)

    def _on_human_takeover(self, e: MeetingEvent, mutate: bool) -> None:
        if mutate:
            self.meeting.control_mode = ControlMode.HUMAN  # type: ignore[union-attr]

    def _on_autopilot_enabled(self, e: MeetingEvent, mutate: bool) -> None:
        if mutate:
            self.meeting.control_mode = ControlMode.AUTOPILOT  # type: ignore[union-attr]

    def _on_topic_started(self, e: MeetingEvent, mutate: bool) -> None:
        if mutate:
            self.meeting.current_topic = str(e.payload["topic"])  # type: ignore[union-attr]

    def _on_topic_completed(self, e: MeetingEvent, mutate: bool) -> None:
        if mutate:
            topic = str(e.payload["topic"])
            self.topics_done.append(topic)
            if self.meeting.current_topic == topic:  # type: ignore[union-attr]
                self.meeting.current_topic = None  # type: ignore[union-attr]

    def _on_summary_generated(self, e: MeetingEvent, mutate: bool) -> None:
        if mutate:
            self.summary = str(e.payload["text"])

    # -- people
    def _on_participant_joined(self, e: MeetingEvent, mutate: bool) -> None:
        p = e.payload
        pid = check_id(str(p["participant_id"]), "participant_id")
        existing = self.participants.get(pid)
        if existing is not None and existing.status != ParticipantStatus.LEFT:
            raise InvalidEvent(f"{pid} is already in the meeting")
        if not mutate:
            return
        self.participants[pid] = Participant(
            participant_id=pid, display_name=str(p["display_name"]), participant_type=str(p["participant_type"]), agent_id=p.get("agent_id"), skill=p.get("skill"),
            temporary_meeting_role=p.get("role") or p.get("temporary_meeting_role"), parent_participant_id=p.get("parent_participant_id"), joined_at=e.timestamp,
        )

    def _on_participant_left(self, e: MeetingEvent, mutate: bool) -> None:
        person = self._joined(str(e.payload["participant_id"]))
        if mutate:
            person.status, person.left_at = ParticipantStatus.LEFT, e.timestamp
            if self.speaker == person.participant_id:
                self.speaker = None

    def _on_skill_selected(self, e: MeetingEvent, mutate: bool) -> None:
        person = self._joined(str(e.payload["participant_id"]))
        if mutate:
            person.skill = str(e.payload["skill"])  # chosen for this meeting; the next meeting may choose another

    def _on_role_assigned(self, e: MeetingEvent, mutate: bool) -> None:
        person = self._joined(str(e.payload["participant_id"]))
        if mutate:
            person.temporary_meeting_role = str(e.payload["role"])

    def _on_participant_blocked(self, e: MeetingEvent, mutate: bool) -> None:
        person = self._joined(str(e.payload["participant_id"]))
        if mutate:
            person.status, person.blocked_reason = ParticipantStatus.BLOCKED, e.payload.get("reason")

    def _on_participant_unblocked(self, e: MeetingEvent, mutate: bool) -> None:
        person = self._joined(str(e.payload["participant_id"]))
        if person.status != ParticipantStatus.BLOCKED:
            raise InvalidEvent(f"{person.participant_id} is not blocked")
        if mutate:
            person.status, person.blocked_reason = ParticipantStatus.LISTENING, None

    # -- talk
    def _on_spoken(self, e: MeetingEvent, mutate: bool) -> None:
        if not mutate or not e.actor_id or e.actor_id in SYSTEM_ACTORS:
            return
        self._speak(e.actor_id)

    def _speak(self, pid: str) -> None:
        previous = self.participants.get(self.speaker or "")
        if previous is not None and previous.participant_id != pid and previous.status == ParticipantStatus.SPEAKING:
            previous.status = ParticipantStatus.LISTENING
        person = self.participants.get(pid)
        if person is not None and person.status not in (ParticipantStatus.BLOCKED, ParticipantStatus.NEEDS_SME):
            person.status = ParticipantStatus.SPEAKING
            self.speaker = pid

    def _ask(self, e: MeetingEvent, mutate: bool) -> None:
        p = e.payload
        qid = check_id(str(p["question_id"]), "question_id")
        if qid in self.questions:
            raise InvalidEvent(f"question {qid} was already asked")
        target = str(p.get("target") or e.target_id or "business_sme")
        if target not in SME_TARGETS and target not in self.participants:
            raise InvalidEvent(f"the question is for {target}, who is not in the meeting")
        if not mutate:
            return
        self.questions[qid] = Question(
            question_id=qid, meeting_id=e.meeting_id, asked_by=e.actor_id, target=target, text=str(p["text"]), options=_as_list(p.get("options")),
            recommended=p.get("recommended"), asked_at=e.timestamp,
        )
        asker = self.participants.get(e.actor_id or "")
        if asker is not None and target in SME_TARGETS and asker.status not in (ParticipantStatus.LEFT, ParticipantStatus.BLOCKED):  # a blocker stays visible
            asker.status = ParticipantStatus.WAITING
            if self.speaker == asker.participant_id:
                self.speaker = None
        if target in SME_TARGETS:
            for person in self.participants.values():
                if person.participant_type == ParticipantType.BUSINESS_SME.value and person.status != ParticipantStatus.LEFT:
                    person.status = ParticipantStatus.NEEDS_SME

    _on_question = _ask
    _on_clarification_requested = _ask

    def _on_clarification_answered(self, e: MeetingEvent, mutate: bool) -> None:
        qid = str(e.payload["question_id"])
        question = self.questions.get(qid)
        if question is None:
            raise InvalidEvent(f"question {qid} was never asked")
        if question.status == QuestionStatus.ANSWERED:
            raise InvalidEvent(f"question {qid} is already answered")
        if not mutate:
            return
        question.status, question.answer, question.answered_by, question.answered_at = QuestionStatus.ANSWERED, str(e.payload["answer"]), e.actor_id, e.timestamp
        asker = self.participants.get(question.asked_by or "")
        if asker is not None and asker.status == ParticipantStatus.WAITING:
            asker.status = ParticipantStatus.LISTENING
        if not self._sme_pending():
            for person in self.participants.values():
                if person.status == ParticipantStatus.NEEDS_SME:
                    person.status = ParticipantStatus.LISTENING

    def _on_risk_raised(self, e: MeetingEvent, mutate: bool) -> None:
        rid = check_id(str(e.payload["risk_id"]), "risk_id")
        if rid in self.risks:
            raise InvalidEvent(f"risk {rid} was already raised")
        if mutate:
            self.risks[rid] = Risk(risk_id=rid, text=str(e.payload["text"]), severity=str(e.payload.get("severity", "medium")), raised_by=e.actor_id)

    def _on_dependency_identified(self, e: MeetingEvent, mutate: bool) -> None:
        did = check_id(str(e.payload["dependency_id"]), "dependency_id")
        if did in self.dependencies:
            raise InvalidEvent(f"dependency {did} was already identified")
        if mutate:
            self.dependencies[did] = Dependency(dependency_id=did, text=str(e.payload["text"]), from_id=e.payload.get("from"), to_id=e.payload.get("to"), identified_by=e.actor_id)

    # -- decisions and actions
    def _on_decision_proposed(self, e: MeetingEvent, mutate: bool) -> None:
        did = check_id(str(e.payload["decision_id"]), "decision_id")
        if did in self.decisions:
            raise InvalidEvent(f"decision {did} was already proposed")
        if mutate:
            self.decisions[did] = Decision(
                decision_id=did, meeting_id=e.meeting_id, title=str(e.payload["title"]), context=str(e.payload.get("context") or ""),
                alternatives=_as_list(e.payload.get("alternatives")), proposed_by=e.actor_id, timestamp=e.timestamp,
            )

    def _settle(self, e: MeetingEvent, status: DecisionStatus, mutate: bool) -> None:
        did = str(e.payload["decision_id"])
        decision = self.decisions.get(did)
        if decision is None:
            raise InvalidEvent(f"decision {did} was never proposed")
        if decision.status not in (DecisionStatus.PROPOSED, DecisionStatus.DEFERRED):
            raise InvalidEvent(f"decision {did} is already {decision.status.value}")
        if mutate:
            decision.status, decision.decided_by, decision.timestamp = status, e.payload.get("decided_by") or e.actor_id, e.timestamp
            decision.selected_option = e.payload.get("selected_option") if status == DecisionStatus.ACCEPTED else None
            decision.reason = str(e.payload.get("reason") or "")

    def _on_decision_accepted(self, e: MeetingEvent, mutate: bool) -> None:
        self._settle(e, DecisionStatus.ACCEPTED, mutate)

    def _on_decision_rejected(self, e: MeetingEvent, mutate: bool) -> None:
        self._settle(e, DecisionStatus.REJECTED, mutate)

    def _on_decision_deferred(self, e: MeetingEvent, mutate: bool) -> None:
        self._settle(e, DecisionStatus.DEFERRED, mutate)

    def _on_action_item_created(self, e: MeetingEvent, mutate: bool) -> None:
        aid = check_id(str(e.payload["action_item_id"]), "action_item_id")
        if aid in self.actions:
            raise InvalidEvent(f"action item {aid} already exists")
        if mutate:
            self.actions[aid] = ActionItem(
                action_item_id=aid, meeting_id=e.meeting_id, owner_id=str(e.payload["owner_id"]), description=str(e.payload["description"]),
                due_reference=e.payload.get("due_reference"), created_at=e.timestamp,
            )

    def _on_action_item_updated(self, e: MeetingEvent, mutate: bool) -> None:
        item = self.actions.get(str(e.payload["action_item_id"]))
        if item is None:
            raise InvalidEvent(f"action item {e.payload['action_item_id']} does not exist")
        try:
            status = ActionStatus(str(e.payload["status"]))
        except ValueError:
            raise InvalidEvent(f"unknown action status {e.payload['status']!r}") from None
        if mutate:
            item.status = status
            item.completed_at = e.timestamp if status == ActionStatus.DONE else None
            if e.payload.get("owner_id"):
                item.owner_id = str(e.payload["owner_id"])

    # -- documents and approvals
    def _on_document_created(self, e: MeetingEvent, mutate: bool) -> None:
        if mutate:
            self.documents[str(e.payload["path"])] = e.actor_id or "system"

    def _on_document_review_started(self, e: MeetingEvent, mutate: bool) -> None:
        if mutate:
            path = str(e.payload["path"])
            self.reviews[path] = DocumentReview(document_path=path, meeting_id=e.meeting_id, reviewer_id=e.payload.get("reviewer_id") or e.actor_id)

    def _review(self, e: MeetingEvent, status: ReviewStatus, mutate: bool) -> None:
        review = self.reviews.get(str(e.payload["path"]))
        if review is None or review.status != ReviewStatus.IN_REVIEW:
            raise InvalidEvent(f"{e.payload['path']} is not under review")
        if mutate:
            review.status, review.reviewed_at = status, e.timestamp
            review.comments.extend(_as_list(e.payload.get("comments")))

    def _on_document_approved(self, e: MeetingEvent, mutate: bool) -> None:
        self._review(e, ReviewStatus.APPROVED, mutate)

    def _on_document_changes_requested(self, e: MeetingEvent, mutate: bool) -> None:
        self._review(e, ReviewStatus.CHANGES_REQUESTED, mutate)

    def _on_sme_approval_requested(self, e: MeetingEvent, mutate: bool) -> None:
        rid = check_id(str(e.payload["request_id"]), "request_id")
        if rid in self.approvals:
            raise InvalidEvent(f"approval {rid} was already requested")
        if mutate:
            self.approvals[rid] = ApprovalRequest(request_id=rid, subject=str(e.payload["subject"]), requested_by=e.actor_id, extra={k: v for k, v in e.payload.items() if k not in ("request_id", "subject")})

    def _close_approval(self, e: MeetingEvent, approved: bool, mutate: bool) -> None:
        req = self.approvals.get(str(e.payload["request_id"]))
        if req is None or not req.open:
            raise InvalidEvent(f"approval {e.payload['request_id']} is not waiting")
        if mutate:
            req.open, req.approved, req.comment = False, approved, str(e.payload.get("comment") or "")

    def _on_sme_approved(self, e: MeetingEvent, mutate: bool) -> None:
        self._close_approval(e, True, mutate)

    def _on_sme_rejected(self, e: MeetingEvent, mutate: bool) -> None:
        self._close_approval(e, False, mutate)

    # ------------------------------------------------------------------ derived

    def _sme_pending(self) -> bool:
        return any(q.status == QuestionStatus.OPEN and (q.target in SME_TARGETS or self._is_sme(q.target)) for q in self.questions.values())

    def _is_sme(self, pid: str) -> bool:
        person = self.participants.get(pid)
        return person is not None and person.participant_type == ParticipantType.BUSINESS_SME.value

    def _recompute(self) -> None:
        m = self.meeting
        if m is None or m.status in TERMINAL_STATUSES:
            return
        if m.started_at is None:
            m.status = MeetingStatus.WAITING_FOR_PARTICIPANTS if any(p.status != ParticipantStatus.LEFT for p in self.participants.values()) else MeetingStatus.CREATED
        elif self.paused:
            m.status = MeetingStatus.PAUSED
        elif any(a.open for a in self.approvals.values()):
            m.status = MeetingStatus.AWAITING_APPROVAL
        elif self._sme_pending():
            m.status = MeetingStatus.WAITING_FOR_SME
        elif any(r.status == ReviewStatus.IN_REVIEW for r in self.reviews.values()):
            m.status = MeetingStatus.REVIEWING
        else:
            m.status = MeetingStatus.ACTIVE

    # ------------------------------------------------------------------ reading

    @property
    def status(self) -> Optional[MeetingStatus]:
        return self.meeting.status if self.meeting else None

    def open_questions(self) -> list[Question]:
        return [q for q in self.questions.values() if q.status == QuestionStatus.OPEN]

    def elapsed_at(self, now: datetime) -> float:
        """Seconds the meeting has been running at `now`, not counting time spent paused."""
        m = self.meeting
        if m is None or m.started_at is None:
            return 0.0
        end = m.ended_at or now
        paused = self.paused_total + (max(timedelta(0), end - self.paused_at) if self.paused and self.paused_at else timedelta(0))
        return max(0.0, (end - m.started_at - paused).total_seconds())

    def remaining_at(self, now: datetime) -> Optional[float]:
        limit = self.meeting.duration_limit_seconds if self.meeting else None
        return None if not limit else max(0.0, limit - self.elapsed_at(now))
