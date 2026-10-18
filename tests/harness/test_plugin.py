"""Hooks and plugins: extra behaviour at fixed points, loaded from files, never able to break a run."""

import asyncio
import json

import pytest

from harness.plugin import Hooks
from harness.schema import message as M
from tests.harness.test_app import make
from tests.harness.test_runner import ScriptedLLM, text_reply, tool_reply

PLUGIN = '''
seen = []

def plugin(api):
    def before(event):
        if event["tool"] == "write":
            event["input"] = {**event["input"], "content": event["input"]["content"].upper()}

    def after(event):
        seen.append((event["tool"], event["status"]))

    api.hooks.add("tool.before", before)
    api.hooks.add("tool.after", after)
    api.hooks.add("context", lambda event: event["messages"].append(__import__("harness.ai.types", fromlist=["x"]).Message.user("PLUGIN WAS HERE")))
'''


def with_plugin(tmp_path, llm, plugin=PLUGIN, **kw):
    home = tmp_path / "home"
    proj = home / "proj"
    proj.mkdir(parents=True)
    (proj / "plug.py").write_text(plugin, encoding="utf-8")
    (proj / "harness.json").write_text(json.dumps({"plugins": ["plug.py"]}), encoding="utf-8")
    from harness.app import Harness

    return Harness(proj, llm=llm, data_root=tmp_path / "d", home=home, db_path=":memory:", snapshots=False, **kw), proj


def test_a_plugin_named_in_configuration_can_change_tool_input_and_the_request(tmp_path):
    llm = ScriptedLLM(tool_reply(("write", {"path": "a.txt", "content": "quiet\n"})), text_reply("done"))
    h, proj = with_plugin(tmp_path, llm)

    async def main():
        assert [p.name for p in h.plugins.loaded] == ["plug.py"] and h.plugins.errors == []
        await h.prompt("write a file")
        assert (proj / "a.txt").read_text() == "QUIET\n"  # the before-hook shouted
        assert "PLUGIN WAS HERE" in str(llm.requests[0].messages)  # the context hook saw the request
        await h.close()

    asyncio.run(main())


def test_plugin_files_in_the_plugins_folder_are_found_too(tmp_path):
    home = tmp_path / "home"
    proj = home / "proj"
    (proj / ".harness" / "plugins").mkdir(parents=True)
    (proj / ".harness" / "plugins" / "loud.py").write_text("def plugin(api):\n    api.hooks.add('event', lambda kind, data: None)\n", encoding="utf-8")
    from harness.app import Harness

    h = Harness(proj, llm=ScriptedLLM(), data_root=tmp_path / "d", home=home, db_path=":memory:", snapshots=False)
    assert [p.name for p in h.plugins.loaded] == ["loud.py"] and h.hooks.count("event") == 1


def test_a_plugin_can_add_a_tool(tmp_path):
    plugin = '''
from pydantic import BaseModel
from harness.tool.info import ToolInfo, ToolResult

class In(BaseModel):
    word: str

async def run(inp, ctx):
    return ToolResult(content=inp.word[::-1])

def plugin(api):
    api.add_tool(ToolInfo("reverse", "Reverses a word", In, run))
'''
    llm = ScriptedLLM(tool_reply(("reverse", {"word": "stressed"})), text_reply("desserts"))
    h, _ = with_plugin(tmp_path, llm, plugin)

    async def main():
        result = await h.prompt("reverse stressed")
        assert result.text == "desserts" and any("desserts" in str(m) for m in llm.requests[1].messages)
        assert [t.name for t in llm.requests[0].tools].count("reverse") == 1
        await h.close()

    asyncio.run(main())


def test_a_broken_plugin_is_reported_and_the_rest_still_work(tmp_path):
    h, proj = with_plugin(tmp_path, ScriptedLLM(), "def plugin(api):\n    raise RuntimeError('boom')\n")
    assert h.plugins.loaded == [] and "boom" in h.plugins.errors[0]
    h2, _ = with_plugin(tmp_path / "x", ScriptedLLM(), "this is not python(")
    assert "plug.py was not loaded" in h2.plugins.errors[0]
    h3, _ = with_plugin(tmp_path / "y", ScriptedLLM(), "x = 1\n")
    assert "no plugin(api) function" in h3.plugins.errors[0]


