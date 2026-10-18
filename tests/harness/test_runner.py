"""The step loop: streaming, tools, retries, overflow, output limits, step limit, declines.

Modelled on opencode's session-runner, session-step and session-runner-retry tests."""

import asyncio
from typing import AsyncIterator, Callable

import pytest
from pydantic import BaseModel

from harness.ai import errors as AIErr
from harness.ai import events as E
from harness.ai import types as T
from harness.instruction_discovery import InstructionDiscovery
from harness.location import Location
from harness.permission import DeclinedError
from harness.schema import message as M
from harness.schema.permission import Rule
from harness.session import compaction as C
from harness.session import history
from harness.session.compaction import AgentInfo, Compaction
from harness.session.context import SessionContext
from harness.session.recorder import Recorder
from harness.session.runner.runner import CONTINUE_AFTER_INCOMPLETE_STREAM, CONTINUE_AFTER_OUTPUT_LIMIT, SessionRunner
from harness.session.usage import Usage
from harness.skill import SkillCatalog
from harness.tool.info import ToolError, ToolInfo, ToolResult
from harness.tool.output import ToolOutput
from harness.tool.registry import ToolRegistry
from harness.util.global_paths import GlobalPaths
from harness.config import service as cfg
from tests.harness.conftest import MODEL, SUMMARY


# ---- scripted model


