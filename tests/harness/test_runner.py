import asyncio
import json
import subprocess

import pytest

from coding_harness.agents import Agent, developer_agent
from coding_harness.config import HarnessConfig
from coding_harness.permission import Rule
from coding_harness.runner import HarnessError, Runner
from coding_harness.session import Session
from coding_harness.types import Message, ModelError, ModelReply
from tests.harness.conftest import ScriptedModel, call, calls, make_runner, run


def go(runner, text, agent="build", session=None):
    s = session or runner.new_session(agent)
    return s, run(runner.run(s, text, agent))


def test_loop_reads_edits_and_answers(ws):
    (ws.cwd / "app.py").write_text("x = 1\n")
    model = ScriptedModel(
        calls(call("read", path="app.py")),
        calls(call("edit", path="app.py", oldString="x = 1", newString="x = 2")),
        "Changed x to 2.",
    )
    runner = make_runner(ws, model)
    session, res = go(runner, "set x to 2")
    assert (ws.cwd / "app.py").read_text() == "x = 2\n"
    assert res.text == "Changed x to 2." and res.steps == 3 and res.stopped == "completed"
    roles = [m.role for m in session.messages]
    assert roles == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    # the model saw tool results and a system prompt that describes the environment
    assert "Working directory" in model.calls[0]["system"] and "read" in model.calls[0]["tools"]
    assert any(m.role == "tool" and "1: x = 1" in m.text for m in model.calls[1]["messages"])


def test_parallel_tool_calls_all_get_results_in_order(ws):
    (ws.cwd / "a.txt").write_text("A")
    (ws.cwd / "b.txt").write_text("B")
    model = ScriptedModel(calls(call("read", path="a.txt"), call("read", path="b.txt")), "ok")
    runner = make_runner(ws, model)
    session, _ = go(runner, "read both")
    tool_msgs = [m for m in session.messages if m.role == "tool"]
    assert "A" in tool_msgs[0].text and "B" in tool_msgs[1].text


def test_unknown_tool_and_tool_errors_are_returned_to_the_model_not_raised(ws):
    model = ScriptedModel(calls(call("nonexistent"), call("read", path="missing.txt")), "recovered")
    runner = make_runner(ws, model)
    session, res = go(runner, "x")
    errs = [m for m in session.messages if m.role == "tool"]
    assert all(m.is_error for m in errs) and "Unknown tool" in errs[0].text and "File not found" in errs[1].text
    assert res.text == "recovered"


def test_step_limit_forces_a_text_only_wrap_up(ws):
    agent = Agent("tiny", "Tiny", steps=2)
    model = ScriptedModel(
        calls(call("glob", pattern="*")), calls(call("glob", pattern="**")), calls(call("glob", pattern="*.x")), "I ran out of steps; here is where I am.",
    )
    runner = make_runner(ws, model, agents={"tiny": agent})
    session, res = go(runner, "keep going", agent="tiny")
    assert res.stopped == "max_steps"
    last = model.calls[-1]
    assert last["tool_choice"] == "none" and last["tools"] == [] and "MAXIMUM STEPS" in last["messages"][-1].text


def test_identical_calls_are_stopped(ws):
    same = [calls(call("glob", pattern="*.nothing")) for _ in range(12)]
    model = ScriptedModel(*same)
    runner = make_runner(ws, model)
    session, res = go(runner, "loop")
    assert res.stopped == "repeated_calls"
    assert any("identical" in m.text for m in session.messages if m.role == "tool")
    assert len(model.calls) < 12  # it did not run to exhaustion


def test_rate_limits_and_transient_errors_are_retried(ws):
    model = ScriptedModel(ModelError("429", "rate_limit", retry_after=3), ModelError("boom", "transient"), "finally")
    runner = make_runner(ws, model)
    events = []
    runner.observer = events.append
    session, res = go(runner, "hi")
    assert res.text == "finally" and [e.kind for e in events].count("retry") == 2


def test_auth_error_stops_with_a_clear_message(ws):
    runner = make_runner(ws, ScriptedModel(ModelError("bad key", "auth")))
    with pytest.raises(HarnessError, match="auth"):
        go(runner, "hi")


def test_empty_reply_is_nudged(ws):
    model = ScriptedModel(ModelReply(""), "now I answer")
    runner = make_runner(ws, model)
    _, res = go(runner, "hi")
    assert res.text == "now I answer"
    assert any("empty" in m.text for m in model.calls[1]["messages"] if m.synthetic)


def test_output_limit_asks_the_model_to_continue_in_pieces(ws):
    model = ScriptedModel(ModelReply("part one", finish="length"), "part two")
    runner = make_runner(ws, model)
    session, res = go(runner, "write a lot")
    assert "cut off" in model.calls[1]["messages"][-1].text and "part one" in res.text and "part two" in res.text


