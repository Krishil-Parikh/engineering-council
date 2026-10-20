"""The versioned event contract between whoever runs a meeting and everything that shows or stores it.

A meeting is its events: append-only, one monotonic sequence number per meeting (never timestamps for order), each with a unique id so applying
one twice changes nothing. Whatever is shown (the live screen, the replay, the .txt transcript) is a projection of this stream."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from standup.enums import ControlMode, MeetingType
from standup.errors import InvalidEvent

SCHEMA_VERSION = 1
NAMESPACE = "standup"  # how the event travels on a shared stream: "standup.<event_type>"


class EventType(str, Enum):
    MEETING_CREATED = "meeting_created"
    MEETING_STARTED = "meeting_started"
    MEETING_PAUSED = "meeting_paused"
    MEETING_RESUMED = "meeting_resumed"
    MEETING_ENDED = "meeting_ended"
    MEETING_TIMED_OUT = "meeting_timed_out"
    MEETING_CANCELLED = "meeting_cancelled"
    PARTICIPANT_JOINED = "participant_joined"
    PARTICIPANT_LEFT = "participant_left"
    SKILL_SELECTED = "skill_selected"
    ROLE_ASSIGNED = "role_assigned"
    TOPIC_STARTED = "topic_started"
    TOPIC_COMPLETED = "topic_completed"
    STATEMENT = "statement"
    BRAINSTORM = "brainstorm"
    PROPOSAL = "proposal"
    CHALLENGE = "challenge"
    COUNTERARGUMENT = "counterargument"
    QUESTION = "question"
    CLARIFICATION_REQUESTED = "clarification_requested"
    CLARIFICATION_ANSWERED = "clarification_answered"
    RISK_RAISED = "risk_raised"
    DEPENDENCY_IDENTIFIED = "dependency_identified"
    FACILITATOR_INTERVENTION = "facilitator_intervention"
    HUMAN_TAKEOVER = "human_takeover"
    AUTOPILOT_ENABLED = "autopilot_enabled"
    DECISION_PROPOSED = "decision_proposed"
    DECISION_ACCEPTED = "decision_accepted"
    DECISION_REJECTED = "decision_rejected"
    DECISION_DEFERRED = "decision_deferred"
    ACTION_ITEM_CREATED = "action_item_created"
    ACTION_ITEM_UPDATED = "action_item_updated"
    DOCUMENT_CREATED = "document_created"
    DOCUMENT_REVIEW_STARTED = "document_review_started"
    DOCUMENT_APPROVED = "document_approved"
    DOCUMENT_CHANGES_REQUESTED = "document_changes_requested"
    SME_APPROVAL_REQUESTED = "sme_approval_requested"
    SME_APPROVED = "sme_approved"
    SME_REJECTED = "sme_rejected"
    PARTICIPANT_BLOCKED = "participant_blocked"
    PARTICIPANT_UNBLOCKED = "participant_unblocked"
    SUMMARY_GENERATED = "summary_generated"


KNOWN_TYPES = frozenset(t.value for t in EventType)

# what a payload must carry, by event type. Anything else in a payload is allowed (and kept): a newer producer may add fields without breaking an older reader.
REQUIRED: dict[str, tuple[str, ...]] = {
    "meeting_created": ("title", "meeting_type"),
    "participant_joined": ("participant_id", "display_name", "participant_type"),
    "participant_left": ("participant_id",),
    "skill_selected": ("participant_id", "skill"),
    "role_assigned": ("participant_id", "role"),
    "topic_started": ("topic",),
    "topic_completed": ("topic",),
    "statement": ("text",),
    "brainstorm": ("text",),
    "proposal": ("text",),
    "challenge": ("text",),
    "counterargument": ("text",),
    "question": ("question_id", "text"),
    "clarification_requested": ("question_id", "text"),
    "clarification_answered": ("question_id", "answer"),
    "risk_raised": ("risk_id", "text"),
    "dependency_identified": ("dependency_id", "text"),
    "facilitator_intervention": ("text",),
    "decision_proposed": ("decision_id", "title"),
    "decision_accepted": ("decision_id",),
    "decision_rejected": ("decision_id",),
    "decision_deferred": ("decision_id",),
    "action_item_created": ("action_item_id", "owner_id", "description"),
    "action_item_updated": ("action_item_id", "status"),
    "document_created": ("path",),
    "document_review_started": ("path",),
    "document_approved": ("path",),
    "document_changes_requested": ("path",),
    "sme_approval_requested": ("request_id", "subject"),
    "sme_approved": ("request_id",),
    "sme_rejected": ("request_id",),
    "participant_blocked": ("participant_id",),
    "participant_unblocked": ("participant_id",),
    "summary_generated": ("text",),
}

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")  # ids become folder names: nothing that can climb out of a directory

_SECRETS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|passwd|password)\b(\s*[:=]\s*)['\"]?[^\s'\"]{8,}"),
]


def redact(text: str) -> str:
    """Secret-looking text never goes into a meeting record."""
    for pattern in _SECRETS[:-1]:
        text = pattern.sub("[redacted]", text)
    return _SECRETS[-1].sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)


SECRET_KEY = re.compile(r"(?i)(api[_-]?key|secret|token|passwd|password|credential|private[_-]?key)")


def redact_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: ("[redacted]" if isinstance(v, str) and v and SECRET_KEY.search(str(k)) else redact_payload(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_payload(v) for v in value]
    return value


def check_id(value: str, what: str = "id") -> str:
    if not isinstance(value, str) or not ID_PATTERN.match(value):
        raise InvalidEvent(f"{what} {value!r} is not a safe identifier (letters, digits, '.', '_', '-'; at most 80)")
    return value


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MeetingEvent(BaseModel):
    """One thing that happened in a meeting. Immutable once made."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: str
    event_type: str  # a plain string so a stream written by a newer version can still be read; `validate_for_publish` rejects the unknown
    meeting_id: str
    workspace_id: str
    sequence_number: int = Field(ge=1)
    timestamp: datetime
    elapsed_seconds: float = Field(ge=0)
    actor_id: Optional[str] = None
    target_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION
    correlation_id: str = ""
    causation_id: Optional[str] = None
    idempotency_key: Optional[str] = None

    @field_validator("timestamp")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @property
    def kind(self) -> str:
        """The name it has on a shared stream."""
        return f"{NAMESPACE}.{self.event_type}"

    def wire(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def validate_for_publish(event_type: str, payload: dict[str, Any]) -> None:
    """What a producer may send: a known type with its required fields. (Replay is more forgiving: it tolerates types it does not know.)"""
    if event_type not in KNOWN_TYPES:
        raise InvalidEvent(f"unknown event type {event_type!r}")
    missing = [k for k in REQUIRED.get(event_type, ()) if payload.get(k) in (None, "")]
    if missing:
        raise InvalidEvent(f"{event_type} needs {', '.join(missing)}")
    if event_type == "meeting_created":
        if payload["meeting_type"] not in {t.value for t in MeetingType}:
            raise InvalidEvent(f"unknown meeting_type {payload['meeting_type']!r}")
        if payload.get("control_mode", "human") not in {m.value for m in ControlMode}:
            raise InvalidEvent(f"unknown control_mode {payload.get('control_mode')!r}")
