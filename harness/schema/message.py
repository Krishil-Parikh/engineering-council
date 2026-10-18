"""Session message model (opencode: packages/schema/src/session-message.ts).

A session is an ordered list of these. Assistant messages hold typed content parts (text, reasoning, tool calls with a
state machine); compaction messages record a checkpoint; `system` messages carry frozen instruction updates."""

from __future__ import annotations

import os
import time
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- ids


def ascending() -> str:
    """Sortable unique suffix: millisecond timestamp (12 hex digits) then random bytes."""
    return f"{int(time.time() * 1000):012x}{os.urandom(7).hex()}"


def new_message_id() -> str:
    return "msg_" + ascending()


def now_ms() -> int:
    return int(time.time() * 1000)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --------------------------------------------------------------------------- small shared shapes


class ModelRef(_Model):
    provider_id: str
    id: str
    variant: Optional[str] = None


class TokenUsage(_Model):
    input: float = 0
    output: float = 0
    reasoning: float = 0
    cache_read: float = 0
    cache_write: float = 0

    def total(self) -> float:
        return self.input + self.output + self.reasoning + self.cache_read + self.cache_write


class SessionError(_Model):
    type: str
    message: str
    status: Optional[int] = None
    response: Optional[dict[str, str]] = None


class TextContent(_Model):
    type: Literal["text"] = "text"
    text: str


class FileContent(_Model):
    type: Literal["file"] = "file"
    uri: str
    mime: str
    name: Optional[str] = None


ToolContent = Annotated[Union[TextContent, FileContent], Field(discriminator="type")]

FinishReason = Literal["stop", "length", "tool-calls", "content-filter", "error", "unknown"]


class Time(_Model):
    created: int = Field(default_factory=now_ms)


class LocationRef(_Model):
    directory: str
    workspace_id: Optional[str] = None


# --------------------------------------------------------------------------- user-side messages


class PromptMention(_Model):
    start: float
    end: float
    text: str


class FileAttachment(_Model):
    data: str  # base64
    mime: str
    source: dict[str, Any]  # {"type": "inline"} or {"type": "uri", "uri": ...}
    name: Optional[str] = None
    description: Optional[str] = None
    mention: Optional[PromptMention] = None


class AgentAttachment(_Model):
    name: str
    mention: Optional[PromptMention] = None


class SkillAttachment(_Model):
    id: str
    name: str
    text: Optional[str] = None
    mention: Optional[PromptMention] = None


class _Base(_Model):
    id: str = Field(default_factory=new_message_id)
    metadata: Optional[dict[str, Any]] = None
    time: Time = Field(default_factory=Time)


class AgentSelected(_Base):
    type: Literal["agent-switched"] = "agent-switched"
    agent: str
    previous: Optional[str] = None


class ModelSelected(_Base):
    type: Literal["model-switched"] = "model-switched"
    model: ModelRef
    previous: Optional[ModelRef] = None


class LocationSwitched(_Base):
    type: Literal["location-switched"] = "location-switched"
    location: LocationRef
    previous: Optional[LocationRef] = None


class User(_Base):
    type: Literal["user"] = "user"
    text: str
    files: Optional[list[FileAttachment]] = None
    agents: Optional[list[AgentAttachment]] = None
    skills: Optional[list[SkillAttachment]] = None


class Synthetic(_Base):
    type: Literal["synthetic"] = "synthetic"
    text: str
    description: Optional[str] = None


class System(_Base):
    """A frozen instruction update: the model-facing text is fixed when it is emitted."""

    type: Literal["system"] = "system"
    text: str
    description: Optional[str] = None


class Skill(_Base):
    type: Literal["skill"] = "skill"
    skill: str
    name: str
    text: str


class ShellTime(_Model):
    created: int = Field(default_factory=now_ms)
    completed: Optional[int] = None


class ShellMessage(_Base):
    type: Literal["shell"] = "shell"
    shell_id: str
    command: str
    status: str = "running"
    exit: Optional[float] = None
    output: Optional[dict[str, Any]] = None  # {"output": str, "truncated": bool}
    time: ShellTime = Field(default_factory=ShellTime)  # type: ignore[assignment]


# --------------------------------------------------------------------------- assistant message


class ToolStateStreaming(_Model):
    status: Literal["streaming"] = "streaming"
    input: str = ""


class ToolStateRunning(_Model):
    status: Literal["running"] = "running"
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolStateCompleted(_Model):
    status: Literal["completed"] = "completed"
    input: dict[str, Any] = Field(default_factory=dict)
    content: list[ToolContent]
    metadata: Optional[dict[str, Any]] = None


class ToolStateError(_Model):
    status: Literal["error"] = "error"
    input: dict[str, Any] = Field(default_factory=dict)
    error: SessionError
    content: Optional[list[ToolContent]] = None
    metadata: Optional[dict[str, Any]] = None