def test_sessions_persist_and_resume(ws):
    runner = make_runner(ws, ScriptedModel("first answer"))
    s, _ = go(runner, "remember 42")
    again = Session.load(ws, s.id)
    assert [m.text for m in again.messages if m.role in ("user", "assistant")] == ["remember 42", "first answer"]
    model2 = ScriptedModel("second")
    r2 = make_runner(ws, model2)
    r2.resume_session(s.id)
    run(r2.run(r2.sessions[s.id], "what number?"))
    assert any("remember 42" in m.text for m in model2.calls[0]["messages"])


def test_interrupted_tool_calls_are_closed_on_resume(ws):
    runner = make_runner(ws, ScriptedModel("ok"))
    s = runner.new_session("build")
    s.add(Message("m1", "user", "go"))
    s.add(Message("m2", "assistant", "", [call("glob", pattern="*")]))  # the process died before the result was stored
    run(runner.run(s, "continue"))
    assert any(m.role == "tool" and "interrupted" in m.text for m in s.messages)


# ---- memory: instruction files


def test_agents_md_is_in_the_system_prompt_and_nearby_files_load_on_read(ws):
    (ws.cwd / "AGENTS.md").write_text("Always run `make check` before finishing.")
    (ws.cwd / "sub").mkdir()
    (ws.cwd / "sub" / "AGENTS.md").write_text("In sub/, never touch generated.py.")
    (ws.cwd / "sub" / "code.py").write_text("print(1)\n")
    model = ScriptedModel(calls(call("read", path="sub/code.py")), "done")
    runner = make_runner(ws, model)
    go(runner, "look")
    assert "make check" in model.calls[0]["system"]
    assert any("never touch generated.py" in m.text for m in model.calls[1]["messages"] if m.role == "tool")


def test_changed_instruction_file_is_announced_mid_session(ws):
    f = ws.cwd / "AGENTS.md"
    f.write_text("v1 rules")
    model = ScriptedModel("a", "b")
    runner = make_runner(ws, model)
    s, _ = go(runner, "first")
    f.write_text("v2 rules")
    run(runner.run(s, "second"))
    assert any("v2 rules" in m.text and "Updated instructions" in m.text for m in model.calls[1]["messages"])


def test_skill_is_listed_and_loadable(ws):
    d = ws.cwd / ".claude" / "skills" / "mermaid"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: mermaid\ndescription: Draw valid diagrams\n---\nUse flowchart TD.\n")
    model = ScriptedModel(calls(call("skill", id="mermaid")), "ok")
    runner = make_runner(ws, model)
    go(runner, "diagram")
    assert "mermaid" in model.calls[0]["system"]
    assert any("Use flowchart TD." in m.text for m in model.calls[1]["messages"] if m.role == "tool")


# ---- memory: compaction


def test_long_conversations_are_compacted_into_a_checkpoint(ws):
    cfg = HarnessConfig(context_window=20_000, compaction_keep=2_000)
    summary = "## Objective\n- build it\n\n## Next Move\n1. finish"
    big = "x" * 30_000

    def respond(messages):
        if messages and messages[0].id == "compact_prompt":
            return summary
        return "ok"

    model = ScriptedModel(*[respond] * 12)
    runner = make_runner(ws, model, config=cfg)
    s = runner.new_session("build")
    for i in range(6):
        s.add(Message(s.next_message_id(), "user", f"request {i} " + big))
        s.add(Message(s.next_message_id(), "assistant", f"answer {i}"))
    run(runner.run(s, "and now?"))
    assert any(m.kind == "summary" for m in s.messages)
    assert sum(1 for m in s.messages if m.compacted) >= 2
    sent = model.calls[-1]["messages"]
    assert any("conversation-checkpoint" in m.text for m in sent) and not any(m.text.startswith("request 0") for m in sent)
    # the full history is still on disk
    assert len(Session.load(ws, s.id).messages) == len(s.messages)


def test_context_overflow_triggers_compaction_and_retry(ws):
    cfg = HarnessConfig(context_window=1_000_000, compaction_keep=500)
    seen = {"n": 0}

    def respond(messages):
        if messages and messages[0].id == "compact_prompt":
            return "## Objective\n- x"
        seen["n"] += 1
        return "answer"

    model = ScriptedModel(ModelError("too long", "overflow"), respond, respond, respond)
    runner = make_runner(ws, model, config=cfg)
    s = runner.new_session("build")
    for i in range(4):
        s.add(Message(s.next_message_id(), "user", f"q{i} " + "y" * 4000))
        s.add(Message(s.next_message_id(), "assistant", f"a{i}"))
    _, res = go(runner, "go", session=s)
    assert res.text == "answer" and any(m.kind == "summary" for m in s.messages)


