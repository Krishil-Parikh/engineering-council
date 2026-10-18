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
