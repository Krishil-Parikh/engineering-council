"""The session runner (opencode: packages/core/src/session/runner/llm.ts).

`drain` runs a session until the model stops asking for tools. Each iteration is one *step*: bring the instruction state up to
date, compact if the context is near the window, build the request, run it, and act on the outcome. A step limit turns the last
step into a text-only wrap-up; output-limit cut-offs and broken streams are continued with a short instruction."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from harness.ai import events as E
from harness.ai import types as T
from harness.ai.errors import AIError
from harness.permission import Permission
from harness.schema import message as M
from harness.session import compaction as C
from harness.session import model_request as R
from harness.session.context import SessionContext
from harness.session.recorder import Recorder
from harness.session.retry import RetryPolicy
from harness.session.runner.max_steps import MAX_STEPS_PROMPT
from harness.session.runner.step import Outcome, RunInterrupted, Snapshots, Step, StepInput
from harness.session.store import SessionStore
from harness.session.to_session_error import StepFailedError, to_session_error
from harness.tool.output import ToolOutput
from harness.tool.registry import Call

log = logging.getLogger("harness.runner")

CONTINUE_AFTER_INCOMPLETE_STREAM = "The previous response was interrupted. Continue from where you left off without repeating completed content."
CONTINUE_AFTER_OUTPUT_LIMIT = (
    "Your last response hit the output token limit (stop reason: length). Do not apologize, recap, or repeat yourself. Break the remaining work into smaller pieces."
)


@dataclass
class DrainResult:
    outcome: str  # succeeded | failed | interrupted
    steps: int = 0
    error: Optional[M.SessionError] = None


class SessionRunner:
    def __init__(
        self, *, store: SessionStore, context: SessionContext, llm: E.LLMClient, compaction: C.Compaction, tool_output: ToolOutput,
        snapshots: Optional[Snapshots] = None, observer: Optional[Callable[[str, dict[str, Any]], None]] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, context_hooks: Optional[list[Callable[[dict[str, Any]], None]]] = None,
    ) -> None:
        # `context` hooks see (and may edit) the model messages of every request: {"sessionID", "agent", "messages", "synthetic"}.
        self.context_hooks = context_hooks if context_hooks is not None else []
        self.store, self.context, self.llm, self.compaction, self.tool_output = store, context, llm, compaction, tool_output
        self.snapshots, self.observer, self.sleep = snapshots or Snapshots(), observer, sleep

    # ---- crash recovery
    def settle_stale_compactions(self, session_id: str) -> None:
        """A process death skips compaction finalizers: close compactions still marked running, newest first."""
        rows = self.store.db.all(
            "select * from session_message where session_id = ? and type = 'compaction' and json_extract(data, '$.status') = 'running' order by seq desc", (session_id,)
        )
        for row in rows:
            msg = SessionStore.decode_row(row)
            if isinstance(msg, M.CompactionRunning):
                self.store.save(session_id, M.CompactionFailed(
                    id=msg.id, reason=msg.reason, error=M.SessionError(type="compaction.interrupted", message="Compaction was interrupted")
                ))

    def settle_stale_tool_calls(self, session_id: str, rec: Recorder) -> None:
        for _, message in self.store.messages(session_id):
            if not isinstance(message, M.Assistant):
                continue
            for part in message.content:
                if not isinstance(part, M.AssistantTool) or part.state.status not in ("streaming", "running"):
                    continue
                metadata = part.state.metadata if part.state.status == "running" else None
                child = metadata.get("sessionID") if metadata and part.name == "subagent" else None
                rec.tool_failed(
                    message.id, part.id,
                    M.SessionError(type="aborted", message=f"Tool execution interrupted: {part.name}{f' (sessionID: {child})' if child else ''}"),
                    executed=part.executed is True, metadata=metadata or None,
                )

    # ---- the loop
    async def drain(self, session_id: str) -> DrainResult:
        rec = Recorder(self.store, session_id, self.observer)
        self.settle_stale_compactions(session_id)
        self.settle_stale_tool_calls(session_id, rec)
        step = 1
        try:
            while True:
                continuing = await self._run_step(session_id, rec, step)
                if not continuing:
                    break
                step += 1
        except (RunInterrupted, asyncio.CancelledError) as exc:
            rec.idle("interrupted")
            if isinstance(exc, asyncio.CancelledError):
                raise
            return DrainResult("interrupted", step)
        except BaseException as exc:  # noqa: BLE001 - the failure is recorded on the session; callers read DrainResult
            error = to_session_error(exc)
            log.warning("session %s failed: %s", session_id, error.message)
            rec.idle("failed", error)
            return DrainResult("failed", step, error)
        rec.idle("succeeded")
        return DrainResult("succeeded", step)

    async def _run_step(self, session_id: str, rec: Recorder, step: int) -> bool:
        assistant_message_id = M.new_message_id()
        retry = RetryPolicy()
        recover_overflow = True
        step_runner = Step(self.llm, rec, self.tool_output, self.snapshots)
        while True:
            selection, loaded = self.context.context(session_id)
            compacted = await self.compaction.compact(C.Trigger("auto", loaded))
            if compacted.status == "failed":
                raise StepFailedError(compacted.error)  # type: ignore[arg-type]
            if compacted.status == "completed":
                assistant_message_id = M.new_message_id()
                continue
            limit_reached = loaded.agent.steps is not None and step >= loaded.agent.steps
            transcript = R.base_transcript(
                agent_system=loaded.agent.system, model=loaded.model, tool_names=[t.name for t in loaded.tools], initial=loaded.initial, messages=loaded.messages
            )
            hooked = list(transcript.messages)
            for hook in self.context_hooks:
                hook({"sessionID": session_id, "agent": loaded.agent.id, "messages": hooked, "synthetic": lambda text: rec.synthetic(text)})
            messages = [*hooked, T.Message.assistant(MAX_STEPS_PROMPT)] if limit_reached else hooked
            request = T.LLMRequest(
                system=transcript.system, tools=list(loaded.tools), messages=messages,
                generation=T.Generation(max_tokens=R.output_limit(loaded.model.limit, "primary", C.estimate_prompt(loaded))),
                # Keep tool definitions on the final step to preserve the provider's cached prefix.
                tool_choice="none" if limit_reached else None,
            )
            definitions = {d.name: d for d in request.tools}
            amid = assistant_message_id

            async def execute_tool(call: T.ToolCallPart, progress: Callable[[dict], None], _amid: str = amid) -> Any:
                return await selection.snapshot.execute(
                    session_id=session_id, agent=loaded.agent.id, message_id=_amid, call=Call(call.id, call.name, call.input), progress=progress, definitions=definitions
                )

            async def recover() -> bool:
                if not recover_overflow:
                    return False
                out = await self.compaction.compact(C.Trigger("overflow", loaded))
                return out.status == "completed"

            outcome: Outcome = await step_runner.attempt(StepInput(
                session_id=session_id, assistant_message_id=assistant_message_id, agent=loaded.agent.id, model=loaded.model, request=request,
                execute_tool=execute_tool, retry=lambda cause, error, proposed: retry.decide(cause, retry=proposed), recover_overflow=recover,
            ))
            kind = outcome.kind
            if kind == "Completed":
                return outcome.needs_continuation
            if kind == "Retry":
                await self._wait(rec, assistant_message_id, outcome)
            elif kind == "Continue":
                await self._wait(rec, assistant_message_id, outcome)
                rec.synthetic(CONTINUE_AFTER_INCOMPLETE_STREAM)
                assistant_message_id = M.new_message_id()
            elif kind == "OutputLimit":
                # The current response is included. User input or any other finish breaks the streak.
                recent = [m for _, m in self.store.messages(session_id) if isinstance(m, (M.User, M.Assistant))][-3:]
                if len(recent) == 3 and all(isinstance(m, M.Assistant) and m.finish == "length" for m in recent):
                    raise StepFailedError(M.SessionError(type="output-limit", message="Response still truncated after two output token limit continuations"))
                if outcome.needs_continuation:
                    return True
                rec.synthetic(CONTINUE_AFTER_OUTPUT_LIMIT)
                assistant_message_id = M.new_message_id()
            elif kind == "Compacted":
                recover_overflow = False
                assistant_message_id = M.new_message_id()

    async def _wait(self, rec: Recorder, assistant_message_id: str, outcome: Outcome) -> None:
        d = outcome.decision
        assert d is not None and outcome.error is not None
        at = M.now_ms() + d.delay_ms
        rec.retry_scheduled(assistant_message_id, d.attempt, at, outcome.error)
        await self.sleep(max(0, at - M.now_ms()) / 1000)
