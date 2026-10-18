"""Session titles, ported from opencode's session-title scenarios."""

import asyncio

from harness.schema import message as M
from harness.session import title as T
from tests.harness.test_app import make
from tests.harness.test_runner import ScriptedLLM, text_reply


def request_text(request):
    return "\n".join(p.text for m in request.messages for p in m.content if hasattr(p, "text"))


def system_text(request):
    return " ".join(p.text for p in request.system)


def seeded(tmp_path, llm, user="Build a todo app with a CLI", auto=False):
    h, _ = make(tmp_path, llm, auto_title=auto)
    sid = h.new_session().id
    if user:
        h.store.add(sid, M.User(text=user))
    return h, sid


def run(coro):
    return asyncio.run(coro)


def test_a_title_comes_from_the_first_user_message_and_the_title_agent(tmp_path):
    llm = ScriptedLLM(text_reply("Todo app CLI"))
    h, sid = seeded(tmp_path, llm)

    async def main():
        assert await h.titles.generate(sid) == "Todo app CLI"
        assert h.store.get(sid).title == "Todo app CLI"
        assert request_text(llm.requests[0]) == "Build a todo app with a CLI" and "title generator" in system_text(llm.requests[0])
        assert llm.requests[0].tools == []  # a plain request: no tools
        await h.close()

    run(main())


def test_only_the_first_non_empty_line_is_used_and_long_titles_are_cut(tmp_path):
    llm = ScriptedLLM(text_reply("\n\n  Fix the login bug  \nAnd a second line that is ignored"))
    h, sid = seeded(tmp_path, llm)

    async def main():
        assert await h.titles.generate(sid) == "Fix the login bug"
        h.store.update(sid, title=None)
        llm.script.append(text_reply("x" * 150))
        assert len(await h.titles.generate(sid)) == 100 and h.store.get(sid).title.endswith("...")
        await h.close()

    run(main())


def test_nothing_to_name_changes_nothing(tmp_path):
    llm = ScriptedLLM(text_reply("unused"))
    h, empty = seeded(tmp_path, llm, user=None)

    async def main():
        assert await h.titles.generate(empty) is None and await h.titles.generate("ses_missing") is None
        assert llm.requests == []
        await h.close()

    run(main())


def test_without_a_title_agent_titles_are_off(tmp_path):
    llm = ScriptedLLM(text_reply("unused"))
    h, sid = seeded(tmp_path, llm)
    h.agents.transform(lambda editor: editor.remove("title"))

    async def main():
        assert await h.titles.generate(sid) is None and llm.requests == [] and h.store.get(sid).title is None
        await h.close()

    run(main())


def test_a_failed_or_empty_request_leaves_the_session_alone_and_can_be_retried(tmp_path):
    class Failing(ScriptedLLM):
        async def stream(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                raise RuntimeError("provider down")
            if len(self.requests) == 2:
                for ev in text_reply("  \n "):
                    yield ev
                return
            for ev in text_reply("Third time lucky"):
                yield ev

    llm = Failing()
    h, sid = seeded(tmp_path, llm)

    async def main():
        assert await h.titles.generate(sid) is None and h.store.get(sid).title is None
        assert await h.titles.generate(sid) is None and h.store.get(sid).title is None
        assert await h.titles.generate(sid) == "Third time lucky"
        await h.close()

    run(main())


def test_a_provider_error_event_does_not_rename(tmp_path):
    from harness.ai import events as E

    llm = ScriptedLLM([E.TextDelta("Half a title"), E.ProviderError("overloaded")])
    h, sid = seeded(tmp_path, llm)

    async def main():
        assert await h.titles.generate(sid) is None and h.store.get(sid).title is None
        await h.close()

    run(main())


def test_a_manual_rename_during_generation_wins(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    class Slow(ScriptedLLM):
        async def stream(self, request):
            self.requests.append(request)
            started.set()
            await release.wait()
            for ev in text_reply("Machine title"):
                yield ev

    h, sid = seeded(tmp_path, Slow())

    async def main():
        task = asyncio.ensure_future(h.titles.generate(sid))
        await started.wait()
        h.sessions.rename(sid, "My own title")
        release.set()
        assert await task is None and h.store.get(sid).title == "My own title"
        await h.close()

    run(main())


def test_an_existing_title_is_regenerated_from_bounded_context(tmp_path):
    llm = ScriptedLLM(text_reply("Todo CLI with sync"))
    h, sid = seeded(tmp_path, llm, user="Original request text " + "o" * 3000)
    h.store.update(sid, title="Todo app CLI")
    h.store.add(sid, M.Assistant(agent="build", model=M.ModelRef(provider_id="google", id="m"), content=[M.AssistantText(text="Sure, starting now.")], finish="stop"))
    h.store.add(sid, M.User(text="please add sync across devices"))
    h.store.add(sid, M.Assistant(agent="build", model=M.ModelRef(provider_id="google", id="m"), content=[M.AssistantText(text="z" * 20_000)], finish="stop"))

    async def main():
        assert await h.titles.generate(sid) == "Todo CLI with sync"
        text = request_text(llm.requests[0])
        assert text.startswith("Original request:\nOriginal request text ") and "Recent conversation:" in text
        assert len(text) <= T.MAX_CONTEXT_LENGTH + 2 * T.MAX_FIRST_MESSAGE_LENGTH and text.count("o") < 2100  # the original is cut to 2000 characters
        assert text.endswith("z" * 100)  # the newest part of the conversation is the part kept
        await h.close()

    run(main())


def test_an_unchanged_regenerated_title_is_not_a_rename(tmp_path):
    events = []
    llm = ScriptedLLM(text_reply("Same title"))
    h, sid = seeded(tmp_path, llm)
    h.store.update(sid, title="Same title")
    h.on_event = lambda kind, data: events.append(kind)
    h.titles.on_event = h.on_event

    async def main():
        assert await h.titles.generate(sid) is None and "session.renamed" not in events
        await h.close()

    run(main())


def test_untitled_recognizes_missing_and_placeholder_titles():
    from harness.session.store import SessionInfo

    assert T.is_untitled(SessionInfo(id="a", directory="/", title=None)) and T.is_untitled(SessionInfo(id="a", directory="/", title=""))
    assert T.is_untitled(SessionInfo(id="a", directory="/", title="New session - 2026-10-18T12:00:00.000Z"))
    assert T.is_untitled(SessionInfo(id="a", directory="/", title="Child session - 2026-10-18T12:00:00.000Z"))
    assert not T.is_untitled(SessionInfo(id="a", directory="/", title="Fix login"))


def test_with_auto_title_a_new_conversation_is_named_while_it_runs(tmp_path):
    class Both(ScriptedLLM):
        async def stream(self, request):
            self.requests.append(request)
            text = "Greeting" if "title generator" in system_text(request) else "Hello! How can I help?"
            for ev in text_reply(text):
                yield ev

    llm = Both()
    h, _ = make(tmp_path, llm, auto_title=True)

    async def main():
        result = await h.prompt("hello there")
        for _ in range(60):
            if h.store.get(result.session_id).title:
                break
            await asyncio.sleep(0.05)
        assert result.text == "Hello! How can I help?" and h.store.get(result.session_id).title == "Greeting"
        await h.close()

    run(main())


def test_child_sessions_are_not_named_automatically(tmp_path):
    llm = ScriptedLLM(text_reply("unused"))
    h, parent = seeded(tmp_path, llm, auto=True)
    child = h.sessions.create(parent_id=parent).id
    h.titles.when_input_arrives(child, 1)
    assert child not in h.titles._running and llm.requests == []
