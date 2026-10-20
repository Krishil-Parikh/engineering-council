"""The human-readable transcript. It is a projection of the events, never the other way round, and it is deterministic: the same events always give the same text."""

from __future__ import annotations

from typing import Optional

from standup.events import MeetingEvent
from standup.state import MeetingState

LABELS = {
    "statement": "Statement", "brainstorm": "Brainstorm", "proposal": "Proposal", "challenge": "Challenge", "counterargument": "Counterargument",
    "question": "Question", "clarification_requested": "Clarification requested", "clarification_answered": "Answer", "facilitator_intervention": "Facilitator",
}
TEXT_FIELD = {"clarification_answered": "answer"}


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def speaker(state: MeetingState, actor_id: Optional[str]) -> str:
    person = state.participants.get(actor_id or "")
    if person is None:
        return "Meeting"
    label = person.display_name
    if person.skill:
        label += f" [{person.skill}]"
    if person.temporary_meeting_role:
        label += f" ({person.temporary_meeting_role})"
    return label


def name(state: MeetingState, pid: Optional[str]) -> str:
    person = state.participants.get(pid or "")
    return person.display_name if person else (pid or "someone")


def _comments(value: object) -> str:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return str(value) if value else ""


def _describe(t: str, p: dict, state: MeetingState) -> Optional[str]:
    """The one-line description of an event that has no speech of its own."""
    simple = {
        "meeting_started": "Meeting started", "meeting_paused": "Meeting paused", "meeting_resumed": "Meeting resumed", "meeting_ended": "Meeting ended",
        "meeting_timed_out": "Meeting timed out", "meeting_cancelled": "Meeting cancelled", "human_takeover": "The Business SME took control",
        "autopilot_enabled": "Autopilot Business SME enabled",
    }
    if t in simple:
        return simple[t]
    if t == "meeting_created":
        return f"Meeting created: {p.get('title')} ({p.get('meeting_type')}, {p.get('control_mode', 'human')} control)"
    if t == "participant_joined":
        return f"{p.get('display_name')} joined as {p.get('participant_type')}" + (f" [{p['skill']}]" if p.get("skill") else "")
    if t == "participant_left":
        return f"{name(state, p.get('participant_id'))} left"
    if t == "skill_selected":
        return f"{name(state, p.get('participant_id'))} took the skill {p.get('skill')}"
    if t == "role_assigned":
        return f"{name(state, p.get('participant_id'))} is now {p.get('role')}"
    if t == "topic_started":
        return f"Topic: {p.get('topic')}"
    if t == "topic_completed":
        return f"Topic done: {p.get('topic')}"
    if t == "risk_raised":
        return f"Risk ({p.get('severity', 'medium')}): {p.get('text')}"
    if t == "dependency_identified":
        return f"Dependency: {p.get('text')}"
    if t == "decision_proposed":
        options = _comments(p.get("alternatives"))
        return f"Decision proposed: {p.get('title')}" + (f" (options: {options})" if options else "")
    if t in ("decision_accepted", "decision_rejected", "decision_deferred"):
        title = state.decisions[p["decision_id"]].title if p.get("decision_id") in state.decisions else p.get("decision_id")
        verb = t.split("_")[1].capitalize()
        extra = f" -> {p['selected_option']}" if t == "decision_accepted" and p.get("selected_option") else (f" ({p['reason']})" if p.get("reason") else "")
        return f"Decision {verb.lower()}: {title}{extra}"
    if t == "action_item_created":
        return f"Action item for {name(state, p.get('owner_id'))}: {p.get('description')}"
    if t == "action_item_updated":
        return f"Action item {p.get('action_item_id')} is now {p.get('status')}"
    if t == "document_created":
        return f"Document created: {p.get('path')}"
    if t == "document_review_started":
        return f"Review of {p.get('path')} started"
    if t == "document_approved":
        return f"Document approved: {p.get('path')}"
    if t == "document_changes_requested":
        comments = _comments(p.get("comments"))
        return f"Changes requested on {p.get('path')}" + (f": {comments}" if comments else "")
    if t == "sme_approval_requested":
        return f"Approval requested from the Business SME: {p.get('subject')}"
    if t in ("sme_approved", "sme_rejected"):
        return f"Business SME {'approved' if t == 'sme_approved' else 'rejected'} {p.get('request_id')}" + (f": {p['comment']}" if p.get("comment") else "")
    if t == "participant_blocked":
        return f"{name(state, p.get('participant_id'))} is blocked" + (f": {p['reason']}" if p.get("reason") else "")
    if t == "participant_unblocked":
        return f"{name(state, p.get('participant_id'))} is unblocked"
    if t == "summary_generated":
        return f"Summary: {p.get('text')}"
    return None


def render_event(event: MeetingEvent, state: MeetingState) -> Optional[str]:
    """The text for one event, or None for an event this version does not know. `state` is the meeting after the event was applied."""
    t, p = event.event_type, event.payload
    prefix = f"{event.timestamp.strftime('%H:%M:%S')}Z [{format_elapsed(event.elapsed_seconds)}]"
    who = speaker(state, event.actor_id)
    if t in LABELS:
        label = LABELS[t]
        if t == "challenge" and event.target_id:
            label += f" to {name(state, event.target_id)}"
        return f"{prefix} {who} — {label}:\n{p.get(TEXT_FIELD.get(t, 'text'), '')}"
    text = _describe(t, p, state)
    if text is None:
        return None
    return f"{prefix} {who} — {text}" if event.actor_id and event.actor_id in state.participants else f"{prefix} {text}"


def render_transcript(events: list[MeetingEvent]) -> str:
    """The whole transcript, from the events alone (what the writer would have appended one line at a time)."""
    state = MeetingState()
    lines = []
    for event in events:
        if state.apply(event):
            line = render_event(event, state)
            if line is not None:
                lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


describe = _describe  # the one-line description of an event, for other renderers
