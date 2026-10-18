"""One model step (opencode: packages/core/src/session/runner/step.ts).

A step sends one request, records the streamed response, and runs the tool calls the model makes while the stream is still
open (concurrently, one task per call). It then settles every outcome:

  Completed     the model finished; `needs_continuation` says whether tool results must go back to it
  Retry         the provider failed before any output; wait and send the same step again
  Continue      the stream broke after output had started; record it and continue from there
  Compacted     the provider said the context was too long and compaction made room
  OutputLimit   the reply was cut off by the output limit

User declines of a tool call stop the run; other failures are recorded on the message and raised."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from harness.ai import events as E
from harness.ai import types as T
from harness.ai.errors import AIError, error as ai_error, is_context_overflow_failure, is_retryable
from harness.ai.model import ResolvedModel
from harness.permission import CorrectedError, DeclinedError
from harness.schema import message as M
from harness.session import usage as SessionUsage
from harness.session.recorder import Recorder
from harness.session.retry import Decision
from harness.session.runner.publisher import LLMEventPublisher
from harness.session.to_session_error import StepFailedError, to_session_error
from harness.tool.info import ToolError
from harness.tool.output import ToolOutput
from harness.tool.registry import NormalizedResult

log = logging.getLogger("harness.step")

TOOLS_INTERRUPTED = M.SessionError(type="aborted", message="Tool execution interrupted")
STEP_INTERRUPTED = M.SessionError(type="aborted", message="Step interrupted")
RESULT_MISSING = M.SessionError(type="tool.result-missing", message="Provider did not return a tool result")


class RunInterrupted(Exception):
    """The user declined a tool call (or cancelled a question): the run stops here and the session goes idle as interrupted."""


@dataclass
class Outcome:
    kind: str  # Completed | Retry | Continue | RecoverFull | Compacted | OutputLimit
    needs_continuation: bool = False
    error: Optional[M.SessionError] = None
    decision: Optional[Decision] = None


class Snapshots:
    """What the step needs from file snapshots (implemented by harness.snapshot.Snapshots; optional)."""

    def capture(self) -> Optional[str]:
        return None

    def files(self, frm: str, to: str) -> Optional[list[str]]:
        return None


@dataclass
class StepInput:
    session_id: str
    assistant_message_id: str
    agent: str
    model: ResolvedModel
    request: T.LLMRequest
    execute_tool: Callable[[T.ToolCallPart, Callable[[dict], None]], Awaitable[NormalizedResult]]
    retry: Callable[[AIError, M.SessionError, bool], Decision]
    recover_overflow: Callable[[], Awaitable[bool]]
    recover_continuation: bool = True
    is_location_closed: Callable[[], bool] = lambda: False


def _overflow(failure: Any) -> bool:
    if isinstance(failure, E.ProviderError):
        return failure.classification == "context-overflow"
    return is_context_overflow_failure(failure)


def _is_interrupted_stream(failure: AIError) -> bool:
    if failure.reason.tag == "InvalidProviderOutput":
        return failure.reason.classification == "incomplete-stream"
    if failure.reason.tag == "Transport":
        return failure.reason.transport_operation == "read"
    return False


class Step:
    def __init__(self, llm: E.LLMClient, recorder: Recorder, tool_output: ToolOutput, snapshots: Optional[Snapshots] = None) -> None:
        self.llm, self.rec, self.tool_output, self.snapshots = llm, recorder, tool_output, snapshots or Snapshots()

    async def attempt(self, inp: StepInput) -> Outcome:
        start_snapshot = await asyncio.to_thread(self.snapshots.capture)
        pub = LLMEventPublisher(
            self.rec, agent=inp.agent, model=inp.model.ref, provider_metadata_key=inp.model.metadata_key,
            assistant_message_id=inp.assistant_message_id, started=M.now_ms(), start_snapshot=lambda: start_snapshot,
        )
        runs: list[tuple[E.ToolCall, asyncio.Task]] = []

        async def run_tool(call: E.ToolCall) -> None:
            part = T.ToolCallPart(id=call.id, name=call.name, input=call.input)
            try:
                if inp.request.tool_choice == "none":
                    raise ToolError("Tools are disabled after the maximum agent steps")
                result = await inp.execute_tool(part, lambda update: pub.progress(call.id, update))
                bounded = self.tool_output.truncate(result)
                pub.tool_execution(call.id, call.name, bounded.content, bounded.metadata)
            except ToolError as error:
                pub.fail_tool(call.id, to_session_error(error), error.metadata)

        overflow_failure: Optional[E.ProviderError] = None
        stream_error: Optional[BaseException] = None
        stream_interrupted = False
        try:
            async for event in self.llm.stream(inp.request):
                if overflow_failure is not None or pub.has_provider_error():
                    continue  # read to the end so the next request can reuse this response
                if isinstance(event, E.ProviderError) and _overflow(event) and not pub.record().output_started:
                    overflow_failure = event
                    continue
                pub.publish(event)
                if isinstance(event, E.ToolCall) and not event.provider_executed:
                    runs.append((event, asyncio.create_task(run_tool(event))))
        except asyncio.CancelledError as exc:
            stream_interrupted, stream_error = True, exc
        except BaseException as exc:  # noqa: BLE001 - AIError and anything else the provider raises
            stream_error = exc
        finally:
            pub.flush()

        if overflow_failure is None and pub.has_started():
            pub.streamed()
        if stream_interrupted:
            for _, task in runs:
                task.cancel()
        # Join tool tasks. A user decline is a typed outcome; any other exception is a defect to surface after settling.
        results = await asyncio.gather(*(t for _, t in runs), return_exceptions=True)
        declines: list[tuple[E.ToolCall, BaseException]] = []
        tool_failure: Optional[BaseException] = None
        tools_interrupted = False
        for (call, _), res in zip(runs, results):
            if isinstance(res, asyncio.CancelledError):
                tools_interrupted = True
            elif isinstance(res, (DeclinedError, CorrectedError, RunInterrupted)):
                declines.append((call, res))
            elif isinstance(res, BaseException) and tool_failure is None:
                tool_failure = res

        overflow = overflow_failure if overflow_failure is not None else stream_error
        if not pub.record().output_started and _overflow(overflow) and await inp.recover_overflow():
            log.warning("provider rejected the request as too long; compacting (session %s)", inp.session_id)
            return Outcome("Compacted")

        if overflow_failure is not None:
            pub.publish(overflow_failure)
        recorded = pub.record()
        unknown_finish = (
            ai_error("InvalidProviderOutput", "The provider response ended with an unknown finish reason.", classification="incomplete-stream")
            if stream_error is None and recorded.finish is not None and recorded.finish.finish == "unknown"
            else None
        )
        llm_failure: Optional[AIError] = stream_error if isinstance(stream_error, AIError) else unknown_finish
        llm_error = to_session_error(llm_failure) if llm_failure is not None and not recorded.provider_failed else None
        decision: Optional[Decision] = None
        if llm_failure is not None and llm_error is not None and not _overflow(llm_failure):
            decision = inp.retry(llm_failure, llm_error, is_retryable(llm_failure) or (recorded.output_started and _is_interrupted_stream(llm_failure)))
        if llm_failure is not None and llm_error is not None and decision is not None and decision.retry and not recorded.output_started:
            pub.start_assistant()  # retry state projects onto the existing assistant, even before it has produced output
            return Outcome("Retry", error=llm_error, decision=decision)
        if llm_error is not None:
            pub.fail_assistant(llm_error)

        for call, reason in declines:
            msg = "Interaction cancelled because the location shut down" if inp.is_location_closed() else (str(reason) if isinstance(reason, RunInterrupted) else "The user declined this tool call")
            pub.fail_tool(call.id, M.SessionError(type="aborted", message=msg))
        interrupted = bool(declines) or stream_interrupted or tools_interrupted
        if interrupted:
            failure_error: Optional[M.SessionError] = TOOLS_INTERRUPTED
        elif tool_failure is not None:
            failure_error = to_session_error(tool_failure)
        else:
            failure_error = TOOLS_INTERRUPTED if recorded.provider_failed else None
        if failure_error is not None:
            pub.fail_unsettled_tools(failure_error)
        if interrupted:
            pub.fail_assistant(STEP_INTERRUPTED)

        # Parsers may leave unfinished calls without an execution event.
        if llm_error is not None or (stream_error is None and not recorded.provider_failed):
            missing = pub.fail_unsettled_tools(RESULT_MISSING, "hosted")
            if missing and llm_error is None and recorded.finish is None:
                pub.fail_assistant(RESULT_MISSING)
            pub.fail_incomplete_tools()

        record = pub.record()
        if record.finish is not None or record.failure is not None:
            snapshot = await asyncio.to_thread(self.snapshots.capture)
            files = None
            if start_snapshot and snapshot:
                files = [] if start_snapshot == snapshot else await asyncio.to_thread(self.snapshots.files, start_snapshot, snapshot)
            usage = None
            if record.finish is not None:
                usage = (SessionUsage.calculate_cost(inp.model.cost, record.finish.tokens), record.finish.tokens)
            if record.failure is not None:
                pub.publish_step_failure(cost=usage[0] if usage else None, tokens=usage[1] if usage else None, snapshot=snapshot, files=files)
            if record.finish is not None and usage is not None and record.failure is None:
                mid = pub.start_assistant()
                self.rec.step_ended(
                    mid, finish=record.finish.finish, raw_finish=record.finish.raw_finish, provider_state=record.finish.provider_state,
                    cost=usage[0], tokens=usage[1], snapshot=snapshot, files=files,
                )

        if llm_failure is not None and llm_error is not None and decision is not None and decision.retry and record.output_started and not declines and not tools_interrupted:
            return Outcome("Continue", error=llm_error, decision=decision)

        if stream_error is not None:
            raise stream_error
        if declines:
            if inp.is_location_closed():
                return Outcome("Completed", needs_continuation=True)
            raise RunInterrupted("The user declined a tool call")
        if tools_interrupted and tool_failure is not None:
            raise tool_failure
        if record.failure is not None:
            raise StepFailedError(record.failure)
        if tool_failure is not None:
            raise tool_failure
        needs_continuation = inp.request.tool_choice != "none" and record.needs_continuation
        if record.finish is not None and record.finish.finish == "length":
            return Outcome("OutputLimit", needs_continuation=needs_continuation)
        return Outcome("Completed", needs_continuation=needs_continuation)
