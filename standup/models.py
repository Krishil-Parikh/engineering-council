"""The things a meeting is made of. Plain data: no behaviour, no framework."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from standup.enums import (
    ActionStatus,
    ControlMode,
    DecisionStatus,
    MeetingStatus,
    MeetingType,
    ParticipantStatus,
    ParticipantType,
    QuestionStatus,
    ReviewStatus,
)


class Meeting(BaseModel):
    meeting_id: str
    workspace_id: str
    sprint_id: Optional[str] = None
    meeting_type: str = MeetingType.CUSTOM.value
    title: str = ""
    status: MeetingStatus = MeetingStatus.CREATED
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_limit_seconds: Optional[float] = None
    control_mode: ControlMode = ControlMode.HUMAN
    current_topic: Optional[str] = None
    created_by: str = "system"
    version: int = 0  # the sequence number of the last event applied


class Participant(BaseModel):
    participant_id: str
    display_name: str
    participant_type: str = ParticipantType.DEVELOPER.value
    agent_id: Optional[str] = None
    skill: Optional[str] = None  # a runtime choice for this meeting, not a permanent kind of agent
    temporary_meeting_role: Optional[str] = None
    parent_participant_id: Optional[str] = None
    joined_at: Optional[datetime] = None
    left_at: Optional[datetime] = None
    status: ParticipantStatus = ParticipantStatus.JOINED
    blocked_reason: Optional[str] = None


class Decision(BaseModel):
    decision_id: str
    meeting_id: str
    title: str
    context: str = ""
    alternatives: list[str] = Field(default_factory=list)
    selected_option: Optional[str] = None
    status: DecisionStatus = DecisionStatus.PROPOSED
    decided_by: Optional[str] = None
    proposed_by: Optional[str] = None
    reason: str = ""
    timestamp: Optional[datetime] = None


class Question(BaseModel):
    question_id: str
    meeting_id: str
    asked_by: Optional[str] = None
    target: str = "business_sme"
    text: str
    status: QuestionStatus = QuestionStatus.OPEN
    answer: Optional[str] = None
    answered_by: Optional[str] = None
    options: list[str] = Field(default_factory=list)
    recommended: Optional[str] = None
    asked_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None


class ActionItem(BaseModel):
    action_item_id: str
    meeting_id: str
    owner_id: str
    description: str
    status: ActionStatus = ActionStatus.OPEN
    due_reference: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class DocumentReview(BaseModel):
    document_path: str
    meeting_id: str
    reviewer_id: Optional[str] = None
    status: ReviewStatus = ReviewStatus.IN_REVIEW
    comments: list[str] = Field(default_factory=list)
    reviewed_at: Optional[datetime] = None


class Risk(BaseModel):
    risk_id: str
    text: str
    severity: str = "medium"
    raised_by: Optional[str] = None


class Dependency(BaseModel):
    dependency_id: str
    text: str
    from_id: Optional[str] = None
    to_id: Optional[str] = None
    identified_by: Optional[str] = None


class ApprovalRequest(BaseModel):
    request_id: str
    subject: str
    requested_by: Optional[str] = None
    open: bool = True
    approved: Optional[bool] = None
    comment: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
