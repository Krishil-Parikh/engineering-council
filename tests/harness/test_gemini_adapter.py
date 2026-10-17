import json

from coding_harness.llm_gemini import GeminiChatModel, classify
from coding_harness.types import Message, ToolCall


class Boom(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def model():
    return GeminiChatModel("fake-key", "gemini-3.1-flash-lite")


def test_assistant_turns_are_replayed_verbatim_including_signatures():
    m = model()
    t = m.types
    original = t.Content(role="model", parts=[t.Part(function_call=t.FunctionCall(name="read", args={"path": "a"}), thought_signature=b"\x01\x02sig")])
    raw = json.loads(original.model_dump_json(exclude_none=True))
    msgs = [
        Message("1", "user", "go"),
        Message("2", "assistant", "", [ToolCall("c1", "read", {"path": "a"})], raw=raw),
        Message("3", "tool", "1: hello", tool_call_id="c1", tool_name="read"),
    ]
    contents = m._contents(msgs)
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[1].parts[0].thought_signature == b"\x01\x02sig"
    fr = contents[2].parts[0].function_response
    assert fr.name == "read" and fr.response == {"output": "1: hello"}


def test_parallel_results_share_one_user_turn_and_errors_are_marked():
    m = model()
    msgs = [
        Message("1", "user", "go"),
        Message("2", "assistant", "", [ToolCall("a", "read", {}), ToolCall("b", "glob", {})]),
        Message("3", "tool", "ok", tool_call_id="a", tool_name="read"),
        Message("4", "tool", "bad", tool_call_id="b", tool_name="glob", is_error=True),
        Message("5", "user", "<system-reminder>note</system-reminder>", synthetic=True),
    ]
    contents = m._contents(msgs)
    assert len(contents) == 4  # user, model, tool responses, reminder
    assert [p.function_response.response for p in contents[2].parts] == [{"output": "ok"}, {"error": "bad"}]
    assert len(contents[1].parts) == 2


def test_consecutive_user_messages_are_merged_and_empty_ones_skipped():
    contents = model()._contents([Message("1", "user", "a"), Message("2", "user", "b"), Message("3", "user", "  ")])
    assert len(contents) == 1 and [p.text for p in contents[0].parts] == ["a", "b"]


def test_tool_schema_goes_through_unchanged():
    from coding_harness.tools import builtin_tools

    decls = model()._tools([t.spec() for t in builtin_tools()])[0].function_declarations
    names = {d.name for d in decls}
    assert {"read", "edit", "shell", "subagent", "patch"} <= names
    assert next(d for d in decls if d.name == "edit").parameters_json_schema["required"] == ["path", "oldString", "newString"]


def test_error_classification():
    assert classify(Boom(429, "Quota exceeded. Please retry in 34.5s")).kind == "rate_limit"
    assert classify(Boom(429, "Quota exceeded. Please retry in 34.5s")).retry_after == 34.5
    assert classify(Boom(400, "The input token count exceeds the maximum number of tokens allowed")).kind == "overflow"
    assert classify(Boom(503, "overloaded")).kind == "transient"
    assert classify(Boom(401, "bad key")).kind == "auth"
    assert classify(Boom(404, "model not found")).kind == "fatal"
    assert classify(TimeoutError("slow")).kind == "transient"
