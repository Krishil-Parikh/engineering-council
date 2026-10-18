"""Gemini lowering and stream parsing (modelled on opencode packages/ai/test for the gemini protocol)."""

import asyncio
import base64

import pytest
from google.genai import types

from harness.ai import errors as AIErr
from harness.ai import events as E
from harness.ai import types as T
from harness.ai.gemini import (
    SKIP_THOUGHT_SIGNATURE_VALIDATOR, classify_sdk_error, lower_messages, map_finish_reason, omits_function_call_ids, parse_stream,
    requires_thought_signature_fallback, wrap_system_update,
)

SIG = base64.b64encode(b"\x01sig-bytes").decode()


def lower(messages, model="gemini-3.1-flash-lite"):
    return lower_messages(types, messages, model)


# ---- lowering


def test_text_signatures_and_tool_calls_round_trip_in_the_assistant_turn():
    msgs = [
        T.Message.user("go"),
        T.Message("assistant", [
            T.ReasoningPart("thinking", provider_metadata={"google": {"thoughtSignature": SIG}}),
            T.TextPart("let me look", provider_metadata={"google": {"thoughtSignature": SIG}}),
            T.ToolCallPart("c1", "read", {"path": "a.py"}, provider_metadata={"google": {"thoughtSignature": SIG}}),
            T.ToolCallPart("c2", "read", {"path": "b.py"}),  # parallel sibling without its own signature
        ]),
    ]
    contents = lower(msgs)
    parts = contents[1].parts
    assert [p.thought for p in parts] == [True, None, None, None] or parts[0].thought is True
    assert all(p.thought_signature == b"\x01sig-bytes" for p in parts[:3])
    assert parts[2].function_call.name == "read" and parts[2].function_call.args == {"path": "a.py"} and parts[2].function_call.id == "c1"
    assert parts[3].thought_signature is None  # an unsigned sibling is valid once one call carries the signature


def test_an_unsigned_tool_call_gets_the_skip_marker_on_gemini_3_but_not_on_gemini_2():
    msgs = [T.Message.user("go"), T.Message("assistant", [T.ToolCallPart("c1", "read", {})])]
    assert lower(msgs, "gemini-3.1-flash-lite")[1].parts[0].thought_signature is not None
    assert lower(msgs, "gemini-2.5-flash")[1].parts[0].thought_signature is None
    assert lower(msgs, "gemini-2.5-flash")[1].parts[0].function_call.id is None  # gemini < 3 does not take call ids
    assert requires_thought_signature_fallback("gemini-3-pro") and not requires_thought_signature_fallback("gemini-2.0-flash") and not requires_thought_signature_fallback("claude")
    assert omits_function_call_ids("gemini-2.0-flash") and not omits_function_call_ids("gemini-3.1-flash-lite")
    assert SKIP_THOUGHT_SIGNATURE_VALIDATOR == "skip_thought_signature_validator"


def test_parallel_tool_results_share_one_user_turn_and_errors_carry_their_message():
    msgs = [
        T.Message.user("go"),
        T.Message("assistant", [T.ToolCallPart("a", "read", {}), T.ToolCallPart("b", "glob", {})]),
        T.Message.tool(T.ToolResultPart("a", "read", T.ToolResultValue("text", "1: hello"))),
        T.Message.tool(T.ToolResultPart("b", "glob", T.ToolResultValue("error", {"error": {"type": "tool.execution", "message": "no such dir"}, "content": []}))),
    ]
    contents = lower(msgs)
    assert [c.role for c in contents] == ["user", "model", "user"]
    r = [p.function_response for p in contents[2].parts]
    assert [x.name for x in r] == ["read", "glob"] and r[0].response["content"] == "1: hello" and r[1].response["content"] == "no such dir"


def test_system_updates_join_the_previous_user_turn_or_start_their_own_after_tool_results():
    after_user = lower([T.Message.user("hello"), T.Message.system("The date changed")])
    assert len(after_user) == 1 and after_user[0].parts[1].text == wrap_system_update("The date changed")
    after_tool = lower([
        T.Message.user("go"), T.Message("assistant", [T.ToolCallPart("a", "read", {})]),
        T.Message.tool(T.ToolResultPart("a", "read", T.ToolResultValue("text", "ok"))), T.Message.system("AGENTS.md changed"),
    ])
    assert len(after_tool) == 4 and after_tool[2].parts[0].function_response is not None and after_tool[3].parts[0].text.startswith("<system-update>")
    assert "&lt;/system-update&gt;" in wrap_system_update("</system-update> escape attempt")  # updates cannot close their own wrapper


def test_empty_assistant_turns_are_dropped():
    assert len(lower([T.Message.user("a"), T.Message("assistant", [T.TextPart("")]), T.Message.user("b")])) == 2


# ---- parsing


def chunk(parts=None, finish=None, usage=None):
    cand = types.Candidate(content=types.Content(role="model", parts=parts or []) if parts is not None else None, finish_reason=finish)
    return types.GenerateContentResponse(candidates=[cand], usage_metadata=usage)


def usage(prompt=1000, cached=0, out=50, thoughts=0):
    return types.GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt, cached_content_token_count=cached or None, candidates_token_count=out, thoughts_token_count=thoughts or None
    )