def test_old_tool_output_is_pruned_first(ws):
    from coding_harness.compaction import CLEARED, Compactor

    s = Session(ws, "build")
    for i in range(8):
        s.add(Message(s.next_message_id(), "assistant", "", [call("read", path=f"f{i}")]))
        s.add(Message(s.next_message_id(), "tool", "z" * 80_000, tool_call_id=f"c{i}", tool_name="read"))
    comp = Compactor(ScriptedModel(), window=100_000)
    assert comp.prune(s) > 0
    texts = [m.text for m in s.messages if m.role == "tool"]
    assert texts[0] == CLEARED and texts[-1] != CLEARED


# ---- subagents, background work, undo


def test_subagent_runs_in_its_own_session_and_cannot_edit(ws):
    (ws.cwd / "notes.md").write_text("the answer is 42\n")

    def main_then(messages):
        return calls(call("subagent", agent="explore", description="find answer", prompt="what is the answer in notes.md?"))

    model = ScriptedModel(
        main_then,
        calls(call("grep", pattern="answer")),  # explore agent
        "It is 42 (notes.md:1).",               # explore final text
        lambda ms: "The explorer says 42.",     # main final
    )
    runner = make_runner(ws, model)
    s, res = go(runner, "ask explorer")
    assert res.text.endswith("The explorer says 42.")
    child = [x for x in runner.sessions.values() if x.parent_id == s.id]
    assert len(child) == 1 and child[0].agent == "explore"
    explore_call = model.calls[1]
    assert "edit" not in explore_call["tools"] and "write" not in explore_call["tools"] and "subagent" not in explore_call["tools"]
    assert any("sessionID" in m.text for m in s.messages if m.role == "tool")


def test_plan_agent_cannot_write_but_can_run_readonly_git(ws):
    model = ScriptedModel(calls(call("write", path="x.txt", content="no"), call("shell", command="git status")), "planned")
    runner = make_runner(ws, model)
    subprocess.run(["git", "init", "-q"], cwd=ws.cwd, check=True)
    s, _ = go(runner, "plan it", agent="plan")
    assert not (ws.cwd / "x.txt").exists()
    assert "write" not in model.calls[0]["tools"] and "shell" in model.calls[0]["tools"]
    results = [m for m in s.messages if m.role == "tool"]
    assert results[0].is_error and "Unknown tool" in results[0].text and not results[1].is_error


def test_background_shell_resumes_the_agent_with_the_result(ws):
    model = ScriptedModel(
        calls(call("shell", command="echo build-finished", background=True)),
        "Started it; nothing else to do.",
        lambda ms: "The build said build-finished.",
    )
    runner = make_runner(ws, model)
    s, res = go(runner, "build in background")
    assert "build-finished" in model.calls[2]["messages"][-1].text and res.text.endswith("The build said build-finished.")


def test_undo_restores_files_and_conversation(ws):
    (ws.cwd / "keep.txt").write_text("original")
    model = ScriptedModel(
        calls(call("read", path="keep.txt")),
        calls(call("edit", path="keep.txt", oldString="original", newString="changed"), call("write", path="new.txt", content="made")),
        "edited",
    )
    runner = make_runner(ws, model)
    s, _ = go(runner, "change things")
    assert (ws.cwd / "keep.txt").read_text() == "changed" and (ws.cwd / "new.txt").exists()
    touched = runner.undo(s)
    assert (ws.cwd / "keep.txt").read_text() == "original" and not (ws.cwd / "new.txt").exists()
    assert set(touched) == {"keep.txt", "new.txt"} and s.messages == []


def test_developer_agent_wears_its_skill_lens(ws):
    dev = developer_agent("DEV_3", "Backend", "APIs and data integrity", "What happens on retry?")
    model = ScriptedModel("built")
    runner = make_runner(ws, model, agents={dev.id: dev})
    go(runner, "build the api", agent=dev.id)
    assert "DEV_3" in model.calls[0]["system"] and "APIs and data integrity" in model.calls[0]["system"]
    assert "question" not in model.calls[0]["tools"]


def test_user_rules_in_config_override_defaults(ws):
    cfg = HarnessConfig(rules=[Rule("shell", "echo *", "deny")])
    model = ScriptedModel(calls(call("shell", command="echo hi")), "ok")
    runner = make_runner(ws, model, config=cfg)
    s, _ = go(runner, "x")
    assert any(m.role == "tool" and m.is_error and "denied" in m.text for m in s.messages)