def test_a_hook_that_raises_never_breaks_the_run(tmp_path):
    seen = []
    h, proj = make(tmp_path, ScriptedLLM(tool_reply(("write", {"path": "a.txt", "content": "x\n"})), text_reply("done")), on_event=lambda k, d: seen.append((k, d)))

    def bad(event):
        raise ValueError("hook bug")

    h.hooks.add("tool.after", bad)

    async def main():
        result = await h.prompt("go")
        assert result.outcome == "succeeded" and (proj / "a.txt").exists()
        errors = [d for k, d in seen if k == "plugin.error"]
        assert errors and errors[0]["hook"] == "tool.after" and "hook bug" in errors[0]["message"]
        await h.close()

    asyncio.run(main())


def test_event_hooks_see_everything_the_harness_reports(tmp_path):
    kinds = []
    h, proj = make(tmp_path, ScriptedLLM(text_reply("hi")))
    h.hooks.add("event", lambda kind, data: kinds.append(kind))

    async def main():
        await h.prompt("hello")
        assert kinds and any(k.startswith("message") or k.startswith("session") or "step" in k or "text" in k for k in kinds)
        await h.close()

    asyncio.run(main())


def test_unknown_hook_names_are_refused():
    with pytest.raises(ValueError, match="unknown hook"):
        Hooks().add("tool.sideways", lambda e: None)


def test_the_plan_agent_gets_its_reminder_through_the_hook_host(tmp_path):
    llm = ScriptedLLM(text_reply("here is a plan"))
    h, proj = make(tmp_path, llm)

    async def main():
        await h.prompt("plan the work", agent="plan")
        sent = str(llm.requests[0].messages)
        assert "Plan mode" in sent or "plan mode" in sent
        await h.close()

    asyncio.run(main())


def test_the_team_engine_does_not_load_project_plugins(tmp_path):
    h, proj = with_plugin(tmp_path, ScriptedLLM(), plugins=False)
    assert h.plugins.loaded == [] and h.plugins.errors == []


# ---------------------------------------------------------------------------------------------- overriding and disabling tools


def test_a_plugin_can_override_a_built_in_tool(tmp_path):
    plugin = '''
from pydantic import BaseModel
from harness.tool.info import ToolInfo, ToolResult

class In(BaseModel):
    path: str

async def run(inp, ctx):
    return ToolResult(content="OVERRIDDEN read of " + inp.path)

def plugin(api):
    assert api.override_tool(ToolInfo("read", "A better read", In, run))
    assert not api.override_tool(ToolInfo("nothing_like_it", "x", In, run))
'''
    llm = ScriptedLLM(tool_reply(("read", {"path": "x.txt"})), text_reply("ok"))
    h, _ = with_plugin(tmp_path, llm, plugin)

    async def main():
        await h.prompt("read x")
        assert "OVERRIDDEN read of x.txt" in str(llm.requests[1].messages)
        assert [t.name for t in llm.requests[0].tools].count("read") == 1
        assert h.registry.errors and "does not exist" in h.registry.errors[-1]
        await h.close()

    asyncio.run(main())


def test_a_disabled_tool_is_hidden_from_the_model_and_can_be_brought_back(tmp_path):
    llm = ScriptedLLM(text_reply("one"), text_reply("two"))
    h, _ = make(tmp_path, llm)
    h.registry.disable("shell")

    async def main():
        await h.prompt("first")
        assert "shell" not in [t.name for t in llm.requests[0].tools] and "read" in [t.name for t in llm.requests[0].tools]
        h.registry.enable("shell")
        await h.prompt("second")
        assert "shell" in [t.name for t in llm.requests[1].tools]
        await h.close()

    asyncio.run(main())


def test_configuration_can_switch_tools_off(tmp_path):
    home = tmp_path / "home"
    proj = home / "proj"
    proj.mkdir(parents=True)
    (proj / "harness.json").write_text(json.dumps({"disabled_tools": ["shell", "write"]}), encoding="utf-8")
    from harness.app import Harness

    llm = ScriptedLLM(text_reply("ok"))
    h = Harness(proj, llm=llm, data_root=tmp_path / "d", home=home, db_path=":memory:", snapshots=False)

    async def main():
        await h.prompt("hi")
        names = [t.name for t in llm.requests[0].tools]
        assert "shell" not in names and "write" not in names and "edit" in names
        await h.close()

    asyncio.run(main())