async def agen(items):
    for i in items:
        yield i


def parse(chunks):
    async def go():
        return [e async for e in parse_stream(agen(chunks))]

    return asyncio.run(go())


def kinds(events):
    return [type(e).__name__ for e in events]


def test_text_streams_with_its_signature_and_usage():
    ev = parse([
        chunk([types.Part(text="Hel")]), chunk([types.Part(text="lo", thought_signature=b"\x01sig-bytes")]), chunk([], "STOP", usage(1000, 200, 50, 30)),
    ])
    assert kinds(ev) == ["TextStart", "TextDelta", "TextDelta", "TextEnd", "StepFinish", "Finish"]
    end = ev[3]
    assert end.provider_metadata == {"google": {"thoughtSignature": SIG}}
    fin = ev[4]
    assert fin.normalized == "stop" and fin.raw == "STOP"
    u = fin.usage
    assert (u.non_cached_input_tokens, u.cache_read_input_tokens, u.visible_output_tokens, u.reasoning_tokens) == (800, 200, 50, 30)


def test_reasoning_then_text_then_tool_call_each_keep_their_own_signature():
    ev = parse([
        chunk([types.Part(text="think", thought=True, thought_signature=b"R")]),
        chunk([types.Part(text="answer", thought_signature=b"T")]),
        chunk([types.Part(function_call=types.FunctionCall(name="read", args={"path": "a"}), thought_signature=b"C")]),
        chunk([], "STOP", usage()),
    ])
    assert kinds(ev) == ["ReasoningStart", "ReasoningDelta", "ReasoningEnd", "TextStart", "TextDelta", "TextEnd", "ToolCall", "StepFinish", "Finish"]
    assert ev[2].provider_metadata == {"google": {"thoughtSignature": base64.b64encode(b"R").decode()}}
    assert ev[5].provider_metadata == {"google": {"thoughtSignature": base64.b64encode(b"T").decode()}}
    call = ev[6]
    assert call.name == "read" and call.input == {"path": "a"} and call.provider_metadata == {"google": {"thoughtSignature": base64.b64encode(b"C").decode()}}
    assert ev[7].normalized == "tool-calls"  # STOP with a tool call means the model wants its results


def test_a_repeated_call_id_is_replaced_so_two_calls_never_share_one():
    fc = lambda: types.Part(function_call=types.FunctionCall(id="same", name="read", args={}))  # noqa: E731
    ev = [e for e in parse([chunk([fc(), fc()]), chunk([], "STOP", usage())]) if isinstance(e, E.ToolCall)]
    assert len(ev) == 2 and ev[0].id == "same" and ev[1].id != "same" and ev[1].id.startswith("tool_")


def test_finish_reason_mapping():
    assert map_finish_reason("MAX_TOKENS", False) == "length"
    assert map_finish_reason("SAFETY", False) == "content-filter"
    assert map_finish_reason("MALFORMED_FUNCTION_CALL", False) == "error"
    assert map_finish_reason("STOP", True) == "tool-calls" and map_finish_reason(None, False) == "unknown" and map_finish_reason("OTHER", False) == "unknown"
    ev = parse([chunk([types.Part(text="cut off")]), chunk([], "MAX_TOKENS", usage())])
    assert ev[-2].normalized == "length"


def test_malformed_response_is_a_retryable_incomplete_stream_and_malformed_calls_are_errors():
    with pytest.raises(AIErr.AIError) as e:
        parse([chunk([types.Part(text="x")]), chunk([], "MALFORMED_RESPONSE")])
    assert e.value.reason.classification == "incomplete-stream" and AIErr.is_retryable(e.value)
    with pytest.raises(AIErr.AIError) as e2:
        parse([chunk([], "MALFORMED_FUNCTION_CALL")])
    assert e2.value.reason.tag == "InvalidProviderOutput" and not AIErr.is_retryable(e2.value)


def test_a_stream_with_no_finish_and_no_usage_ends_without_a_finish_event():
    assert kinds(parse([chunk([types.Part(text="partial")])])) == ["TextStart", "TextDelta"]


# ---- errors


class FakeApiError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


def test_free_tier_quota_429_with_a_retry_delay_is_a_rate_limit_not_a_hard_quota_stop():
    err = classify_sdk_error(FakeApiError(429, "You exceeded your current quota. Quota exceeded for metric. Please retry in 34.5s.", {"error": {"details": [{"retryDelay": "34s"}]}}))
    assert err.reason.tag == "RateLimit" and err.reason.retry_after_ms == 34_500 and AIErr.is_retryable(err)


def test_other_http_errors_use_the_shared_classifier():
    assert classify_sdk_error(FakeApiError(401, "API key not valid")).reason.tag == "Authentication"
    assert classify_sdk_error(FakeApiError(400, "The input token count exceeds the maximum number of tokens allowed")).reason.classification == "context-overflow"
    assert classify_sdk_error(FakeApiError(503, "The model is overloaded")).reason.tag == "ProviderInternal"
    assert classify_sdk_error(TimeoutError("slow")).reason.code == "Timeout"
    assert classify_sdk_error(ConnectionError("reset")).reason.tag == "Transport"
