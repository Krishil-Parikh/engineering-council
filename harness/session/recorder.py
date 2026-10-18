"""Recording what happens in a session (opencode: packages/core/src/session/message-updater.ts).

opencode derives messages from a stream of durable events. Here the runner calls these methods directly; each one applies the
same change to the stored message that the matching event would, then persists it and tells the observer. The assistant message
of a step is created on `step_started` and filled in as text, reasoning and tool calls stream in; a tool call moves through
streaming -> running -> completed | error."""

from __future__ import annotations

from typing import Any, Callable, Optional

from harness.schema import message as M
from harness.session.store import SessionStore

Observer = Callable[[str, dict[str, Any]], None]


class Recorder:
    def __init__(self, store: SessionStore, session_id: str, observer: Optional[Observer] = None) -> None:
        self.store, self.session_id, self.observer = store, session_id, observer

    def _emit(self, kind: str, **data: Any) -> None:
        if self.observer:
            self.observer(kind, {"session": self.session_id, **data})

    # ---- lookups
    def assistant(self, message_id: str) -> Optional[M.Assistant]:
        msg = self.store.get_message(self.session_id, message_id)
        return msg if isinstance(msg, M.Assistant) else None

    def current_assistant(self) -> Optional[M.Assistant]:
        row = self.store.db.get("select * from session_message where session_id = ? and type = 'assistant' order by seq desc limit 1", (self.session_id,))
        return SessionStore.decode_row(row) if row else None  # type: ignore[return-value]

    def current_compaction(self) -> Optional[M.Info]:
        row = self.store.db.get("select * from session_message where session_id = ? and type = 'compaction' order by seq desc limit 1", (self.session_id,))
        return SessionStore.decode_row(row) if row else None

    def _update(self, message_id: str, recipe: Callable[[M.Assistant], None]) -> Optional[M.Assistant]:
        a = self.assistant(message_id)
        if a is None:
            return None
        recipe(a)
        self.store.save(self.session_id, a)
        return a

    @staticmethod
    def _latest_tool(a: M.Assistant, tool_id: str) -> Optional[M.AssistantTool]:
        return next((i for i in reversed(a.content) if isinstance(i, M.AssistantTool) and i.id == tool_id), None)

    # ---- user-side messages
    def user(self, text: str, **kw: Any) -> M.User:
        msg = M.User(text=text, **kw)
        self.store.add(self.session_id, msg)
        self._emit("message.user", id=msg.id, text=text)
        return msg

    def synthetic(self, text: str, description: Optional[str] = None, metadata: Optional[dict[str, Any]] = None) -> M.Synthetic:
        msg = M.Synthetic(text=text, description=description, metadata=metadata)
        self.store.add(self.session_id, msg)
        self._emit("message.synthetic", id=msg.id, text=text)
        return msg

    def skill_activated(self, skill_id: str, name: str, text: str) -> M.Skill:
        msg = M.Skill(skill=skill_id, name=name, text=text)
        self.store.add(self.session_id, msg)
        return msg

    def agent_selected(self, agent: str, previous: Optional[str] = None) -> None:
        self.store.add(self.session_id, M.AgentSelected(agent=agent, previous=previous))

    def model_selected(self, model: M.ModelRef, previous: Optional[M.ModelRef] = None) -> None:
        self.store.add(self.session_id, M.ModelSelected(model=model, previous=previous))

    def shell_started(self, shell_id: str, command: str, status: str = "running", background: bool = False) -> M.ShellMessage:
        msg = M.ShellMessage(shell_id=shell_id, command=command, status=status, metadata={"background": True} if background else None)
        self.store.add(self.session_id, msg)
        return msg

    def shell_ended(self, shell_id: str, status: str, exit: Optional[float], output: dict[str, Any]) -> None:
        row = self.store.db.get("select * from session_message where session_id = ? and type = 'shell' and json_extract(data, '$.shell_id') = ?", (self.session_id, shell_id))
        if row is None:
            return
        msg = SessionStore.decode_row(row)
        assert isinstance(msg, M.ShellMessage)
        msg.status, msg.exit, msg.output = status, exit, output
        msg.time.completed = M.now_ms()
        self.store.save(self.session_id, msg)

    # ---- a step (one model request and its tool calls)
    def step_started(self, *, assistant_message_id: str, agent: str, model: M.ModelRef, started: int, snapshot: Optional[str] = None) -> None:
        existing = self.assistant(assistant_message_id)
        if existing is not None:  # a retry of the same step: reset it
            existing.agent, existing.model = agent, model
            existing.retry = existing.error = existing.finish = existing.raw_finish = existing.provider_state = None
            existing.time.created, existing.time.streamed, existing.time.completed = started, None, None
            if snapshot:
                existing.snapshot = M.SnapshotRefs(start=snapshot, end=existing.snapshot.end if existing.snapshot else None, files=existing.snapshot.files if existing.snapshot else None)
            self.store.save(self.session_id, existing)
            return
        current = self.current_assistant()
        if current is not None:
            current.retry = None
            current.time.completed = M.now_ms()
            self.store.save(self.session_id, current)
        self.store.add(self.session_id, M.Assistant(
            id=assistant_message_id, agent=agent, model=model, content=[], time=M.AssistantTime(created=started),
            snapshot=M.SnapshotRefs(start=snapshot) if snapshot else None,
        ))
        self._emit("step.started", id=assistant_message_id)

    def step_streamed(self, assistant_message_id: str) -> None:
        self._update(assistant_message_id, lambda a: setattr(a.time, "streamed", M.now_ms()))

    def _terminal_snapshot(self, a: M.Assistant, snapshot: Optional[str], files: Optional[list[str]]) -> None:
        if snapshot or files:
            a.snapshot = M.SnapshotRefs(start=a.snapshot.start if a.snapshot else None, end=snapshot, files=list(files) if files else None)

    def step_ended(
        self, assistant_message_id: str, *, finish: str, raw_finish: Optional[str], provider_state: Optional[dict[str, Any]], cost: float,
        tokens: M.TokenUsage, snapshot: Optional[str] = None, files: Optional[list[str]] = None,
    ) -> None:
        def apply(a: M.Assistant) -> None:
            a.time.completed = M.now_ms()
            a.finish, a.raw_finish, a.provider_state, a.cost, a.tokens = finish, raw_finish, provider_state, cost, tokens  # type: ignore[assignment]
            self._terminal_snapshot(a, snapshot, files)

        self._update(assistant_message_id, apply)
        self.store.add_usage(self.session_id, cost, tokens)
        self._emit("step.ended", id=assistant_message_id, finish=finish)

    def step_failed(
        self, assistant_message_id: str, *, error: M.SessionError, finish: Optional[str] = None, raw_finish: Optional[str] = None,
        provider_state: Optional[dict[str, Any]] = None, cost: Optional[float] = None, tokens: Optional[M.TokenUsage] = None,
        snapshot: Optional[str] = None, files: Optional[list[str]] = None,
    ) -> None:
        def apply(a: M.Assistant) -> None:
            a.time.completed = M.now_ms()
            a.finish, a.raw_finish, a.provider_state, a.error, a.retry = finish or "error", raw_finish, provider_state, error, None  # type: ignore[assignment]
            if cost is not None and tokens is not None:
                a.cost, a.tokens = cost, tokens
            self._terminal_snapshot(a, snapshot, files)

        self._update(assistant_message_id, apply)
        if cost is not None and tokens is not None:
            self.store.add_usage(self.session_id, cost, tokens)
        else:
            self.store.touch(self.session_id)
        self._emit("step.failed", id=assistant_message_id, error=error.message)

    # ---- content
    def text_started(self, assistant_message_id: str) -> None:
        self._update(assistant_message_id, lambda a: a.content.append(M.AssistantText(text="")))

    def text_delta(self, assistant_message_id: str, delta: str) -> None:
        self._emit("text.delta", id=assistant_message_id, text=delta)

    def text_ended(self, assistant_message_id: str, text: str, state: Optional[dict[str, Any]] = None) -> None:
        def apply(a: M.Assistant) -> None:
            match = next((i for i in reversed(a.content) if isinstance(i, M.AssistantText)), None)
            if match:
                match.text, match.state = text, state

        self._update(assistant_message_id, apply)
        self._emit("text.ended", id=assistant_message_id, text=text)

    def reasoning_started(self, assistant_message_id: str, state: Optional[dict[str, Any]] = None) -> None:
        self._update(assistant_message_id, lambda a: a.content.append(M.AssistantReasoning(text="", state=state, time=M.ReasoningTime())))

    def reasoning_delta(self, assistant_message_id: str, delta: str) -> None:
        self._emit("reasoning.delta", id=assistant_message_id, text=delta)

    def reasoning_ended(self, assistant_message_id: str, text: str, state: Optional[dict[str, Any]] = None) -> None:
        def apply(a: M.Assistant) -> None:
            match = next((i for i in reversed(a.content) if isinstance(i, M.AssistantReasoning) and not (i.time and i.time.completed)), None)
            if match:
                match.text = text
                match.time = M.ReasoningTime(created=match.time.created if match.time else M.now_ms(), completed=M.now_ms())
                if state is not None:
                    match.state = state

        self._update(assistant_message_id, apply)

    # ---- tools
    def tool_input_started(self, assistant_message_id: str, tool_id: str, name: str) -> None:
        self._update(assistant_message_id, lambda a: a.content.append(M.AssistantTool(id=tool_id, name=name, state=M.ToolStateStreaming(input=""))))
        self._emit("tool.input.started", id=assistant_message_id, tool=name, call=tool_id)

    def tool_input_ended(self, assistant_message_id: str, tool_id: str, text: str) -> None:
        def apply(a: M.Assistant) -> None:
            t = self._latest_tool(a, tool_id)
            if t and t.state.status == "streaming":
                t.state.input = text

        self._update(assistant_message_id, apply)

    def tool_called(self, assistant_message_id: str, tool_id: str, input: dict[str, Any], executed: bool, state: Optional[dict[str, Any]]) -> None:
        def apply(a: M.Assistant) -> None:
            t = self._latest_tool(a, tool_id)
            if t:
                t.executed, t.provider_state = executed, state
                t.time.ran = M.now_ms()
                t.state = M.ToolStateRunning(input=input, metadata={})

        self._update(assistant_message_id, apply)
        self._emit("tool.called", id=assistant_message_id, call=tool_id, input=input)

    def tool_progress(self, assistant_message_id: str, tool_id: str, metadata: dict[str, Any]) -> None:
        self._emit("tool.progress", id=assistant_message_id, call=tool_id, metadata=metadata)

    def tool_success(
        self, assistant_message_id: str, tool_id: str, content: list[M.TextContent | M.FileContent], *, executed: bool = False,
        result_state: Optional[dict[str, Any]] = None, metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        def apply(a: M.Assistant) -> None:
            t = self._latest_tool(a, tool_id)
            if t and t.state.status == "running":
                t.executed = executed or t.executed is True
                t.provider_result_state = result_state
                t.time.completed = M.now_ms()
                t.state = M.ToolStateCompleted(input=t.state.input, content=content, metadata=metadata)

        self._update(assistant_message_id, apply)
        self._emit("tool.success", id=assistant_message_id, call=tool_id)

    def tool_failed(
        self, assistant_message_id: str, tool_id: str, error: M.SessionError, *, executed: bool = False, result_state: Optional[dict[str, Any]] = None,
        content: Optional[list[M.TextContent | M.FileContent]] = None, metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        def apply(a: M.Assistant) -> None:
            t = self._latest_tool(a, tool_id)
            if t and t.state.status in ("streaming", "running"):
                t.executed = executed or t.executed is True
                t.provider_result_state = result_state
                t.time.completed = M.now_ms()
                t.state = M.ToolStateError(input={} if isinstance(t.state.input, str) else t.state.input, error=error, content=content, metadata=metadata)

        self._update(assistant_message_id, apply)
        self._emit("tool.failed", id=assistant_message_id, call=tool_id, error=error.message)

    # ---- retry and idle
    def retry_scheduled(self, assistant_message_id: str, attempt: int, at: int, error: M.SessionError) -> None:
        self._update(assistant_message_id, lambda a: setattr(a, "retry", M.AssistantRetry(attempt=attempt, at=at, error=error)))
        self._emit("retry.scheduled", id=assistant_message_id, attempt=attempt, error=error.message)

    def clear_current_retry(self) -> None:
        a = self.current_assistant()
        if a is not None and a.retry is not None:
            a.retry = None
            self.store.save(self.session_id, a)

    def idle(self, outcome: str, error: Optional[M.SessionError] = None) -> None:
        self.clear_current_retry()
        self.store.add(self.session_id, M.Idle(outcome=outcome, error=error))  # type: ignore[arg-type]
        self._emit("idle", outcome=outcome)