def text_reply(text, finish="stop", usage=None):
    return [
        E.TextStart(), E.TextDelta(text[: len(text) // 2]), E.TextDelta(text[len(text) // 2 :]), E.TextEnd(),
        E.StepFinish(usage or Usage(non_cached_input_tokens=100, visible_output_tokens=10), normalized=finish), E.Finish(finish),
    ]


def tool_reply(*calls, text=""):
    ev = [E.TextStart(), E.TextDelta(text), E.TextEnd()] if text else []
    for i, (name, args) in enumerate(calls):
        ev.append(E.ToolCall(f"call_{name}_{i}_{abs(hash(str(args))) % 9999}", name, args))
    return [*ev, E.StepFinish(Usage(non_cached_input_tokens=120, visible_output_tokens=20), normalized="tool-calls"), E.Finish("tool-calls")]


class ScriptedLLM:
    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[T.LLMRequest] = []

    async def stream(self, request: T.LLMRequest) -> AsyncIterator[E.LLMEvent]:
        self.requests.append(request)
        item = self.script.pop(0) if self.script else text_reply("done")
        if callable(item):
            item = item(request)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, str):
            item = text_reply(item)
        for ev in item:
            if isinstance(ev, BaseException):
                raise ev
            yield ev


# ---- fixtures


class EchoInput(BaseModel):
    text: str
    times: int = 1


class Rig:
    def __init__(self, store, tmp_path, llm, agent=None, rules=None):
        self.store, self.llm = store, llm
        home = tmp_path / "home"
        self.proj = home / "proj"
        self.proj.mkdir(parents=True, exist_ok=True)
        paths = GlobalPaths.default(root=tmp_path / "global", home=home).ensure()
        loc = Location.of(self.proj)
        config = cfg.Config(loc, paths)
        self.registry = ToolRegistry()
        self.calls: list[str] = []
        self.registry.add(ToolInfo("echo", "Echo text back", EchoInput, self._echo))
        self.registry.add(ToolInfo("boom", "Always fails", {"type": "object", "properties": {}}, self._boom))
        self.registry.add(ToolInfo("needs_approval", "Asks permission", {"type": "object", "properties": {}}, self._approval))
        self.registry.add(ToolInfo("big", "Large output", {"type": "object", "properties": {}}, self._big))
        self.agent = agent or AgentInfo("build")
        self.rules = rules or [Rule("*", "*", "allow")]
        self.observed: list[tuple[str, dict]] = []
        self.ctx = SessionContext(
            store, loc, paths, InstructionDiscovery(loc, paths, config), SkillCatalog(),
            resolve_agent=lambda name: (self.agent, self.rules), resolve_model=lambda s: MODEL, tools_for=self.registry.snapshot,
        )

        async def no_sleep(_):
            self.slept.append(_)

        self.slept: list[float] = []
        self.compaction = Compaction(store, llm, settings=C.Settings(), sleep=no_sleep)
        self.runner = SessionRunner(
            store=store, context=self.ctx, llm=llm, compaction=self.compaction, tool_output=ToolOutput(tmp_path / "out"),
            observer=lambda k, d: self.observed.append((k, d)), sleep=no_sleep,
        )
        self.session = store.create(str(self.proj), agent="build")

    async def _echo(self, inp, ctx):
        self.calls.append(inp.text)
        return ToolResult(content=inp.text * inp.times, metadata={"len": len(inp.text)})

    async def _boom(self, inp, ctx):
        raise ToolError("it broke: disk is full")

    async def _approval(self, inp, ctx):
        raise DeclinedError()

    async def _big(self, inp, ctx):
        return ToolResult(content="\n".join(f"line {i}" for i in range(5000)))

    def prompt(self, text="go"):
        Recorder(self.store, self.session.id).user(text)
        return asyncio.run(self.runner.drain(self.session.id))

    def messages(self):
        return [m for _, m in self.store.messages(self.session.id)]

    def assistants(self):
        return [m for m in self.messages() if isinstance(m, M.Assistant)]


@pytest.fixture
def rig(store, tmp_path):
    def make(*script, **kw):
        return Rig(store, tmp_path, ScriptedLLM(*script), **kw)

    return make


def tools_of(a):
    return [p for p in a.content if isinstance(p, M.AssistantTool)]


# ---- basics


def test_a_plain_reply_is_recorded_with_usage_and_the_session_goes_idle(rig):
    r = rig(text_reply("Hello there"))
    res = r.prompt("hi")
    assert res.outcome == "succeeded" and res.steps == 1
    (a,) = r.assistants()
    assert [type(p).__name__ for p in a.content] == ["AssistantText"] and a.content[0].text == "Hello there"
    assert a.finish == "stop" and a.tokens.input == 100 and a.time.completed is not None
    assert isinstance(r.messages()[-1], M.Idle) and r.messages()[-1].outcome == "succeeded"
    assert r.store.get(r.session.id).tokens.input == 100  # session totals
    deltas = [d["text"] for k, d in r.observed if k == "text.delta"]
    assert "".join(deltas) == "Hello there"


def test_the_request_carries_system_prompt_instructions_and_history(rig):
    r = rig(text_reply("ok"))
    r.prompt("do the thing")
    req = r.llm.requests[0]
    assert "coding agent harness" in req.system[0].text and "Today's date:" in req.system[1].text
    assert req.messages[0].role == "user" and req.messages[0].content[0].text == "do the thing"
    assert {t.name for t in req.tools} == {"echo", "boom", "needs_approval", "big"} and req.generation.max_tokens > 0


def test_a_tool_call_runs_and_its_result_goes_back_to_the_model(rig):
    r = rig(tool_reply(("echo", {"text": "ab", "times": 2}), text="Let me echo."), text_reply("It said abab"))
    res = r.prompt("echo something")
    assert res.outcome == "succeeded" and res.steps == 2 and r.calls == ["ab"]
    first, second = r.assistants()
    (t,) = tools_of(first)
    assert t.state.status == "completed" and t.state.content[0].text == "abab" and t.state.metadata == {"len": 2, "truncated": False}
    assert first.content[0].text == "Let me echo." and second.content[0].text == "It said abab"
    # step 2's request replays the assistant turn and the tool result
    msgs = r.llm.requests[1].messages
    assert [m.role for m in msgs] == ["user", "assistant", "tool"]
    assert isinstance(msgs[1].content[-1], T.ToolCallPart) and msgs[2].content[0].result.value == "abab"


def test_parallel_tool_calls_all_execute_and_settle(rig):
    r = rig(tool_reply(("echo", {"text": "a"}), ("echo", {"text": "b"}), ("echo", {"text": "c"})), text_reply("done"))
    r.prompt()
    assert sorted(r.calls) == ["a", "b", "c"]
    assert [t.state.status for t in tools_of(r.assistants()[0])] == ["completed"] * 3


def test_unknown_tools_and_invalid_arguments_are_returned_to_the_model(rig):
    r = rig(tool_reply(("nonexistent", {}), ("echo", {"times": "x"})), text_reply("sorry"))
    assert r.prompt().outcome == "succeeded"
    unknown, invalid = tools_of(r.assistants()[0])
    assert unknown.state.status == "error" and 'No tool named "nonexistent"' in unknown.state.error.message
    assert invalid.state.status == "error" and 'Invalid arguments for tool "echo"' in invalid.state.error.message
    assert "- text:" in invalid.state.error.message and "- times:" in invalid.state.error.message and "call the tool again" in invalid.state.error.message


def test_a_failing_tool_is_recorded_and_the_run_continues(rig):
    r = rig(tool_reply(("boom", {})), text_reply("I could not do that"))
    assert r.prompt().outcome == "succeeded"
    (t,) = tools_of(r.assistants()[0])
    assert t.state.status == "error" and t.state.error.type == "tool.execution" and "disk is full" in t.state.error.message


def test_large_tool_output_is_truncated_to_a_file(rig, tmp_path):
    r = rig(tool_reply(("big", {})), text_reply("ok"))
    r.prompt()
    (t,) = tools_of(r.assistants()[0])
    texts = [c.text for c in t.state.content]
    assert t.state.metadata["truncated"] is True and "[showing lines 1-" in texts[-1] and "of 5000; full output saved to" in texts[-1]
    assert len(list((tmp_path / "out").glob("tool_*"))) == 1


# ---- errors, retries, recovery


def test_a_rate_limit_before_any_output_is_retried_on_the_same_assistant_message(rig):
    limited = AIErr.classify_provider_failure("rate limited", status=429, retry_after_ms=3000)
    r = rig(limited, limited, text_reply("finally"))
    res = r.prompt()
    assert res.outcome == "succeeded" and len(r.llm.requests) == 3
    assert len(r.assistants()) == 1 and r.assistants()[0].content[0].text == "finally" and r.assistants()[0].retry is None
    assert len(r.slept) == 2 and r.slept[0] >= 3.0  # retry-after raises the delay
    assert [k for k, _ in r.observed].count("retry.scheduled") == 2


def test_an_authentication_error_fails_the_run_and_is_recorded(rig):
    r = rig(AIErr.classify_provider_failure("bad key", status=401))
    res = r.prompt()
    assert res.outcome == "failed" and res.error.type == "provider.auth" and len(r.llm.requests) == 1
    (a,) = r.assistants()
    assert a.error.type == "provider.auth" and a.finish == "error"
    assert isinstance(r.messages()[-1], M.Idle) and r.messages()[-1].outcome == "failed"


def test_retries_stop_after_the_policy_is_exhausted(rig):
    boom = AIErr.classify_provider_failure("server error", status=503)
    r = rig(*[boom] * 20)
    res = r.prompt()
    assert res.outcome == "failed" and len(r.llm.requests) == 11  # the first try plus ten retries


def test_a_context_overflow_compacts_and_retries_once(rig):
    overflow = AIErr.error("InvalidRequest", "prompt is too long", classification="context-overflow")
    r = rig()
    # seed enough history to have something to compact
    for i in range(4):
        r.store.add(r.session.id, M.User(text=f"q{i} " + "x" * 4000))
        r.store.add(r.session.id, M.Assistant(agent="build", model=MODEL.ref, content=[M.AssistantText(text=f"a{i}")], finish="stop"))
    r.llm.script = [overflow, SUMMARY, text_reply("answered after compaction")]
    res = r.prompt("and now?")
    assert res.outcome == "succeeded"
    assert any(isinstance(m, M.CompactionCompleted) for m in r.messages())
    assert len(r.assistants()) >= 1 and r.assistants()[-1].content[0].text == "answered after compaction"


def test_a_second_overflow_after_compaction_fails_instead_of_looping(rig):
    overflow = AIErr.error("InvalidRequest", "prompt is too long", classification="context-overflow")
    r = rig()
    for i in range(4):
        r.store.add(r.session.id, M.User(text=f"q{i} " + "x" * 4000))
        r.store.add(r.session.id, M.Assistant(agent="build", model=MODEL.ref, content=[M.AssistantText(text=f"a{i}")], finish="stop"))
    r.llm.script = [overflow, SUMMARY, overflow, overflow]
    assert r.prompt("go").outcome == "failed"


def test_auto_compaction_runs_before_a_request_that_would_not_fit(rig):
    r = rig()
    for i in range(6):
        r.store.add(r.session.id, M.User(text=f"q{i} " + "x" * 60000))
        r.store.add(r.session.id, M.Assistant(agent="build", model=MODEL.ref, content=[M.AssistantText(text=f"a{i}")], finish="stop"))
    r.llm.script = [SUMMARY, text_reply("ok")]  # the first model call is the compaction summary
    assert r.prompt("continue").outcome == "succeeded"
    assert r.llm.requests[0].messages[-1].content[0].text.startswith("You MUST summarize")
    first_real = r.llm.requests[1]
    assert "conversation-checkpoint" in first_real.messages[0].content[0].text


def test_a_stream_that_breaks_after_output_is_recorded_and_continued(rig):
    cut = AIErr.error("InvalidProviderOutput", "stream ended early", classification="incomplete-stream")
    partial = [E.TextStart(), E.TextDelta("I started to"), cut]
    r = rig(partial, text_reply("finish the thought"))
    res = r.prompt()
    assert res.outcome == "succeeded" and len(r.llm.requests) == 2
    first, second = r.assistants()
    assert first.error.type == "provider.invalid-output" and first.content[0].text == "I started to" and second.content[0].text == "finish the thought"
    assert any(isinstance(m, M.Synthetic) and m.text == CONTINUE_AFTER_INCOMPLETE_STREAM for m in r.messages())


def test_output_limit_asks_for_smaller_pieces_and_gives_up_after_two_tries(rig):
    r = rig(text_reply("part one", finish="length"), text_reply("part two", finish="stop"))
    assert r.prompt().outcome == "succeeded"
    assert any(isinstance(m, M.Synthetic) and m.text == CONTINUE_AFTER_OUTPUT_LIMIT for m in r.messages())
    r2 = rig(*[text_reply("again", finish="length")] * 5)
    res = r2.prompt()
    assert res.outcome == "failed" and res.error.type == "output-limit" and len(r2.llm.requests) == 3


def test_a_tool_call_cut_off_by_the_output_limit_tells_the_model_how_to_recover(rig):
    partial = [E.ToolInputStart("c1", "echo"), E.ToolInputDelta("c1", '{"text": "abc'), E.ToolInputError("c1", "echo", '{"text": "abc'), E.StepFinish(Usage(), normalized="length"), E.Finish("length")]
    r = rig(partial, text_reply("retrying smaller"))
    r.prompt()
    (t,) = tools_of(r.assistants()[0])
    assert t.state.status == "error" and t.state.error.type == "tool.input-incomplete" and "output token limit" in t.state.error.message
    assert 'Input excerpt (first 13 of 13 characters)' in t.state.error.message


# ---- limits and permissions


def test_the_step_limit_makes_the_last_step_text_only(rig):
    r = rig(tool_reply(("echo", {"text": "a"})), tool_reply(("echo", {"text": "b"})), tool_reply(("echo", {"text": "c"})), text_reply("I ran out of steps"), agent=AgentInfo("build", steps=2))
    res = r.prompt()
    assert res.outcome == "succeeded" and len(r.llm.requests) == 2  # steps=2: one normal step, then the text-only wrap-up
    last = r.llm.requests[-1]
    assert last.tool_choice == "none" and last.tools and last.messages[-1].role == "assistant" and "MAXIMUM STEPS REACHED" in last.messages[-1].content[0].text
    assert r.calls == ["a"]  # the wrap-up step could not call tools


def test_declining_a_tool_call_stops_the_run_as_interrupted(rig):
    r = rig(tool_reply(("needs_approval", {})), text_reply("never reached"))
    res = r.prompt()
    assert res.outcome == "interrupted" and len(r.llm.requests) == 1
    (t,) = tools_of(r.assistants()[0])
    assert t.state.status == "error" and t.state.error.type == "aborted" and "declined" in t.state.error.message
    assert r.assistants()[0].error.type == "aborted"
    assert r.messages()[-1].outcome == "interrupted"


def test_tools_the_permissions_deny_are_not_advertised(rig):
    r = rig(text_reply("ok"), rules=[Rule("*", "*", "allow"), Rule("boom", "*", "deny"), Rule("needs_approval", "*", "deny")])
    r.prompt()
    assert {t.name for t in r.llm.requests[0].tools} == {"echo", "big"}


def test_interrupted_tool_calls_from_a_crashed_run_are_closed_on_the_next_run(rig):
    r = rig(text_reply("resumed"))
    hanging = M.Assistant(agent="build", model=MODEL.ref, content=[M.AssistantTool(id="c9", name="echo", state=M.ToolStateRunning(input={"text": "x"}))])
    r.store.add(r.session.id, M.User(text="earlier"))
    r.store.add(r.session.id, hanging)
    r.store.add(r.session.id, M.CompactionRunning(reason="auto"))
    r.prompt("continue")
    stale = next(m for m in r.messages() if isinstance(m, M.Assistant) and m.id == hanging.id)
    assert tools_of(stale)[0].state.status == "error" and "interrupted" in tools_of(stale)[0].state.error.message
    assert any(isinstance(m, M.CompactionFailed) and m.error.type == "compaction.interrupted" for m in r.messages())


def test_the_first_message_after_a_reply_sees_gemini_thought_state_replayed(rig):
    state_reply = [
        E.TextStart(provider_metadata={"google": {"thoughtSignature": "sig-1"}}), E.TextDelta("hello"), E.TextEnd(provider_metadata={"google": {"thoughtSignature": "sig-1"}}),
        E.StepFinish(Usage(), normalized="stop"), E.Finish("stop"),
    ]
    r = rig(state_reply, text_reply("second"))
    r.prompt("one")
    assert r.assistants()[0].content[0].state == {"thoughtSignature": "sig-1"}
    r.prompt("two")
    replayed = r.llm.requests[1].messages[1].content[0]
    assert replayed.provider_metadata == {"google": {"thoughtSignature": "sig-1"}}
