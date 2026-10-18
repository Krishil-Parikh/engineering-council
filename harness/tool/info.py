"""Tool contract (opencode: packages/schema/src/tool.ts).

A tool has a name, a description, an input schema (a pydantic model, or a raw JSON schema when the input is not validated
locally), and one async `execute(input, context)` returning a `ToolResult`. Expected failures are raised as `ToolError`; the
message becomes the tool result the model reads and reacts to."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Union

from pydantic import BaseModel

from harness.schema.message import FileContent, TextContent

Content = Union[TextContent, FileContent]
Metadata = dict[str, Any]


class ToolError(Exception):
    """An expected tool failure the model should see and react to (bad path, no match, declined)."""

    def __init__(self, message: str, error: Optional[BaseException] = None, metadata: Optional[Metadata] = None) -> None:
        super().__init__(message)
        self.message = message
        self.error = error
        self.metadata = metadata


@dataclass
class ToolResult:
    """`content` is what the model reads (text, or a list of text/file items); `output` is the structured value, if the tool declares one."""

    content: Union[str, list[Content], None] = None
    output: Any = None
    metadata: Optional[Metadata] = None


@dataclass
class ToolContext:
    session_id: str
    agent: str
    message_id: str
    id: str  # the tool call id
    progress: Callable[[Metadata], None] = lambda update: None


@dataclass
class ToolOptions:
    namespace: Optional[str] = None
    permission: Optional[str] = None  # rule action this tool is gated by (defaults to its name; edit/write/patch share "edit")


@dataclass
class ToolInfo:
    name: str
    description: str
    input: Union[type[BaseModel], dict[str, Any]]
    execute: Callable[[Any, ToolContext], Awaitable[ToolResult]]
    options: ToolOptions = field(default_factory=ToolOptions)
    id: str = ""  # the effective name (namespace flattened into it); set at registration
