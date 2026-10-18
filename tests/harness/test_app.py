"""The assembled harness: real tools, permissions, sessions and subagents driven by a scripted model."""

import asyncio
import time

import pytest

from harness.app import Harness
from harness.schema import message as M
from tests.harness.test_runner import ScriptedLLM, text_reply, tool_reply


def make(tmp_path, llm, name="proj", **kw):
    home = tmp_path / "home"
    proj = home / name
    proj.mkdir(parents=True, exist_ok=True)
    return Harness(proj, llm=llm, data_root=tmp_path / f"data-{name}", home=home, db_path=":memory:", snapshots=False, **kw), proj


def tool_states(h, session_id):
    out = []
    for m in h.sessions.messages(session_id):
        if isinstance(m, M.Assistant):
            out += [(p.name, p.state.status) for p in m.content if isinstance(p, M.AssistantTool)]
    return out


def test_agent_writes_a_file_and_reports(tmp_path):
    llm = ScriptedLLM(tool_reply(("write", {"path": "hello.txt", "content": "hi there\n"})), text_reply("Created hello.txt."))
    h, proj = make(tmp_path, llm)

    async def main():
        result = await h.prompt("make a greeting file")
        assert (result.outcome, result.text, result.steps) == ("succeeded", "Created hello.txt.", 2)
        assert (proj / "hello.txt").read_text() == "hi there\n"
        assert tool_states(h, result.session_id) == [("write", "completed")]
        # the second request carried the tool result back to the model
        assert any("Created file successfully" in str(m) for m in llm.requests[1].messages)
        await h.close()

    asyncio.run(main())


def test_tool_registry_exposes_the_builtin_tools(tmp_path):
    h, _ = make(tmp_path, ScriptedLLM())
    names = {t.id for t in h.registry.list()}
    assert {"read", "edit", "write", "glob", "grep", "shell", "subagent", "question", "skill", "harness_session_rename", "harness_models"} <= names
    assert "harness_worktree_create" not in names  # no git repository here
    assert "Available subagents:" in h.registry.get("subagent").description


def test_unattended_agent_cannot_hang_on_a_permission_prompt(tmp_path):
    llm = ScriptedLLM(tool_reply(("read", {"path": ".env"})), text_reply("unreachable"))
    h, proj = make(tmp_path, llm)
    (proj / ".env").write_text("SECRET=1")

    async def main():
        result = await asyncio.wait_for(h.prompt("read the env file"), 10)
        assert result.outcome == "interrupted" and len(llm.requests) == 1  # rejected: the run ends after the first request
        assert tool_states(h, result.session_id) == [("read", "error")]
        assert not any("SECRET" in str(m) for r in llm.requests for m in r.messages)
        await h.close()

    asyncio.run(main())


def test_approver_can_allow_a_guarded_read(tmp_path):
    seen = []

    def approve(request):
        seen.append((request.action, request.resources))
        return "once"

    llm = ScriptedLLM(tool_reply(("read", {"path": ".env"})), text_reply("read it"))
    h, proj = make(tmp_path, llm, approve=approve)
    (proj / ".env").write_text("SECRET=1")

    async def main():
        result = await h.prompt("read the env file")
        assert result.outcome == "succeeded" and seen and seen[0][0] == "read"
        assert any("SECRET=1" in str(m) for m in llm.requests[1].messages)
        await h.close()

    asyncio.run(main())


def test_subagent_round_trip_through_the_whole_stack(tmp_path):
    llm = ScriptedLLM(
        tool_reply(("subagent", {"agent": "general", "description": "look around", "prompt": "list the files"})),
        text_reply("The folder has two files."),  # the child's reply
        text_reply("Subagent says: two files."),  # the parent's final reply
    )
    h, _ = make(tmp_path, llm)

    async def main():
        result = await h.prompt("what is in here?")
        assert result.outcome == "succeeded" and result.text == "Subagent says: two files."
        child = h.store.children(result.session_id)[0]
        assert child.agent == "general" and child.title == "look around"
        assert 'state="completed"' in str(llm.requests[2].messages) and "The folder has two files." in str(llm.requests[2].messages)
        await h.close()

    asyncio.run(main())


def test_instruction_file_reaches_the_model(tmp_path):
    llm = ScriptedLLM(text_reply("ok"))
    h, proj = make(tmp_path, llm)
    (proj / "AGENTS.md").write_text("Always answer in haiku.")

    async def main():
        await h.prompt("hello")
        assert "Always answer in haiku." in str(llm.requests[0].messages) + str(llm.requests[0].system)
        await h.close()

    asyncio.run(main())


def test_two_harnesses_run_in_parallel_without_waiting_for_each_other(tmp_path):
    """Each developer has their own Harness. Both model calls must be in flight at the same moment, or the barrier times out."""

    class BarrierLLM(ScriptedLLM):
        def __init__(self, barrier, *script):
            super().__init__(*script)
            self.barrier = barrier

        async def stream(self, request):
            await asyncio.wait_for(self.barrier.wait(), 5)
            async for ev in super().stream(request):
                yield ev

    async def main():
        barrier = asyncio.Barrier(2)
        a, pa = make(tmp_path, BarrierLLM(barrier, tool_reply(("write", {"path": "a.txt", "content": "A"})), text_reply("a done")), "alice")
        b, pb = make(tmp_path, BarrierLLM(barrier, tool_reply(("write", {"path": "b.txt", "content": "B"})), text_reply("b done")), "bob")
        started = time.monotonic()
        ra, rb = await asyncio.gather(a.prompt("do a"), b.prompt("do b"))
        assert (ra.text, rb.text) == ("a done", "b done")
        assert (pa / "a.txt").read_text() == "A" and (pb / "b.txt").read_text() == "B"
        assert not (pa / "b.txt").exists() and not (pb / "a.txt").exists()
        assert time.monotonic() - started < 5
        await a.close()
        await b.close()

    asyncio.run(main())


def test_new_session_defaults(tmp_path):
    h, _ = make(tmp_path, ScriptedLLM())
    s = h.new_session(title="t")
    assert s.agent == "build" and s.model["id"] == h.model_id and s.title == "t"
