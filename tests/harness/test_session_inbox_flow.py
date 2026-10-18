"""Input to a busy session: steer, queue, idle sends, manual compaction and interruption, through a real Harness."""

import asyncio

from harness.schema import message as M
from harness.session import compaction as C
from tests.harness.conftest import SUMMARY
from tests.harness.test_app import make
from tests.harness.test_runner import ScriptedLLM, text_reply, tool_reply


def request_text(request):
    return "\n".join(p.text for m in request.messages for p in m.content if hasattr(p, "text"))


def kinds(h, session_id):
    out = []
    for m in h.sessions.messages(session_id):
        if isinstance(m, M.User):
            out.append(("user", m.text))
        elif isinstance(m, M.Synthetic):
            out.append(("synthetic", m.text))
        elif isinstance(m, M.Assistant):
            out.append(("assistant", "".join(p.text for p in m.content if isinstance(p, M.AssistantText))))
        elif isinstance(m, M.CompactionEnded) if hasattr(M, "CompactionEnded") else False:
            out.append(("compaction", ""))
    return out


def test_a_steer_during_a_step_is_seen_by_the_next_step_of_the_same_run(tmp_path):
    llm = ScriptedLLM()  # its script is set once the Harness exists, because the script talks to the Harness
    h, proj = make(tmp_path, llm)
    (proj / "a.txt").write_text("one\n")
    sid = h.new_session().id

    def first(request):
        h.sessions.send(sid, "also keep it short", "steer")  # the user types while the model is working on step 1
        return tool_reply(("read", {"path": "a.txt"}))

    llm.script = [first, text_reply("done, briefly")]

    async def main():
        h.sessions.prompt(sid, "read a.txt")
        result = await h.sessions.resume(sid)
        assert result.outcome == "succeeded" and result.steps == 2  # still one run: the steer joined it
        assert "also keep it short" not in request_text(llm.requests[0]) and "also keep it short" in request_text(llm.requests[1])
        order = [k for k, _ in kinds(h, sid)]
        assert order == ["user", "assistant", "user", "assistant"]  # the steer sits between the two steps
        await h.close()

    asyncio.run(main())


def test_a_queued_prompt_waits_for_the_current_work_to_finish_and_then_gets_its_own_answer(tmp_path):
    llm = ScriptedLLM()  # its script is set once the Harness exists, because the script talks to the Harness
    h, proj = make(tmp_path, llm)
    (proj / "a.txt").write_text("one\n")
    sid = h.new_session().id

    def first(request):
        h.sessions.send(sid, "and then explain it", "queue")
        return tool_reply(("read", {"path": "a.txt"}))

    llm.script = [first, text_reply("here is a.txt"), text_reply("explained")]

    async def main():
        h.sessions.prompt(sid, "read a.txt")
        result = await h.sessions.resume(sid)
        assert result.outcome == "succeeded" and result.steps == 3
        assert "and then explain it" not in request_text(llm.requests[0]) and "and then explain it" not in request_text(llm.requests[1])
        assert "and then explain it" in request_text(llm.requests[2])  # only once the first answer was complete
        assert kinds(h, sid)[-2:] == [("user", "and then explain it"), ("assistant", "explained")]
        await h.close()

    asyncio.run(main())


def test_input_sent_to_an_idle_session_starts_it(tmp_path):
    h, _ = make(tmp_path, ScriptedLLM(text_reply("hi there")))
    sid = h.new_session().id

    async def main():
        h.sessions.send(sid, "hello", "queue")
        await asyncio.wait_for(h.sessions.coordinator.await_idle(sid), 5)
        assert kinds(h, sid) == [("user", "hello"), ("assistant", "hi there")]
        await h.close()

    asyncio.run(main())


def test_queued_prompts_are_answered_one_after_another_in_order(tmp_path):
    h, _ = make(tmp_path, ScriptedLLM(text_reply("first answer"), text_reply("second answer")))
    sid = h.new_session().id

    async def main():
        h.sessions.send(sid, "first question", "queue", wake=False)
        h.sessions.send(sid, "second question", "queue")
        await asyncio.wait_for(h.sessions.coordinator.await_idle(sid), 5)
        assert kinds(h, sid) == [("user", "first question"), ("assistant", "first answer"), ("user", "second question"), ("assistant", "second answer")]
        await h.close()

    asyncio.run(main())


def test_a_wake_with_nothing_pending_does_not_call_the_model(tmp_path):
    llm = ScriptedLLM(text_reply("should not be asked"))
    h, _ = make(tmp_path, llm)
    sid = h.new_session().id

    async def main():
        h.sessions.wake(sid)
        h.sessions.wake(sid, "steer")
        await asyncio.wait_for(h.sessions.coordinator.await_idle(sid), 5)
        assert llm.requests == [] and h.sessions.messages(sid) == []
        await h.close()

    asyncio.run(main())


