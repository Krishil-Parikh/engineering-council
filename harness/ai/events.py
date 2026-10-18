"""Streaming events a provider produces (opencode: packages/ai/src/schema/events.ts, the subset the engine consumes)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Optional, Protocol, Union

from harness.ai.types import LLMRequest
from harness.session.usage import Usage

NormalizedFinish = Literal["stop", "length", "tool-calls", "content-filter", "error", "unknown"]


@dataclass
class TextStart:
    id: str = "0"
    provider_metadata: Optional[dict[str, Any]] = None


@dataclass
class TextDelta:
    text: str
    id: str = "0"


@dataclass
class TextEnd:
    id: str = "0"
    provider_metadata: Optional[dict[str, Any]] = None


@dataclass
class ReasoningStart:
    id: str = "0"
    provider_metadata: Optional[dict[str, Any]] = None


@dataclass
class ReasoningDelta:
    text: str
    id: str = "0"


@dataclass
class ReasoningEnd:
    id: str = "0"
    provider_metadata: Optional[dict[str, Any]] = None


@dataclass
class ToolInputStart:
    id: str
    name: str


@dataclass
class ToolInputDelta:
    id: str
    text: str


@dataclass
class ToolInputEnd:
    id: str


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]
    provider_executed: bool = False
    provider_metadata: Optional[dict[str, Any]] = None


@dataclass
class StepFinish:
    usage: Optional[Usage] = None
    provider_metadata: Optional[dict[str, Any]] = None


@dataclass
class Finish:
    normalized: NormalizedFinish = "stop"
    raw: Optional[str] = None


@dataclass
class ProviderError:
    message: str
    classification: Optional[str] = None  # context-overflow | payload-too-large


LLMEvent = Union[TextStart, TextDelta, TextEnd, ReasoningStart, ReasoningDelta, ReasoningEnd, ToolInputStart, ToolInputDelta, ToolInputEnd, ToolCall, StepFinish, Finish, ProviderError]


class LLMClient(Protocol):
    """A model provider. `stream` yields events for one request and raises `AIError` for failures before or during the stream."""

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]: ...
