"""The tool registry and per-request snapshot (opencode: packages/core/src/tool.ts and tool/runtime.ts).

Tools register by effective name (a namespace is flattened into it, `ns_tool`). Registering the same name again replaces the
earlier tool. A *snapshot* is taken for each model request: the definitions it advertises (tools the permissions deny outright
are left out, so the model never tries what it can never do) and an `execute` that runs a call against exactly those tools."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from harness.ai.types import ToolEntry
from harness.schema.message import FileContent, TextContent
from harness.schema.permission import Ruleset
from harness.tool.info import Content, Metadata, ToolContext, ToolError, ToolInfo, ToolResult
from harness.tool.schema import decode_input, to_json_schema
from harness.util import wildcard

NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class RegistrationError(Exception):
    pass


def normalized_name(tool: ToolInfo) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", tool.name)


def effective_name(tool: ToolInfo) -> str:
    ns = tool.options.namespace
    return normalized_name(tool) if ns is None else f"{ns.replace('.', '_')}_{normalized_name(tool)}"


def stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


def normalize_content(value: Any, output: Any = None) -> list[Content]:
    if isinstance(value, str):
        return [TextContent(text=value)]
    if value:
        return list(value)
    return [TextContent(text=stringify(output))]


def definition(tool: ToolInfo) -> ToolEntry:
    return ToolEntry(name=tool.id or effective_name(tool), description=tool.description, input_schema=to_json_schema(tool.input))


def whollly_disabled(action: str, rules: Ruleset) -> bool:
    """The last rule for this action denies every use of it."""
    rule = next((r for r in reversed(rules) if wildcard.match(action, r.action)), None)
    return rule is not None and rule.resource == "*" and rule.effect == "deny"


@dataclass
class NormalizedResult:
    content: list[Content]
    output: Any = None
    metadata: Optional[Metadata] = None


@dataclass
class Call:
    id: str
    name: str
    input: Any


Hook = Callable[[dict[str, Any]], None]


@dataclass
class Snapshot:
    definitions: list[ToolEntry]
    _tools: dict[str, ToolInfo] = field(default_factory=dict)
    _before: list[Hook] = field(default_factory=list)
    _after: list[Hook] = field(default_factory=list)

    async def execute(
        self, *, session_id: str, agent: str, message_id: str, call: Call, progress: Optional[Callable[[Metadata], None]] = None,
        definitions: Optional[dict[str, ToolEntry]] = None,
    ) -> NormalizedResult:
        """Run one call. Raises ToolError for failures the model should read; anything else is a defect."""
        context = ToolContext(session_id, agent, message_id, call.id, progress or (lambda update: None))
        event: dict[str, Any] = {"tool": call.name, "sessionID": session_id, "agent": agent, "messageID": message_id, "id": call.id, "input": call.input}
        for hook in self._before:
            hook(event)  # a hook may repair the input or rename the tool
        name = event["tool"]
        if definitions is not None and name not in definitions and name in self._tools:
            raise ToolError(f"Tool is not available for this request: {name}")
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f'No tool named "{name}" is currently available. Please use a tool from the available tool list.')
        try:
            result = await self._run(tool, event["input"], context)
        except ToolError as failure:
            for hook in self._after:
                hook({**event, "status": "error", "error": failure})
            raise
        after = {**event, "status": "completed", "result": result}
        for hook in self._after:
            hook(after)
        return after["result"]

    @staticmethod
    async def _run(tool: ToolInfo, raw: Any, context: ToolContext) -> NormalizedResult:
        try:
            decoded = decode_input(tool, raw)
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        try:
            result = await tool.execute(decoded, context)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - plugins can fail with anything; the contract is enforced at this untrusted boundary
            from harness.permission import BlockedError, CorrectedError, DeclinedError

            if isinstance(exc, DeclinedError):
                raise  # a plain "no" ends the run; the step records the decline, it is not tool output
            if isinstance(exc, CorrectedError):  # a "no" with feedback: the model continues and adjusts
                raise ToolError(f"The user rejected this action and said: {exc.feedback}", exc) from None
            if isinstance(exc, BlockedError):
                raise ToolError(str(exc), exc) from None
            raise ToolError(str(exc) or type(exc).__name__, exc) from None
        return NormalizedResult(normalize_content(result.content, result.output), result.output, result.metadata)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolInfo] = {}
        self.before: list[Hook] = []
        self.after: list[Hook] = []
        self.errors: list[str] = []

    # ---- editing
    def add(self, tool: ToolInfo) -> None:
        name = normalized_name(tool)
        if not NAME_RE.fullmatch(name):
            self.errors.append(f"Invalid tool name: {name}")
            return
        try:
            tool.id = effective_name(tool)
            definition(tool)  # must produce a valid schema
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"Invalid tool definition {tool.name}: {exc}")
            return
        self._tools[tool.id] = tool

    def update(self, tool_id: str, update: Callable[[ToolInfo], None]) -> None:
        current = self._tools.get(tool_id)
        if current is not None:
            update(current)

    def remove(self, tool_id: str) -> None:
        self._tools.pop(tool_id, None)

    def get(self, tool_id: str) -> Optional[ToolInfo]:
        return self._tools.get(tool_id)

    def list(self) -> list[ToolInfo]:
        return list(self._tools.values())

    # ---- per request
    def snapshot(self, permissions: Optional[Ruleset] = None) -> Snapshot:
        rules = permissions or []
        active = {name: t for name, t in self._tools.items() if not whollly_disabled(t.options.permission or name, rules)}
        defs = [definition(t) for _, t in sorted(active.items())]
        return Snapshot(defs, active, list(self.before), list(self.after))