def test_a_background_notice_reaches_a_busy_session_at_its_next_step(tmp_path):
    llm = ScriptedLLM()  # its script is set once the Harness exists, because the script talks to the Harness
    h, proj = make(tmp_path, llm)
    (proj / "a.txt").write_text("one\n")
    sid = h.new_session().id

    def first(request):
        h.sessions.synthetic(sid, "<shell id=\"x\" state=\"completed\">build done</shell>", "build")
        return tool_reply(("read", {"path": "a.txt"}))

    llm.script = [first, text_reply("noted the build")]

    async def main():
        h.sessions.prompt(sid, "read a.txt")
        await h.sessions.resume(sid)
        assert "build done" in request_text(llm.requests[1])
        await h.close()

    asyncio.run(main())


def test_cancelling_pending_input_removes_it(tmp_path):
    llm = ScriptedLLM(text_reply("answer"))
    h, _ = make(tmp_path, llm)
    sid = h.new_session().id
    drop = h.sessions.send(sid, "never mind this", "queue", wake=False)
    h.sessions.send(sid, "keep this", "queue", wake=False)
    h.sessions.cancel_input(sid, drop.id)
    assert [i.payload["text"] for i in h.sessions.pending_input(sid)] == ["keep this"]

    async def main():
        h.sessions.wake(sid)
        await asyncio.wait_for(h.sessions.coordinator.await_idle(sid), 5)
        assert "never mind this" not in request_text(llm.requests[0]) and "keep this" in request_text(llm.requests[0])
        await h.close()

    asyncio.run(main())


def test_a_manual_compaction_summarizes_without_asking_the_model_for_an_answer(tmp_path):
    llm = ScriptedLLM(SUMMARY)
    h, _ = make(tmp_path, llm, compaction=C.Settings(keep=1))
    sid = h.new_session().id
    for i in range(3):
        h.store.add(sid, M.User(text=f"question {i} " + "padding " * 50))
        a = M.Assistant(agent="build", model=M.ModelRef(provider_id="google", id=h.model_id), content=[M.AssistantText(text=f"answer {i} " + "padding " * 50)], finish="stop")
        a.time.completed = M.now_ms()
        h.store.add(sid, a)

    async def main():
        result = await h.sessions.compact(sid)
        assert result.outcome == "succeeded" and result.steps == 0
        assert len(llm.requests) == 1  # only the summarizer ran
        compactions = [m for m in h.sessions.messages(sid) if getattr(m, "type", "") == "compaction"]
        assert compactions and h.sessions.pending_input(sid) == []
        await h.close()

    asyncio.run(main())


def test_interrupting_with_resume_lets_the_steer_carry_on_in_a_fresh_run(tmp_path):
    gate = asyncio.Event()
    holder = {}

    class Gated(ScriptedLLM):
        async def stream(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                holder["started"].set()
                await gate.wait()  # the first request never finishes: it is interrupted
            for ev in text_reply("after the change of course"):
                yield ev

    llm = Gated()
    h, _ = make(tmp_path, llm)
    sid = h.new_session().id

    async def main():
        holder["started"] = asyncio.Event()
        h.sessions.prompt(sid, "do the first thing")
        running = asyncio.ensure_future(h.sessions.resume(sid))
        await holder["started"].wait()
        h.sessions.send(sid, "actually, do something else", "steer", wake=False)
        assert await h.sessions.interrupt(sid, resume=True) is True
        gate.set()
        try:
            await running
        except asyncio.CancelledError:
            pass
        await asyncio.wait_for(h.sessions.coordinator.await_idle(sid), 5)
        assert "actually, do something else" in request_text(llm.requests[1])
        assert kinds(h, sid)[-1] == ("assistant", "after the change of course")
        await h.close()

    asyncio.run(main())


def test_interrupting_without_resume_leaves_queued_follow_ups_parked(tmp_path):
    started = asyncio.Event()

    class Hang(ScriptedLLM):
        async def stream(self, request):
            self.requests.append(request)
            started.set()
            await asyncio.Event().wait()
            yield  # pragma: no cover

    llm = Hang()
    h, _ = make(tmp_path, llm)
    sid = h.new_session().id

    async def main():
        h.sessions.prompt(sid, "work")
        running = asyncio.ensure_future(h.sessions.resume(sid))
        await started.wait()
        h.sessions.send(sid, "later", "queue", wake=False)
        assert await h.sessions.interrupt(sid) is True
        try:
            await running
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.1)
        assert not h.sessions.running(sid) and [i.payload["text"] for i in h.sessions.pending_input(sid)] == ["later"]
        await h.close()

    asyncio.run(main())
