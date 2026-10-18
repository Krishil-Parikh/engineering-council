"""Plain data types shared by the whole harness. Nothing here knows about a specific model provider."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class ToolResult:
    output: str
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False


@dataclass
class ToolSpec:
    """What the model is told about a tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema


@dataclass
class Message:
    """One entry of a session. `raw` is the provider's own representation of an assistant turn (it may carry signatures
    that must be sent back unchanged); it is plain JSON so a session can be saved and reloaded."""

    id: str
    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""  # role == "tool": which call this answers
    tool_name: str = ""
    is_error: bool = False
    synthetic: bool = False  # written by the harness (reminders, notifications, summaries), not by the user
    kind: str = ""  # "summary" for compaction checkpoints
    agent: str = ""
    raw: dict[str, Any] | None = None
    usage: dict[str, int] = field(default_factory=dict)
    compacted: bool = False  # kept on disk, no longer sent to the model
    snapshot: str = ""  # filesystem snapshot taken before this assistant step ran
    created: float = field(default_factory=time.time)

    def to_json(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["tool_calls"] = [c.__dict__ for c in self.tool_calls]
        return d

    @staticmethod
    def from_json(d: dict[str, Any]) -> "Message":
        d = dict(d)
        d["tool_calls"] = [ToolCall(**c) for c in d.get("tool_calls", [])]
        return Message(**d)


@dataclass
class ModelReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    usage: dict[str, int] = field(default_factory=dict)  # input_tokens, output_tokens
    finish: Literal["stop", "tool_calls", "length", "other"] = "stop"


class ModelError(Exception):
    """kind: overflow (context too long), rate_limit, transient, auth, fatal."""

    def __init__(self, message: str, kind: str = "fatal", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


@dataclass
class Event:
    kind: str  # text, thought, tool_start, tool_end, permission, step, compaction, retry, usage, note, error, message
    data: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.kind}: {json.dumps(self.data, default=str)[:300]}"


Observer = Callable[[Event], None]


class ChatModel(Protocol):
    async def complete(
        self, *, system: str, messages: list[Message], tools: list[ToolSpec], tool_choice: str = "auto",
        on_event: Observer | None = None, stage: str = "", max_output_tokens: int | None = None,
    ) -> ModelReply: ...


AskFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