# ---------------------------------------------------------------------------------------------- compaction


def a_long_session(h):
    from harness.schema import message as M

    sid = h.new_session().id
    for i in range(3):
        h.store.add(sid, M.User(text=f"question {i} " + "padding " * 50))
        a = M.Assistant(agent="build", model=M.ModelRef(provider_id="google", id=h.model_id), content=[M.AssistantText(text=f"answer {i} " + "padding " * 50)], finish="stop")
        a.time.completed = M.now_ms()
        h.store.add(sid, a)
    return sid


def test_compaction_reports_what_it_does_as_events(tmp_path):
    from harness.session import compaction as C
    from tests.harness.conftest import SUMMARY

    seen = []
    h, _ = make(tmp_path, ScriptedLLM(SUMMARY), compaction=C.Settings(keep=1), on_event=lambda k, d: seen.append(k))
    sid = a_long_session(h)

    async def main():
        await h.sessions.compact(sid)
        assert [k for k in seen if k in ("compaction.started", "compaction.ended", "compaction.failed")] == ["compaction.started", "compaction.ended"]
        assert "compaction.delta" in seen  # and the summary is reported as it streams in
        await h.close()

    asyncio.run(main())


def test_a_failed_compaction_is_reported_too(tmp_path):
    from harness.session import compaction as C

    seen = []
    h, _ = make(tmp_path, ScriptedLLM("not a summary at all", "still not a summary"), compaction=C.Settings(keep=1), on_event=lambda k, d: seen.append((k, d)))
    sid = a_long_session(h)

    async def main():
        await h.sessions.compact(sid)
        failed = [d for k, d in seen if k == "compaction.failed"]
        assert failed and "template" in failed[0]["error"]
        await h.close()

    asyncio.run(main())


def test_a_plugin_can_write_the_summary_itself_and_no_model_is_asked(tmp_path):
    from harness.session import compaction as C

    llm = ScriptedLLM()
    h, _ = make(tmp_path, llm, compaction=C.Settings(keep=1))
    h.hooks.add("compaction.summary", lambda context, request: {"summary": "## Objective\n- written by a plugin\n\n## Next Move\n1. go on"})
    sid = a_long_session(h)

    async def main():
        await h.sessions.compact(sid)
        assert llm.requests == []
        from harness.schema import message as M

        done = [m for m in h.sessions.messages(sid) if getattr(m, "type", "") == "compaction"]
        assert done and "written by a plugin" in done[-1].summary
        await h.close()

    asyncio.run(main())


def test_the_request_hook_sees_the_summary_request_and_may_change_it(tmp_path):
    from harness.session import compaction as C
    from tests.harness.conftest import SUMMARY

    llm = ScriptedLLM(SUMMARY)
    h, _ = make(tmp_path, llm, compaction=C.Settings(keep=1))
    seen = []

    def hook(request):
        seen.append(len(request.messages))
        from harness.ai import types as T

        return request.update(messages=[*request.messages, T.Message.user("PLEASE BE BRIEF")])

    h.hooks.add("compaction.request", hook)
    sid = a_long_session(h)

    async def main():
        await h.sessions.compact(sid)
        assert seen and "PLEASE BE BRIEF" in str(llm.requests[0].messages)
        await h.close()

    asyncio.run(main())


def test_a_separate_model_can_write_the_summaries(tmp_path):
    from harness.session import compaction as C
    from tests.harness.conftest import SUMMARY

    main_llm, small_llm = ScriptedLLM(text_reply("unused")), ScriptedLLM(SUMMARY)
    h, _ = make(tmp_path, main_llm, compaction=C.Settings(keep=1), compaction_llm=small_llm)
    sid = a_long_session(h)

    async def main():
        await h.sessions.compact(sid)
        assert len(small_llm.requests) == 1 and main_llm.requests == []
        await h.close()

    asyncio.run(main())
