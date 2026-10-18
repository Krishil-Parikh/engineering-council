"""Provider-neutral model request types (opencode: packages/ai/src/schema/messages.ts and llm.ts, reduced to what the
engine uses): messages made of typed content parts, a system prompt made of parts, tool entries, and a request."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Optional, Union

ProviderMetadata = dict[str, dict[str, Any]]  # {providerKey: state}


@dataclass
class SystemPart:
    text: str
    type: Literal["text"] = "text"
    metadata: Optional[dict[str, Any]] = None


@dataclass
class TextPart:
    text: str
    type: Literal["text"] = "text"
    metadata: Optional[dict[str, Any]] = None
    provider_metadata: Optional[ProviderMetadata] = None


@dataclass
class MediaAsset:
    media_type: str
    data: str = ""  # base64


@dataclass
class MediaPart:
    media: MediaAsset
    type: Literal["media"] = "media"
    filename: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    provider_metadata: Optional[ProviderMetadata] = None


@dataclass
class ReasoningPart:
    text: str
    type: Literal["reasoning"] = "reasoning"
    encrypted: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    provider_metadata: Optional[ProviderMetadata] = None


@dataclass
class ToolCallPart:
    id: str
    name: str
    input: Any
    type: Literal["tool-call"] = "tool-call"
    provider_executed: Optional[bool] = None
    metadata: Optional[dict[str, Any]] = None
    provider_metadata: Optional[ProviderMetadata] = None


@dataclass
class ToolResultValue:
    """type: json | text | error | content. `content` values are tool content items ({"type": "text"|"file", ...})."""

    type: str
    value: Any


@dataclass
class ToolResultPart:
    id: str
    name: str
    result: ToolResultValue
    type: Literal["tool-result"] = "tool-result"
    provider_executed: Optional[bool] = None
    metadata: Optional[dict[str, Any]] = None
    provider_metadata: Optional[ProviderMetadata] = None


@dataclass
class CompactionPart:
    provider: str
    type: Literal["compaction"] = "compaction"
    id: Optional[str] = None
    text: Optional[str] = None
    encrypted: Optional[str] = None


ContentPart = Union[TextPart, MediaPart, ReasoningPart, ToolCallPart, ToolResultPart, CompactionPart]


@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: list[ContentPart]
    id: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None

    # ---- constructors (opencode: Message.make / user / assistant / system / text / tool)
    @staticmethod
    def make(*, role: str, content: Union[str, list[ContentPart], None] = None, id: Optional[str] = None, metadata: Optional[dict[str, Any]] = None) -> "Message":
        if content is None:
            parts: list[ContentPart] = []
        elif isinstance(content, str):
            parts = [TextPart(content)]
        else:
            parts = list(content)
        return Message(role, parts, id, metadata)  # type: ignore[arg-type]

    @staticmethod
    def user(text: str) -> "Message":
        return Message.make(role="user", content=text)

    @staticmethod
    def assistant(text: str) -> "Message":
        return Message.make(role="assistant", content=text)

    @staticmethod
    def system(text: str) -> "Message":
        return Message.make(role="system", content=text)

    @staticmethod
    def text(text: str) -> TextPart:
        return TextPart(text)

    @staticmethod
    def tool(result: ToolResultPart) -> "Message":
        return Message("tool", [result])


@dataclass
class ToolEntry:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    type: Literal["tool"] = "tool"


@dataclass
class Generation:
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None


@dataclass
class LLMRequest:
    system: list[SystemPart] = field(default_factory=list)
    tools: list[ToolEntry] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    generation: Optional[Generation] = None
    tool_choice: Optional[str] = None  # None/"auto" or "none"

    def update(self, **changes: Any) -> "LLMRequest":
        return replace(self, **changes)


def json_dumps(value: Any) -> str:
    """JS-like JSON.stringify (compact, UTF-8 kept)."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)