ToolState = Annotated[
    Union[ToolStateStreaming, ToolStateRunning, ToolStateCompleted, ToolStateError], Field(discriminator="status")
]


class ToolTime(_Model):
    created: int = Field(default_factory=now_ms)
    ran: Optional[int] = None
    completed: Optional[int] = None


class AssistantTool(_Model):
    type: Literal["tool"] = "tool"
    id: str
    name: str
    executed: Optional[bool] = None
    provider_state: Optional[dict[str, Any]] = None
    provider_result_state: Optional[dict[str, Any]] = None
    state: ToolState
    time: ToolTime = Field(default_factory=ToolTime)


class AssistantText(_Model):
    type: Literal["text"] = "text"
    text: str = ""
    state: Optional[dict[str, Any]] = None  # provider state such as Gemini thought signatures


class ReasoningTime(_Model):
    created: int = Field(default_factory=now_ms)
    completed: Optional[int] = None


class AssistantReasoning(_Model):
    type: Literal["reasoning"] = "reasoning"
    text: str = ""
    state: Optional[dict[str, Any]] = None
    time: Optional[ReasoningTime] = None


AssistantContent = Annotated[Union[AssistantText, AssistantReasoning, AssistantTool], Field(discriminator="type")]


class AssistantRetry(_Model):
    attempt: int
    at: int
    error: SessionError


class SnapshotRefs(_Model):
    start: Optional[str] = None
    end: Optional[str] = None
    files: Optional[list[str]] = None


class AssistantTime(_Model):
    created: int = Field(default_factory=now_ms)
    streamed: Optional[int] = None
    completed: Optional[int] = None


class Assistant(_Base):
    type: Literal["assistant"] = "assistant"
    agent: str
    model: ModelRef
    content: list[AssistantContent] = Field(default_factory=list)
    snapshot: Optional[SnapshotRefs] = None
    finish: Optional[FinishReason] = None
    raw_finish: Optional[str] = None
    provider_state: Optional[dict[str, Any]] = None
    cost: Optional[float] = None
    tokens: Optional[TokenUsage] = None
    error: Optional[SessionError] = None
    retry: Optional[AssistantRetry] = None
    time: AssistantTime = Field(default_factory=AssistantTime)  # type: ignore[assignment]


# --------------------------------------------------------------------------- compaction


class CompactionRunning(_Base):
    type: Literal["compaction"] = "compaction"
    status: Literal["running"] = "running"
    reason: Literal["auto", "manual"]
    summary: str = ""
    recent: str = ""


class CompactionCompleted(_Base):
    type: Literal["compaction"] = "compaction"
    status: Literal["completed"] = "completed"
    reason: Literal["auto", "manual"]
    model: Optional[ModelRef] = None
    provider_state: Optional[dict[str, Any]] = None
    summary: str
    recent: str = ""
    cost: Optional[float] = None
    tokens: Optional[TokenUsage] = None


class CompactionFailed(_Base):
    type: Literal["compaction"] = "compaction"
    status: Literal["failed"] = "failed"
    reason: Literal["auto", "manual"]
    error: SessionError
    cost: Optional[float] = None
    tokens: Optional[TokenUsage] = None


class Idle(_Base):
    """Marks the session going idle: every step since the previous marker belongs to one turn."""

    type: Literal["idle"] = "idle"
    outcome: Literal["succeeded", "failed", "interrupted"]
    error: Optional[SessionError] = None


Compaction = Union[CompactionRunning, CompactionCompleted, CompactionFailed]
Info = Union[AgentSelected, ModelSelected, LocationSwitched, User, Synthetic, System, Skill, ShellMessage, Assistant, Compaction, Idle]

_BY_TYPE: dict[str, type[_Model]] = {
    "agent-switched": AgentSelected,
    "model-switched": ModelSelected,
    "location-switched": LocationSwitched,
    "user": User,
    "synthetic": Synthetic,
    "system": System,
    "skill": Skill,
    "shell": ShellMessage,
    "assistant": Assistant,
    "idle": Idle,
}
_COMPACTION = {"running": CompactionRunning, "completed": CompactionCompleted, "failed": CompactionFailed}


def parse(data: dict[str, Any]) -> Info:
    """Build the right message class from stored data (`type`, plus `status` for compactions)."""
    kind = data.get("type")
    if kind == "compaction":
        return _COMPACTION[data["status"]].model_validate(data)  # type: ignore[return-value]
    return _BY_TYPE[kind].model_validate(data)  # type: ignore[return-value,index]


def dump(message: Info) -> dict[str, Any]:
    return message.model_dump(mode="json", exclude_none=True)
