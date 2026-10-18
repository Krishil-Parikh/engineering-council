"""The stale-file guard: an edit made against text that has since changed is refused, and a re-read makes it work."""

import asyncio
import os
import time

import pytest

from harness.file_time import FileTime
from harness.tool.info import ToolError
from tests.harness.test_app import make
from tests.harness.test_runner import ScriptedLLM, text_reply, tool_reply


def touch_later(path, text):
    path.write_bytes(text.encode())
    later = time.time() + 5
    os.utime(path, (later, later))


def tool_results(h, session_id):
    from harness.schema import message as M

    out = []
    for m in h.sessions.messages(session_id):
        if isinstance(m, M.Assistant):
            for p in m.content:
                if isinstance(p, M.AssistantTool):
                    out.append((p.name, p.state.status, getattr(p.state, "error", None) and p.state.error.message if p.state.status == "error" else ""))
    return out


def test_an_edit_after_the_file_changed_underneath_is_refused_until_it_is_read_again(tmp_path):
    llm = ScriptedLLM(
        tool_reply(("read", {"path": "notes.txt"})), text_reply("read it"),
        tool_reply(("edit", {"path": "notes.txt", "oldString": "alpha", "newString": "ALPHA"})), text_reply("refused"),
        tool_reply(("read", {"path": "notes.txt"})), text_reply("read again"),
        tool_reply(("edit", {"path": "notes.txt", "oldString": "alpha", "newString": "ALPHA"})), text_reply("done"),
    )
    h, proj = make(tmp_path, llm)
    (proj / "notes.txt").write_bytes(b"alpha\n")

    async def main():
        first = await h.prompt("read the notes")
        touch_later(proj / "notes.txt", "alpha\nsomeone added a line\n")  # something else changed the file
        await h.prompt("now edit", first.session_id)
        results = tool_results(h, first.session_id)
        assert results[1][0:2] == ("edit", "error") and "has been modified since it was last read" in results[1][2]
        assert (proj / "notes.txt").read_bytes() == b"alpha\nsomeone added a line\n"  # untouched
        await h.prompt("read it again", first.session_id)
        await h.prompt("edit once more", first.session_id)
        assert tool_results(h, first.session_id)[-1][1] == "completed"
        assert (proj / "notes.txt").read_bytes() == b"ALPHA\nsomeone added a line\n"
        await h.close()

    asyncio.run(main())


def test_the_agents_own_edits_do_not_trip_the_guard(tmp_path):
    llm = ScriptedLLM(
        tool_reply(("read", {"path": "a.txt"})), text_reply("ok"),
        tool_reply(("edit", {"path": "a.txt", "oldString": "one", "newString": "two"})), text_reply("ok"),
        tool_reply(("edit", {"path": "a.txt", "oldString": "two", "newString": "three"})), text_reply("ok"),
        tool_reply(("write", {"path": "a.txt", "content": "four\n"})), text_reply("ok"),
    )
    h, proj = make(tmp_path, llm)
    (proj / "a.txt").write_bytes(b"one\n")

    async def main():
        first = await h.prompt("read")
        for text in ("edit", "edit again", "overwrite"):
            await h.prompt(text, first.session_id)
        assert [s for _, s, _ in tool_results(h, first.session_id)] == ["completed"] * 4
        assert (proj / "a.txt").read_bytes() == b"four\n"
        await h.close()

    asyncio.run(main())


def test_a_file_the_session_never_read_is_not_refused(tmp_path):
    llm = ScriptedLLM(tool_reply(("write", {"path": "b.txt", "content": "new\n"})), text_reply("ok"))
    h, proj = make(tmp_path, llm)
    (proj / "b.txt").write_bytes(b"old\n")

    async def main():
        run = await h.prompt("overwrite")
        assert tool_results(h, run.session_id)[0][1] == "completed" and (proj / "b.txt").read_bytes() == b"new\n"
        await h.close()

    asyncio.run(main())


def test_one_sessions_reads_do_not_count_for_another(tmp_path):
    ft = FileTime()
    f = tmp_path / "x.txt"
    f.write_bytes(b"a")
    ft.record("ses_1", str(f))
    touch_later(f, "b")
    ft.check("ses_2", str(f))  # never read by ses_2: fine
    with pytest.raises(ToolError, match="modified since it was last read"):
        ft.check("ses_1", str(f))
    ft.record("ses_1", str(f))
    ft.check("ses_1", str(f))
    ft.forget("ses_1")
    touch_later(f, "c")
    ft.check("ses_1", str(f))  # forgotten: no history, no complaint


def test_a_patch_is_guarded_the_same_way(tmp_path):
    patch = "*** Begin Patch\n*** Update File: p.txt\n@@\n-one\n+two\n*** End Patch"
    llm = ScriptedLLM(tool_reply(("read", {"path": "p.txt"})), text_reply("ok"), tool_reply(("patch", {"patchText": patch})), text_reply("refused"))
    h, proj = make(tmp_path, llm)
    from harness.tool.builtin import patch

    h.registry.add(patch.make(h.deps))  # not offered by default; a model that prefers patches gets it
    (proj / "p.txt").write_bytes(b"one\n")

    async def main():
        first = await h.prompt("read")
        touch_later(proj / "p.txt", "one\nextra\n")
        await h.prompt("patch", first.session_id)
        results = tool_results(h, first.session_id)
        assert results[1][1] == "error" and "modified since it was last read" in results[1][2] and (proj / "p.txt").read_bytes() == b"one\nextra\n"
        await h.close()

    asyncio.run(main())
