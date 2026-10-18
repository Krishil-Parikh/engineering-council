"""Exporting a session to JSON and importing it again, in the same database or another one."""

import asyncio

import pytest

from harness.db.database import Database
from harness.schema import message as M
from harness.session import portable as P
from harness.session.store import SessionStore
from tests.harness.test_app import make
from tests.harness.test_runner import ScriptedLLM, text_reply, tool_reply


def texts(store, session_id):
    return [(type(m).__name__, getattr(m, "text", None)) for _, m in store.messages(session_id)]


def a_session_with_a_child(tmp_path):
    llm = ScriptedLLM(tool_reply(("write", {"path": "a.txt", "content": "x\n"})), text_reply("wrote a"))
    h, proj = make(tmp_path, llm)
    return h


def test_a_session_round_trips_into_another_database(tmp_path):
    h = a_session_with_a_child(tmp_path)

    async def main():
        run = await h.prompt("make a.txt")
        child = h.sessions.create(parent_id=run.session_id, title="a subagent")
        h.store.add(child.id, M.User(text="child task"))
        data = P.loads(P.dumps(P.export_session(h.store, run.session_id)))
        assert [s["parent_id"] for s in data["sessions"]] == [None, run.session_id]
        other = SessionStore(Database(":memory:"))
        copy = P.import_session(other, data)
        assert copy.id == run.session_id  # nothing in the way, so the ids are kept
        assert texts(other, copy.id) == texts(h.store, run.session_id)
        assert [c.title for c in other.children(copy.id)] == ["a subagent"] and texts(other, other.children(copy.id)[0].id) == [("User", "child task")]
        assert copy.cost == h.store.get(run.session_id).cost
        await h.close()

    asyncio.run(main())


def test_importing_into_the_same_database_makes_a_separate_copy(tmp_path):
    h = a_session_with_a_child(tmp_path)

    async def main():
        run = await h.prompt("make a.txt")
        child = h.sessions.create(parent_id=run.session_id)
        h.store.add(child.id, M.User(text="child task"))
        data = P.export_session(h.store, run.session_id)
        copy = P.import_session(h.store, data, directory="/elsewhere")
        again = P.import_session(h.store, data)
        assert len({run.session_id, copy.id, again.id}) == 3
        assert copy.directory == "/elsewhere" and texts(h.store, copy.id) == texts(h.store, run.session_id)
        assert {m.id for _, m in h.store.messages(copy.id)}.isdisjoint({m.id for _, m in h.store.messages(run.session_id)})
        (copy_child,) = h.store.children(copy.id)  # the copy has its own subagent session, not the original's
        assert copy_child.id != child.id and texts(h.store, copy_child.id) == [("User", "child task")]
        assert len(h.store.children(run.session_id)) == 1
        await h.close()

    asyncio.run(main())


def test_references_to_subagent_sessions_follow_the_copy(tmp_path):
    h = a_session_with_a_child(tmp_path)

    async def main():
        run = await h.prompt("make a.txt")
        child = h.sessions.create(parent_id=run.session_id)
        h.store.update(run.session_id, metadata={"lastChild": child.id})
        copy = P.import_session(h.store, P.export_session(h.store, run.session_id))
        (copy_child,) = h.store.children(copy.id)
        assert h.store.get(copy.id).metadata == {"lastChild": copy_child.id}
        await h.close()

    asyncio.run(main())


def test_children_can_be_left_out(tmp_path):
    h = a_session_with_a_child(tmp_path)

    async def main():
        run = await h.prompt("make a.txt")
        h.sessions.create(parent_id=run.session_id)
        assert len(P.export_session(h.store, run.session_id, include_children=False)["sessions"]) == 1
        await h.close()

    asyncio.run(main())


def test_a_bad_export_is_refused_with_a_clear_message(tmp_path):
    store = SessionStore(Database(":memory:"))
    for bad in ({}, {"version": 99, "sessions": [{}]}, {"version": 1, "sessions": []}, [1, 2]):
        with pytest.raises(P.ImportError_, match="not a session export"):
            P.import_session(store, bad)
    with pytest.raises(P.ImportError_, match="not valid JSON"):
        P.loads("{nope")
    with pytest.raises(KeyError):
        P.export_session(store, "ses_missing")


def test_a_transcript_reads_as_a_conversation(tmp_path):
    h = a_session_with_a_child(tmp_path)

    async def main():
        run = await h.prompt("make a.txt")
        h.store.update(run.session_id, title="Make a file")
        text = P.to_markdown(h.store, run.session_id)
        assert text.startswith("# Make a file") and "## You\n\nmake a.txt" in text and "tool `write`" in text and "wrote a" in text
        await h.close()

    asyncio.run(main())
