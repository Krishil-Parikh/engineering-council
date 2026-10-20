"""What a screen needs, computed from a meeting and nothing else: an Agent Standup style team call (who is speaking, who needs the Business SME, what was decided).

Pure functions over `MeetingState`. A different screen, or a different visual adapter later, reads the same view model; nothing here knows about HTTP or React."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from standup.enums import ParticipantStatus
from standup.events import MeetingEvent
from standup.models import ActionItem, Decision, DocumentReview, Participant, Question
from standup.state import MeetingState
from standup.transcript import format_elapsed

URGENCY = {  # the order people are listed in: whoever needs attention first
    ParticipantStatus.NEEDS_SME: 0, ParticipantStatus.BLOCKED: 1, ParticipantStatus.SPEAKING: 2, ParticipantStatus.THINKING: 3, ParticipantStatus.WAITING: 4,
    ParticipantStatus.REVIEWING: 5, ParticipantStatus.LISTENING: 6, ParticipantStatus.JOINED: 7, ParticipantStatus.FINISHED: 8, ParticipantStatus.LEFT: 9,
}
BADGES = {
    ParticipantStatus.NEEDS_SME: "needs you", ParticipantStatus.BLOCKED: "blocked", ParticipantStatus.SPEAKING: "speaking", ParticipantStatus.THINKING: "thinking",
    ParticipantStatus.WAITING: "waiting for an answer", ParticipantStatus.REVIEWING: "reviewing", ParticipantStatus.LISTENING: "listening",
}
TONES = {  # how the timeline colours an event
    "challenge": "warn", "counterargument": "warn", "risk_raised": "warn", "participant_blocked": "warn", "meeting_timed_out": "danger", "sme_rejected": "danger",
    "decision_rejected": "danger", "document_changes_requested": "danger", "decision_accepted": "success", "sme_approved": "success", "document_approved": "success",
    "clarification_requested": "ask", "question": "ask", "sme_approval_requested": "ask", "facilitator_intervention": "info", "human_takeover": "info", "autopilot_enabled": "info",
}


class PresentationEvent(BaseModel):
    sequence: int
    event_type: str
    kind: str  # the shared-stream name, "standup.<type>"
    elapsed: str
    actor_id: Optional[str] = None
    actor_name: str = "Meeting"
    text: str = ""
    tone: str = "plain"


class ParticipantView(BaseModel):
    participant_id: str
    display_name: str
    participant_type: str
    skill: Optional[str] = None
    role: Optional[str] = None
    status: str
    badge: str = ""
    speaking: bool = False
    needs_sme: bool = False


class StandupViewState(BaseModel):
    meeting_id: str
    title: str
    meeting_type: str
    status: str
    control_mode: str
    started_at: Optional[datetime] = None
    elapsed_seconds: float = 0
    elapsed: str = "00:00:00"
    remaining_seconds: Optional[float] = None
    paused: bool = False
    current_topic: Optional[str] = None
    active_speaker: Optional[str] = None
    pending_question: Optional[Question] = None
    open_questions: list[Question] = Field(default_factory=list)
    participants: list[ParticipantView] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    reviews: list[DocumentReview] = Field(default_factory=list)
    risks: list[dict[str, Any]] = Field(default_factory=list)
    dependencies: list[dict[str, Any]] = Field(default_factory=list)
    approvals_open: list[dict[str, Any]] = Field(default_factory=list)
    summary: str = ""
    last_sequence: int = 0
    recent: list[PresentationEvent] = Field(default_factory=list)


def _participant(p: Participant, speaker: Optional[str]) -> ParticipantView:
    return ParticipantView(
        participant_id=p.participant_id, display_name=p.display_name, participant_type=p.participant_type, skill=p.skill, role=p.temporary_meeting_role, status=p.status.value,
        badge=BADGES.get(p.status, ""), speaking=p.participant_id == speaker and p.status == ParticipantStatus.SPEAKING, needs_sme=p.status == ParticipantStatus.NEEDS_SME,
    )


def translate(event: MeetingEvent, state: MeetingState) -> PresentationEvent:
    """One event as a timeline entry. Pure: the same event and state always give the same entry; an unknown event becomes a quiet note."""
    from standup.transcript import describe as _describe, name

    t, p = event.event_type, event.payload
    spoken = p.get("text") or p.get("answer") or p.get("description") or ""
    text = spoken if t in {"statement", "brainstorm", "proposal", "challenge", "counterargument", "question", "clarification_requested", "clarification_answered", "facilitator_intervention"} else (_describe(t, p, state) or f"({t})")
    if t == "challenge" and event.target_id:
        text = f"to {name(state, event.target_id)}: {text}"
    return PresentationEvent(
        sequence=event.sequence_number, event_type=t, kind=event.kind, elapsed=format_elapsed(event.elapsed_seconds), actor_id=event.actor_id,
        actor_name=name(state, event.actor_id) if event.actor_id in state.participants else "Meeting", text=str(text), tone=TONES.get(t, "plain"),
    )


def build_view(state: MeetingState, now: datetime, recent: int = 40) -> StandupViewState:
    m = state.meeting
    if m is None:
        raise ValueError("a meeting that was never created has no view")
    people = sorted(state.participants.values(), key=lambda p: (URGENCY.get(p.status, 9), p.display_name))
    pending = next(iter(state.open_questions()), None)
    elapsed = state.elapsed_at(now)
    return StandupViewState(
        meeting_id=m.meeting_id, title=m.title, meeting_type=m.meeting_type, status=m.status.value, control_mode=m.control_mode.value, started_at=m.started_at,
        elapsed_seconds=elapsed, elapsed=format_elapsed(elapsed), remaining_seconds=state.remaining_at(now), paused=state.paused, current_topic=m.current_topic,
        active_speaker=state.speaker, pending_question=pending, open_questions=state.open_questions(), participants=[_participant(p, state.speaker) for p in people],
        decisions=list(state.decisions.values()), action_items=list(state.actions.values()), reviews=list(state.reviews.values()),
        risks=[r.model_dump(mode="json") for r in state.risks.values()], dependencies=[d.model_dump(mode="json") for d in state.dependencies.values()],
        approvals_open=[a.model_dump(mode="json") for a in state.approvals.values() if a.open], summary=state.summary, last_sequence=state.last_sequence,
        recent=[translate(e, state) for e in list(state.recent)[-recent:]],
    )
