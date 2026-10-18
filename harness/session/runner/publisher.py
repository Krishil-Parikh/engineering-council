"""Turning a model's streamed events into recorded session state (opencode: session/runner/publish-llm-event.ts).

One publisher lives for one step. It remembers which tool calls exist and whether each has been called and settled, enforces
the ordering rules (a result needs a call, a call is settled once), and records everything through the Recorder. Tool calls
whose arguments never completed are failed with a message that tells the model how to recover."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from harness.ai import events as E
from harness.schema import message as M
from harness.session import usage as SessionUsage
from harness.session.recorder import Recorder
from harness.session.to_session_error import content_filter_error
from harness.tool.info import Content, Metadata

INPUT_EXCERPT_LIMIT = 2048

INPUT_FAILURES = {
    "malformed": M.SessionError(
        type="tool.input-json",
        message="The tool input could not be parsed as JSON, so the call was not executed. Reissue the call with valid JSON arguments.",
    ),
    "length": M.SessionError(
        type="tool.input-incomplete",
        message="The tool call was not executed because the output token limit (stop reason: length) was reached before you could complete the arguments. Break large payloads into smaller tool calls and reissue the call with complete arguments.",
    ),
    "incomplete": M.SessionError(
        type="tool.input-incomplete", message="Tool call arguments were not completed and were not executed. Reissue the call with complete arguments."
    ),
}


def input_failure(excerpt: Optional[tuple[str, int]], reason: str) -> M.SessionError:
    failure = INPUT_FAILURES[reason]
    if not excerpt or not excerpt[1]:
        return failure
    text, length = excerpt
    truncated = "\n[truncated]" if length > len(text) else ""
    return M.SessionError(type=failure.type, message=f"{failure.message}\n\nInput excerpt (first {len(text)} of {length} characters):\n{text}{truncated}")


@dataclass
class StepSettlement:
    finish: str
    raw_finish: Optional[str]
    provider_state: Optional[dict[str, Any]]
    tokens: M.TokenUsage


@dataclass
class StepRecord:
    """Immutable view of what a step has recorded so far."""

    output_started: bool
    provider_failed: bool
    failure: Optional[M.SessionError]
    finish: Optional[StepSettlement]
    needs_continuation: bool


@dataclass
class _Tool:
    name: str
    called: bool = False
    settled: bool = False
    provider_executed: bool = False
    progress: Optional[Metadata] = None
    input: Optional[tuple[str, int]] = None
    malformed: bool = False


class _Fragments:
    """Open text / reasoning / tool-input blocks of the step, accumulated until they end."""

    def __init__(self, name: str, ended: Callable[[str, str, int, Optional[dict]], None], delta: Optional[Callable[[str, str, int], None]] = None, single: bool = False) -> None:
        self.name, self.ended, self.delta, self.single = name, ended, delta, single
        self.chunks: dict[str, dict[str, Any]] = {}
        self.next_ordinal = 0

    def start(self, id: str, state: Optional[dict] = None) -> int:
        if id in self.chunks:
            raise RuntimeError(f"Duplicate {self.name} start: {id}")
        if self.single and self.chunks:
            raise RuntimeError(f"{self.name} start before end: {id}")
        ordinal = self.next_ordinal
        self.next_ordinal += 1
        self.chunks[id] = {"ordinal": ordinal, "values": [], "state": state}
        return ordinal

    def append(self, id: str, value: str, state: Optional[dict] = None) -> int:
        cur = self.chunks.get(id)
        if cur is None:
            raise RuntimeError(f"{self.name} delta before start: {id}")
        cur["values"].append(value)
        if state is not None:
            cur["state"] = {**(cur["state"] or {}), **state}
        if self.delta:
            self.delta(id, value, cur["ordinal"])
        return cur["ordinal"]

    def end(self, id: str, state: Optional[dict] = None, value: Optional[str] = None) -> None:
        cur = self.chunks.get(id)
        if cur is None:
            raise RuntimeError(f"{self.name} end before start: {id}")
        merged = cur["state"] if state is None else {**(cur["state"] or {}), **state}
        self.ended(id, value if value is not None else "".join(cur["values"]), cur["ordinal"], merged)
        del self.chunks[id]

    def flush(self) -> None:
        for id in list(self.chunks):
            self.end(id)

    def has(self, id: str) -> bool:
        return id in self.chunks


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {"value": value}


class LLMEventPublisher:
    def __init__(
        self, recorder: Recorder, *, agent: str, model: M.ModelRef, provider_metadata_key: str, assistant_message_id: str, started: int,
        start_snapshot: Callable[[], Optional[str]] = lambda: None,
    ) -> None:
        self.rec, self.agent, self.model, self.key = recorder, agent, model, provider_metadata_key
        self.assistant_message_id, self.started, self._start_snapshot = assistant_message_id, started, start_snapshot
        self._tools: dict[str, _Tool] = {}
        self._step_started = False
        self._provider_failed = False
        self._output_started = False
        self._failure: Optional[M.SessionError] = None
        self._settlement: Optional[StepSettlement] = None
        mid = lambda: self.assistant_message_id  # noqa: E731
        self._text = _Fragments("text", lambda _i, v, _o, st: self.rec.text_ended(mid(), v, st), lambda _i, v, _o: self.rec.text_delta(mid(), v), single=True)
        self._reasoning = _Fragments("reasoning", lambda _i, v, _o, st: self.rec.reasoning_ended(mid(), v, st), lambda _i, v, _o: self.rec.reasoning_delta(mid(), v), single=True)
        self._tool_input = _Fragments("tool input", self._tool_input_ended)

    # ---- state helpers
    def _provider_state(self, metadata: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        return None if metadata is None else metadata.get(self.key)

    def start_assistant(self) -> str:
        if self._step_started:
            return self.assistant_message_id
        snapshot = self._start_snapshot()
        self._step_started = True
        self.rec.step_started(assistant_message_id=self.assistant_message_id, agent=self.agent, model=self.model, started=self.started, snapshot=snapshot)
        return self.assistant_message_id

    def _require_started(self) -> str:
        if not self._step_started:
            raise RuntimeError("Tool event before assistant step start")
        return self.assistant_message_id

    def streamed(self) -> None:
        self.rec.step_streamed(self.start_assistant())

    def has_provider_error(self) -> bool:
        return self._provider_failed

    def has_started(self) -> bool:
        return self._step_started

    def record(self) -> StepRecord:
        return StepRecord(
            self._output_started, self._provider_failed, self._failure, self._settlement,
            any(not t.provider_executed and (t.called or t.settled) for t in self._tools.values()),
        )

    # ---- tool input
    def _tool_input_ended(self, id: str, value: str, _ordinal: int, _state: Optional[dict]) -> None:
        tool = self._tools.get(id)
        if tool is None:
            raise RuntimeError(f"Tool input end before start: {id}")
        tool.input = (value[:INPUT_EXCERPT_LIMIT], len(value))  # a bounded excerpt for recovery errors; the full text is persisted below
        self.rec.tool_input_ended(self.assistant_message_id, id, value)

    def _start_tool_input(self, id: str, name: str, provider_executed: bool = False) -> _Tool:
        if id in self._tools:
            raise RuntimeError(f"Duplicate tool input start: {id}")
        self.start_assistant()
        tool = _Tool(name=name, provider_executed=provider_executed)
        self._tools[id] = tool
        self._tool_input.start(id)
        self._publish_pending_deltas()
        self.rec.tool_input_started(self.assistant_message_id, id, name)
        return tool

    def _end_tool_input(self, id: str, name: str, value: Optional[str] = None) -> None:
        tool = self._tools.get(id)
        if tool is None:
            raise RuntimeError(f"Tool input end before start: {id}")
        if tool.name != name:
            raise RuntimeError(f"Tool input name changed for {id}: {tool.name} -> {name}")
        if not self._tool_input.has(id):
            raise RuntimeError(f"Duplicate tool input end: {id}")
        self._tool_input.end(id, None, value)

    def _fail_malformed_tool_input(self, id: str, name: str, raw: str) -> None:
        tool = self._tools.get(id) or self._start_tool_input(id, name)
        if tool.called or tool.settled:
            raise RuntimeError(f"Malformed tool input after call settlement: {id}")
        if tool.name != name:
            raise RuntimeError(f"Tool input name changed for {id}: {tool.name} -> {name}")
        if self._tool_input.has(id):
            self._end_tool_input(id, name, raw)
        tool.input = (raw[:INPUT_EXCERPT_LIMIT], len(raw))
        tool.malformed = True

    def _publish_pending_deltas(self) -> None:
        pass  # deltas are emitted immediately, so there is nothing held back

    def _flush_fragments(self) -> None:
        self._text.flush()
        self._reasoning.flush()
        self._tool_input.flush()

    def flush(self) -> None:
        self._flush_fragments()
        # The finish reason distinguishes invalid JSON from arguments cut off by the output limit.
        for id, tool in self._tools.items():
            if tool.malformed and not tool.settled:
                self._fail_tool_input(id, tool, "malformed")

    def _fail_tool_input(self, id: str, tool: _Tool, reason: str) -> None:
        use = "length" if self._settlement and self._settlement.finish == "length" else reason
        self.fail_tool(id, input_failure(tool.input, use))

    # ---- failing things
    def fail_tool(self, id: str, error: M.SessionError, metadata: Optional[Metadata] = None) -> bool:
        tool = self._tools.get(id)
        if tool is None or tool.settled:
            return False
        tool.settled = True
        if tool.name == "subagent" and error.type == "aborted" and isinstance((tool.progress or {}).get("sessionID"), str):
            error = M.SessionError(type=error.type, message=f"{error.message} (sessionID: {tool.progress['sessionID']})")  # type: ignore[index]
        merged = metadata if tool.progress is None else ({**tool.progress, **(metadata or {})})
        self.rec.tool_failed(self.assistant_message_id, id, error, executed=tool.provider_executed, metadata=merged)
        return True

    def fail_tools(self, error: M.SessionError, mode: str) -> bool:
        failed = False
        for id, tool in self._tools.items():
            if tool.settled or (mode == "hosted" and not tool.provider_executed) or (mode == "uncalled" and tool.called):
                continue
            if self.fail_tool(id, error):
                failed = True
        return failed

    def fail_incomplete_tools(self) -> None:
        for id, tool in self._tools.items():
            if not tool.called and not tool.settled:
                self._fail_tool_input(id, tool, "incomplete")

    def fail_assistant(self, error: M.SessionError) -> None:
        self.flush()
        self.fail_tools(error, "uncalled")
        self.start_assistant()
        if self._failure is None:
            self._failure = error

    def publish_step_failure(self, *, cost: Optional[float] = None, tokens: Optional[M.TokenUsage] = None, snapshot: Optional[str] = None, files: Optional[list[str]] = None) -> None:
        if self._failure is None:
            return
        mid = self.start_assistant()
        s = self._settlement
        self.rec.step_failed(
            mid, error=self._failure, finish="content-filter" if s and s.finish == "content-filter" else None, raw_finish=s.raw_finish if s else None,
            provider_state=s.provider_state if s else None, cost=cost, tokens=tokens, snapshot=snapshot, files=files,
        )

    def fail_unsettled_tools(self, error: M.SessionError, scope: str = "all") -> bool:
        return self.fail_tools(error, scope)

    # ---- the event stream
    def publish(self, event: E.LLMEvent) -> None:
        if isinstance(event, E.TextStart):
            self._output_started = True
            self._text.start(event.id, self._provider_state(event.provider_metadata))
            self._publish_pending_deltas()
            self.rec.text_started(self.start_assistant())
        elif isinstance(event, E.TextDelta):
            self._text.append(event.id, event.text)
        elif isinstance(event, E.TextEnd):
            self._text.end(event.id, self._provider_state(event.provider_metadata))
        elif isinstance(event, E.ReasoningStart):
            self._output_started = True
            self._reasoning.start(event.id, self._provider_state(event.provider_metadata))
            self._publish_pending_deltas()
            self.rec.reasoning_started(self.start_assistant(), self._provider_state(event.provider_metadata))
        elif isinstance(event, E.ReasoningDelta):
            self._reasoning.append(event.id, event.text)
        elif isinstance(event, E.ReasoningEnd):
            self._reasoning.end(event.id, self._provider_state(event.provider_metadata))
        elif isinstance(event, E.ToolInputStart):
            self._output_started = True
            self._start_tool_input(event.id, event.name)
        elif isinstance(event, E.ToolInputDelta):
            tool = self._tools.get(event.id)
            if tool is None:
                raise RuntimeError(f"Tool input delta before start: {event.id}")
            if not self._tool_input.has(event.id):
                raise RuntimeError(f"Tool input delta after end: {event.id}")
            self._tool_input.append(event.id, event.text)
        elif isinstance(event, E.ToolInputEnd):
            tool = self._tools.get(event.id)
            self._end_tool_input(event.id, tool.name if tool else "")
        elif isinstance(event, E.ToolInputError):
            self._output_started = True
            self._fail_malformed_tool_input(event.id, event.name, event.raw)
        elif isinstance(event, E.ToolCall):
            self._output_started = True
            tool = self._tools.get(event.id) or self._start_tool_input(event.id, event.name, event.provider_executed)
            if self._tool_input.has(event.id):
                self._end_tool_input(event.id, event.name)
            if tool.name != event.name:
                raise RuntimeError(f"Tool call name changed for {event.id}: {tool.name} -> {event.name}")
            if tool.called:
                raise RuntimeError(f"Duplicate tool call: {event.id}")
            tool.called = True
            tool.provider_executed = event.provider_executed is True
            self.rec.tool_called(self.assistant_message_id, event.id, _as_record(event.input), tool.provider_executed, self._provider_state(event.provider_metadata))
        elif isinstance(event, E.StepFinish):
            self._flush_fragments()
            if self._settlement:
                raise RuntimeError("Duplicate step finish")
            self._settlement = StepSettlement(event.normalized, event.raw, self._provider_state(event.provider_metadata), SessionUsage.tokens(event.usage))
            if event.normalized == "content-filter":
                self._provider_failed = True
                self.fail_assistant(content_filter_error("Provider blocked the response", event.raw))
        elif isinstance(event, E.Finish):
            return
        elif isinstance(event, E.ProviderError):
            self._provider_failed = True
            self.fail_assistant(M.SessionError(type="provider.unknown", message=event.message))

    def progress(self, id: str, update: Metadata) -> None:
        tool = self._tools.get(id)
        if tool is None or not tool.called or tool.settled:
            raise RuntimeError(f"Tool progress outside running call: {id}")
        tool.progress = update
        self.rec.tool_progress(self.assistant_message_id, id, update)

    def tool_execution(self, id: str, name: str, content: list[Content], metadata: Optional[Metadata] = None) -> None:
        """One terminal success for a locally executed tool call."""
        tool = self._tools.get(id)
        if tool is None or not tool.called:
            raise RuntimeError(f"Tool execution before call: {id}")
        if tool.name != name:
            raise RuntimeError(f"Tool execution name changed for {id}: {tool.name} -> {name}")
        if tool.settled:
            raise RuntimeError(f"Duplicate tool execution: {id}")
        tool.settled = True
        if not content:
            raise RuntimeError(f"Tool execution has no content: {id}")
        self.rec.tool_success(self.assistant_message_id, id, content, executed=tool.provider_executed, metadata=metadata)
