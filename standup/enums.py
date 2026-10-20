from __future__ import annotations

from enum import Enum


class _Str(str, Enum):
    def __str__(self) -> str:
        return self.value


class MeetingType(_Str):
    DISCOVERY = "discovery"
    PRD_REVIEW = "prd_review"
    ARCHITECTURE_REVIEW = "architecture_review"
    DESIGN_REVIEW = "design_review"
    SPRINT_PLANNING = "sprint_planning"
    DAILY_STANDUP = "daily_standup"
    SPRINT_REVIEW = "sprint_review"
    SPRINT_RETROSPECTIVE = "sprint_retrospective"
    SME_CHECKPOINT = "sme_checkpoint"
    CUSTOM = "custom"


class MeetingStatus(_Str):
    CREATED = "created"
    WAITING_FOR_PARTICIPANTS = "waiting_for_participants"
    ACTIVE = "active"
    PAUSED = "paused"
    WAITING_FOR_SME = "waiting_for_sme"
    REVIEWING = "reviewing"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


TERMINAL_STATUSES = frozenset({MeetingStatus.COMPLETED, MeetingStatus.CANCELLED, MeetingStatus.TIMED_OUT})


class ControlMode(_Str):
    HUMAN = "human"
    AUTOPILOT = "autopilot"


class ParticipantType(_Str):
    BUSINESS_SME = "business_sme"
    SCRUM_MASTER = "scrum_master"
    DEVELOPER = "developer"
    REVIEWER = "reviewer"
    OBSERVER = "observer"


class ParticipantStatus(_Str):
    JOINED = "joined"
    THINKING = "thinking"
    SPEAKING = "speaking"
    LISTENING = "listening"
    WAITING = "waiting"
    BLOCKED = "blocked"
    NEEDS_SME = "needs_sme"
    REVIEWING = "reviewing"
    FINISHED = "finished"
    LEFT = "left"


class DecisionStatus(_Str):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class QuestionStatus(_Str):
    OPEN = "open"
    ANSWERED = "answered"


class ActionStatus(_Str):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    DROPPED = "dropped"


class ReviewStatus(_Str):
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
