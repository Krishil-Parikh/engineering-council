"""Session statistics: counts, cost, tokens, tools and models, for one session with its subagents or for all of them."""

import asyncio

from harness.schema import message as M
from harness.session import stats as S
from tests.harness.test_app import make
from tests.harness.test_runner import ScriptedLLM, text_reply, tool_reply


def test_a_sessions_numbers_come_from_its_messages(tmp_path):
    llm = ScriptedLLM(
        tool_reply(("write", {"path": "a.txt", "content": "x\n"})), text_reply("wrote a"),
        tool_reply(("read", {"path": "missing.txt"})), text_reply("it was not there"),
    )
    h, proj = make(tmp_path, llm)

    async def main():
        first = await h.prompt("make a.txt")
        await h.prompt("read a missing file", first.session_id)
        s = S.collect(h.store, first.session_id)
        assert (s.sessions, s.user_messages, s.assistant_messages) == (1, 2, 4)
        assert s.tools["write"].calls == 1 and s.tools["write"].failures == 0
        assert s.tools["read"].calls == 1 and s.tools["read"].failures == 1
        assert s.messages == 6 and sum(m.messages for m in s.models.values()) == 4
        text = S.render(s)
        assert "Sessions   1" in text and "write: 1 call(s)" in text and "read: 1 call(s), 1 failed" in text
        await h.close()

    asyncio.run(main())


def test_totals_add_up_across_sessions_and_include_subagents(tmp_path):
    llm = ScriptedLLM(text_reply("one"), text_reply("two"))
    h, proj = make(tmp_path, llm)

    async def main():
        a = await h.prompt("first")
        b = await h.prompt("second")
        base = S.collect(h.store)
        h.store.add_usage(a.session_id, 0.25, M.TokenUsage(input=100, output=50))
        h.store.add_usage(b.session_id, 0.5, M.TokenUsage(input=10, output=5))
        child = h.sessions.create(parent_id=a.session_id)
        h.store.add_usage(child.id, 0.25, M.TokenUsage(input=1, output=1))
        everything = S.collect(h.store)
        assert everything.sessions == 3 and everything.child_sessions == 1
        assert abs((everything.cost - base.cost) - 1.0) < 1e-9 and everything.tokens.input - base.tokens.input == 111
        one = S.collect(h.store, a.session_id)
        assert one.sessions == 2 and abs(one.cost - 0.5 - (S.collect(h.store, a.session_id, include_children=False).cost - 0.25)) < 1e-9  # the session and its subagent
        assert S.collect(h.store, a.session_id, include_children=False).sessions == 1
        assert S.collect(h.store, "ses_missing").sessions == 0 and S.render(S.Stats()) == "No sessions."
        assert abs(everything.cost_per_session - everything.cost / 3) < 1e-12
        await h.close()

    asyncio.run(main())


def test_old_sessions_can_be_left_out(tmp_path):
    llm = ScriptedLLM(text_reply("one"), text_reply("two"))
    h, proj = make(tmp_path, llm)

    async def main():
        a = await h.prompt("old")
        await h.prompt("new")
        h.store.db.execute("update session set time_updated = ? where id = ?", (1_000, a.session_id))
        assert S.collect(h.store).sessions == 2
        assert S.collect(h.store, days=7).sessions == 1
        await h.close()

    asyncio.run(main())
