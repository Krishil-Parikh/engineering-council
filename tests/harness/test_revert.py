"""Rewinding a session: files go back, nothing is lost until the revert is committed, and new input makes it final."""

import asyncio
import os
import subprocess

import pytest

from harness.app import Harness
from harness.schema import message as M
from harness.session.revert import RevertError, SessionRevert
from tests.harness.test_runner import ScriptedLLM, text_reply, tool_reply

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, **ENV})


def repo_harness(tmp_path, llm):
    proj = tmp_path / "proj"
    proj.mkdir()
    git(proj, "init", "-q", "-b", "main")
    (proj / "base.txt").write_bytes(b"base\n")
    git(proj, "add", "-A")
    git(proj, "commit", "-q", "-m", "init")
    return Harness(proj, llm=llm, data_root=tmp_path / "data", home=tmp_path / "home", db_path=":memory:", snapshots=True), proj


def user_ids(h, session_id):
    return [m.id for m in h.sessions.messages(session_id) if isinstance(m, M.User)]


def two_turns(tmp_path):
    llm = ScriptedLLM(
        tool_reply(("write", {"path": "a.txt", "content": "alpha\n"})), text_reply("wrote a"),
        tool_reply(("write", {"path": "b.txt", "content": "beta\n"})), text_reply("wrote b"),
    )
    return repo_harness(tmp_path, llm)


async def run_two_turns(h):
    first = await h.prompt("make a.txt")
    await h.prompt("make b.txt", first.session_id)
    return first.session_id


def test_rewinding_to_a_message_puts_the_files_back_and_keeps_the_conversation_until_committed(tmp_path):
    h, proj = two_turns(tmp_path)

    async def main():
        sid = await run_two_turns(h)
        ids = user_ids(h, sid)
        assert (proj / "a.txt").exists() and (proj / "b.txt").exists()
        state = h.revert.stage(sid, ids[1])  # rewind the second turn only
        assert not (proj / "b.txt").exists() and (proj / "a.txt").read_bytes() == b"alpha\n" and state.files == ["b.txt"]
        assert [d["file"] for d in state.diff] == ["b.txt"] and state.diff[0]["additions"] == 1
        assert len(user_ids(h, sid)) == 2 and h.store.get(sid).revert["message_id"] == ids[1]  # nothing deleted yet
        h.revert.unstage(sid)
        assert (proj / "b.txt").read_bytes() == b"beta\n" and h.store.get(sid).revert is None
        await h.close()

    asyncio.run(main())


def test_rewinding_further_back_starts_from_the_real_state(tmp_path):
    h, proj = two_turns(tmp_path)

    async def main():
        sid = await run_two_turns(h)
        ids = user_ids(h, sid)
        h.revert.stage(sid, ids[1])
        assert not (proj / "b.txt").exists() and (proj / "a.txt").exists()
        state = h.revert.stage(sid, ids[0])  # now both turns
        assert not (proj / "a.txt").exists() and not (proj / "b.txt").exists() and sorted(state.files) == ["a.txt", "b.txt"]
        h.revert.unstage(sid)
        assert (proj / "a.txt").exists() and (proj / "b.txt").exists()  # everything is back
        await h.close()

    asyncio.run(main())


def test_committing_deletes_the_rewound_conversation(tmp_path):
    h, proj = two_turns(tmp_path)

    async def main():
        sid = await run_two_turns(h)
        ids = user_ids(h, sid)
        h.revert.stage(sid, ids[1])
        h.revert.commit(sid)
        assert user_ids(h, sid) == [ids[0]] and h.store.get(sid).revert is None
        assert not any("make b.txt" in str(m) for m in h.sessions.messages(sid))
        assert not (proj / "b.txt").exists()
        await h.close()

    asyncio.run(main())


def test_new_input_to_a_rewound_session_makes_the_rewind_final_first(tmp_path):
    llm = ScriptedLLM(
        tool_reply(("write", {"path": "a.txt", "content": "alpha\n"})), text_reply("wrote a"),
        tool_reply(("write", {"path": "b.txt", "content": "beta\n"})), text_reply("wrote b"),
        text_reply("fine, something else"),
    )
    h, proj = repo_harness(tmp_path, llm)

    async def main():
        sid = await run_two_turns(h)
        ids = user_ids(h, sid)
        h.revert.stage(sid, ids[1])
        result = await h.prompt("never mind, do something else", sid)
        assert result.text == "fine, something else" and h.store.get(sid).revert is None
        texts = [m.text for m in h.sessions.messages(sid) if isinstance(m, M.User)]
        assert texts == ["make a.txt", "never mind, do something else"]  # the rewound turn is gone, as far as the model is concerned
        sent = str(llm.requests[-1].messages)
        assert "make b.txt" not in sent and "wrote b" not in sent
        await h.close()

    asyncio.run(main())


def test_only_a_message_you_sent_can_be_a_rewind_point_and_a_busy_session_cannot_be_rewound(tmp_path):
    h, proj = two_turns(tmp_path)

    async def main():
        sid = await run_two_turns(h)
        assistant = next(m for m in h.sessions.messages(sid) if isinstance(m, M.Assistant))
        with pytest.raises(RevertError, match="message you sent"):
            h.revert.stage(sid, assistant.id)
        with pytest.raises(RevertError, match="not found"):
            h.revert.stage(sid, "msg_nope")
        busy = SessionRevert(h.store, h.snapshots, lambda s: True)
        with pytest.raises(RevertError, match="busy"):
            busy.stage(sid, user_ids(h, sid)[0])
        assert h.revert.unstage(sid) is None and h.revert.commit(sid) is None  # nothing staged: nothing to do
        await h.close()

    asyncio.run(main())


def test_the_points_you_can_rewind_to_say_what_rewinding_would_undo(tmp_path):
    h, proj = two_turns(tmp_path)

    async def main():
        sid = await run_two_turns(h)
        points = h.revert.points(sid)
        assert [p["text"] for p in points] == ["make a.txt", "make b.txt"]
        assert points[0]["files"] == ["a.txt", "b.txt"] and points[1]["files"] == ["b.txt"]
        await h.close()

    asyncio.run(main())


def test_without_snapshots_a_rewind_still_trims_the_conversation(tmp_path):
    llm = ScriptedLLM(text_reply("one"), text_reply("two"))
    proj = tmp_path / "plain"
    proj.mkdir()
    h = Harness(proj, llm=llm, data_root=tmp_path / "d", home=tmp_path / "home", db_path=":memory:", snapshots=False)

    async def main():
        first = await h.prompt("first")
        await h.prompt("second", first.session_id)
        ids = user_ids(h, first.session_id)
        state = h.revert.stage(first.session_id, ids[1])
        assert state.files == [] and state.snapshot is None
        h.revert.commit(first.session_id)
        assert user_ids(h, first.session_id) == [ids[0]]
        await h.close()

    asyncio.run(main())


def test_events_report_what_happened(tmp_path):
    events = []
    llm = ScriptedLLM(tool_reply(("write", {"path": "a.txt", "content": "alpha\n"})), text_reply("wrote a"))
    h, proj = repo_harness(tmp_path, llm)
    h.on_event = lambda kind, data: events.append(kind)

    async def main():
        first = await h.prompt("make a.txt")
        mid = user_ids(h, first.session_id)[0]
        h.revert.stage(first.session_id, mid)
        h.revert.unstage(first.session_id)
        h.revert.stage(first.session_id, mid)
        h.revert.commit(first.session_id)
        assert [e for e in events if e.startswith("session.")] == ["session.reverted", "session.unreverted", "session.reverted", "session.revert.committed"]
        await h.close()

    asyncio.run(main())
