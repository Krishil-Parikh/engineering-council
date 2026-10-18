"""subagent, question and skill tools, plus the form and session services they sit on."""

import asyncio
from pathlib import Path

import pytest

from harness import form as F
from harness.agent import default_registry
from harness.form import FormService
from harness.permission import DeclinedError
from harness.schema import message as M
from harness.schema.permission import Rule
from harness.session.runner.runner import DrainResult
from harness.session.service import SessionService
from harness.skill import SkillCatalog, SkillInfo
from harness.tool.builtin import question, skill, subagent
from harness.tool.info import ToolError
from tests.harness.tools_rig import Rig


class FakeRunner:
    """Answers each drain with an assistant message echoing the last user text; `gate` holds runs open."""

    def __init__(self, store):
        self.store = store
        self.gate = None
        self.calls = []
        self.fail = None

    async def drain(self, session_id):
        self.calls.append(session_id)
        if self.gate:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError(self.fail)
        last = [m for _, m in self.store.messages(session_id) if isinstance(m, (M.User, M.Synthetic))][-1]
        info = self.store.get(session_id)
        msg = M.Assistant(agent=info.agent or "build", model=M.ModelRef(provider_id="p", id="m"), content=[M.AssistantText(text=f"did: {last.text.splitlines()[-1]}")])
        msg.time.completed = M.now_ms()
        self.store.add(session_id, msg)
        return DrainResult("succeeded", 1)


def build(tmp_path, rules=None, answers=None):
    rig = Rig(tmp_path, rules=rules, answers=answers)
    runner = FakeRunner(rig.store)
    sessions = SessionService(rig.store, runner, str(rig.proj))
    catalog = SkillCatalog()
    rig.deps.extras.update({"sessions": sessions, "agents": default_registry(None, rig.home, str(rig.proj / ".plans")), "forms": FormService(), "skills": catalog})
    rig.add(subagent.make, question.make, skill.make)
    # the rig's default session needs the model/agent a parent would have
    rig.store.update(rig.session.id, agent="build", model={"provider_id": "p", "id": "m"})
    return rig, runner, sessions, catalog


# ------------------------------------------------------------------ subagent

def test_foreground_subagent_runs_a_child_and_returns_its_reply(tmp_path):
    rig, runner, sessions, _ = build(tmp_path)

    async def main():
        res = await rig.acall("subagent", agent="general", description="find x", prompt="find the thing")
        text = "\n".join(c.text for c in res.content)
        child = rig.store.children(rig.session.id)[0]
        assert text == f'<subagent sessionID="{child.id}" state="completed">\ndid: find the thing\n</subagent>'
        assert child.agent == "general" and child.title == "find x"
        first = [m for _, m in rig.store.messages(child.id) if isinstance(m, M.User)][0]
        assert first.text.startswith("You are a subagent spawned by another session.")

    asyncio.run(main())


def test_continuing_a_child_by_session_id_omits_the_preamble(tmp_path):
    rig, runner, sessions, _ = build(tmp_path)

    async def main():
        await rig.acall("subagent", agent="general", description="d", prompt="one")
        child = rig.store.children(rig.session.id)[0]
        res = await rig.acall("subagent", agent="general", description="d", prompt="two", sessionID=child.id)
        assert "did: two" in "\n".join(c.text for c in res.content)
        users = [m.text for _, m in rig.store.messages(child.id) if isinstance(m, M.User)]
        assert users[1] == "two" and len(rig.store.children(rig.session.id)) == 1

    asyncio.run(main())


def test_subagent_rejections(tmp_path):
    rig, runner, sessions, _ = build(tmp_path)
    with pytest.raises(ToolError, match="Unknown agent: nope"):
        rig.call("subagent", agent="nope", description="d", prompt="p")
    with pytest.raises(ToolError, match="cannot run as a subagent"):
        rig.call("subagent", agent="build", description="d", prompt="p")
    with pytest.raises(ToolError, match="Subagent session not found"):
        rig.call("subagent", agent="general", description="d", prompt="p", sessionID="ses_missing")
    other = rig.store.create(str(rig.proj))
    with pytest.raises(ToolError, match="is not a child of the current session"):
        rig.call("subagent", agent="general", description="d", prompt="p", sessionID=other.id)
    with pytest.raises(ToolError, match='Invalid model "bad"'):
        rig.call("subagent", agent="general", description="d", prompt="p", model="bad")


def test_depth_limit_blocks_nested_subagents(tmp_path):
    rig, runner, sessions, _ = build(tmp_path)
    child = rig.store.create(str(rig.proj), agent="general", parent_id=rig.session.id)
    rig.session = child
    with pytest.raises(ToolError, match="Subagent depth limit reached \\(1\\)"):
        rig.call("subagent", agent="general", description="d", prompt="p")
    rig.deps.extras["subagent_depth"] = 2
    assert "did: p" in rig.text("subagent", agent="general", description="d", prompt="p")


def test_model_override_is_validated_against_the_catalog(tmp_path):
    rig, runner, sessions, _ = build(tmp_path)
    rig.deps.extras["models_available"] = lambda: [{"provider_id": "g", "id": "fast", "variants": ["high"]}]
    with pytest.raises(ToolError, match='"g/slow" is not available'):
        rig.call("subagent", agent="general", description="d", prompt="p", model="g/slow")
    with pytest.raises(ToolError, match='Variant "low" is not available.*Available: high'):
        rig.call("subagent", agent="general", description="d", prompt="p", model="g/fast#low")
    rig.call("subagent", agent="general", description="d", prompt="p", model="g/fast#high")
    assert rig.store.children(rig.session.id)[0].model == {"provider_id": "g", "id": "fast", "variant": "high"}


def test_failed_child_reports_its_session_id(tmp_path):
    rig, runner, sessions, _ = build(tmp_path)
    runner.fail = "boom"
    with pytest.raises(ToolError, match=r"Subagent failed \(sessionID: ses_\w+\): boom"):
        rig.call("subagent", agent="general", description="d", prompt="p")


def test_background_subagent_notifies_the_parent_when_done(tmp_path):
    rig, runner, sessions, _ = build(tmp_path)

    async def main():
        runner.gate = asyncio.Event()
        res = await rig.acall("subagent", agent="general", description="slow job", prompt="work", background=True)
        text = "\n".join(c.text for c in res.content)
        assert "working in the background" in text and "DO NOT sleep, poll" in text
        runner.gate.set()
        for _ in range(100):
            await asyncio.sleep(0.05)
            notes = [m for _, m in rig.store.messages(rig.session.id) if isinstance(m, M.Synthetic)]
            if notes:
                break
        assert 'state="completed" description="slow job"' in notes[0].text and "did: work" in notes[0].text
        assert notes[0].metadata["source"] == "subagent"
        await sessions.close()

    asyncio.run(main())


def test_signal_moves_a_foreground_subagent_to_the_background(tmp_path):
    rig, runner, sessions, _ = build(tmp_path)

    async def main():
        runner.gate = asyncio.Event()
        call = asyncio.ensure_future(rig.acall("subagent", agent="general", description="d", prompt="p"))
        await asyncio.sleep(0.2)
        assert len(rig.jobs.background_all(rig.session.id, "subagent")) == 1
        assert "working in the background" in "\n".join(c.text for c in (await call).content)
        runner.gate.set()
        for _ in range(100):
            await asyncio.sleep(0.05)
            if any(isinstance(m, M.Synthetic) for _, m in rig.store.messages(rig.session.id)):
                break
        assert any(isinstance(m, M.Synthetic) and "did: p" in m.text for _, m in rig.store.messages(rig.session.id))
        await sessions.close()

    asyncio.run(main())


def test_cancelling_the_parent_call_interrupts_the_child(tmp_path):
    rig, runner, sessions, _ = build(tmp_path)

    async def main():
        runner.gate = asyncio.Event()
        call = asyncio.ensure_future(rig.acall("subagent", agent="general", description="d", prompt="p"))
        await asyncio.sleep(0.2)
        child = rig.store.children(rig.session.id)[0]
        assert sessions.running(child.id)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        assert not sessions.running(child.id)

    asyncio.run(main())


def test_subagent_needs_permission_for_the_agent(tmp_path):
    rig, *_ = build(tmp_path, rules=[Rule("*", "*", "allow"), Rule("subagent", "general", "ask")], answers=["once"])
    rig.call("subagent", agent="general", description="d", prompt="p")
    assert ("subagent", ["general"]) == rig.asked[0][:2]


def test_description_lists_available_subagents(tmp_path):
    rig, runner, sessions, _ = build(tmp_path)
    agents = rig.deps.extras["agents"]
    desc = subagent.with_available_subagents(subagent.DESCRIPTION, agents, agents.resolve("build"))
    assert "Available subagents:" in desc and "- general:" in desc and "- build:" not in desc
    denied = agents.resolve("build")
    denied.permissions = [*denied.permissions, Rule("subagent", "general", "deny")]
    assert "- general:" not in subagent.with_available_subagents(subagent.DESCRIPTION, agents, denied)


def test_repair_input_drops_empty_optionals():
    event = {"tool": "subagent", "input": {"agent": "a", "model": "", "sessionID": ""}}
    subagent.repair_input(event)
    assert event["input"] == {"agent": "a"}


def test_session_service_wake_and_interrupt(tmp_path):
    rig, runner, sessions, _ = build(tmp_path)

    async def main():
        sessions.synthetic(rig.session.id, "ping", "d")
        await asyncio.sleep(0.1)
        assert runner.calls == [rig.session.id]
        runner.gate = asyncio.Event()
        sessions.prompt(rig.session.id, "again")
        task = asyncio.ensure_future(sessions.resume(rig.session.id))
        await asyncio.sleep(0.05)
        assert sessions.running(rig.session.id)
        await sessions.interrupt(rig.session.id)
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())


# ------------------------------------------------------------------ question

def ask_in_background(rig, **kw):
    async def main(reply):
        call = asyncio.ensure_future(rig.acall("question", **kw))
        await asyncio.sleep(0.05)
        forms = rig.deps.extras["forms"]
        pending = forms.list()
        assert len(pending) == 1
        reply(forms, pending[0])
        return await call

    return main


def test_question_returns_the_answers(tmp_path):
    rig, *_ = build(tmp_path)
    qs = [
        {"question": "Which db?", "header": "DB", "options": [{"label": "pg", "description": "Postgres"}, {"label": "sqlite", "description": "file"}]},
        {"question": "Extras?", "header": "X", "multiple": True, "options": [{"label": "a", "description": "A"}, {"label": "b", "description": "B"}]},
    ]
    main = ask_in_background(rig, questions=qs)
    res = asyncio.run(main(lambda forms, f: forms.reply(f["id"], {"q0": "pg", "q1": ["a", "custom"]})))
    assert "\n".join(c.text for c in res.content) == (
        'User has answered your questions: "Which db?"="pg", "Extras?"="a, custom". You can now continue with the user\'s answers in mind.'
    )
    assert res.output == {"answers": [["pg"], ["a", "custom"]]}


def test_unanswered_question_and_dismissals(tmp_path):
    rig, *_ = build(tmp_path)
    q = [{"question": "Q?", "header": "H", "options": []}]
    res = asyncio.run(ask_in_background(rig, questions=q)(lambda forms, f: forms.reply(f["id"], {})))
    assert '"Q?"="Unanswered"' in "\n".join(c.text for c in res.content)
    with pytest.raises(DeclinedError, match="dismissed"):
        asyncio.run(ask_in_background(rig, questions=q)(lambda forms, f: forms.cancel(f["id"])))
    with pytest.raises(ToolError, match="no UI here"):
        asyncio.run(ask_in_background(rig, questions=q)(lambda forms, f: forms.cancel(f["id"], "no UI here")))


def test_question_requires_at_least_one_question(tmp_path):
    rig, *_ = build(tmp_path)
    with pytest.raises(ToolError):
        rig.call("question", questions=[])


# ------------------------------------------------------------------ skill

def test_skill_tool_loads_skill_content(tmp_path):
    rig, _, _, catalog = build(tmp_path)
    d = rig.proj / ".agents" / "skills" / "lint"
    (d / "scripts").mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: lint\ndescription: lint stuff\n---\nRun the linter.\n")
    (d / "scripts" / "run.sh").write_text("x")
    catalog.add_provider(lambda: [SkillInfo("lint", "lint", d / "SKILL.md", "Run the linter.\n", "lint stuff")])
    out = rig.text("skill", id="lint")
    assert out.startswith('<skill_content name="lint">') and "Run the linter." in out and "scripts" in out
    with pytest.raises(ToolError, match="Unable to load skill nope"):
        rig.call("skill", id="nope")


def test_skill_permission_denied_is_reported(tmp_path):
    rig, _, _, catalog = build(tmp_path, rules=[Rule("*", "*", "allow"), Rule("skill", "lint", "deny")])
    catalog.add_provider(lambda: [SkillInfo("lint", "lint", rig.proj / "SKILL.md", "x", "d")])
    with pytest.raises(ToolError, match="Unable to load skill lint"):
        rig.call("skill", id="lint")


# ------------------------------------------------------------------ forms

def test_form_validation():
    s = FormService()

    async def main():
        with pytest.raises(F.InvalidFormError, match="at least one field"):
            s.create("s", "t", [])
        with pytest.raises(F.InvalidFormError, match="Duplicate form field key: a"):
            s.create("s", "t", [{"key": "a", "type": "string"}, {"key": "a", "type": "string"}])
        with pytest.raises(F.InvalidFormError, match="must reference an earlier field"):
            s.create("s", "t", [{"key": "a", "type": "string", "when": [{"key": "b", "op": "eq", "value": "x"}]}, {"key": "b", "type": "string"}])
        form = s.create("s", "t", [
            {"key": "kind", "type": "string", "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}], "required": True},
            {"key": "why", "type": "string", "required": True, "when": [{"key": "kind", "op": "eq", "value": "b"}]},
            {"key": "n", "type": "integer", "minimum": 1, "maximum": 3},
        ])
        with pytest.raises(F.InvalidAnswerError, match="Missing required form field: kind"):
            s.reply(form["id"], {})
        with pytest.raises(F.InvalidAnswerError, match="Invalid option"):
            s.reply(form["id"], {"kind": "z"})
        with pytest.raises(F.InvalidAnswerError, match="Missing required form field: why"):
            s.reply(form["id"], {"kind": "b"})
        with pytest.raises(F.InvalidAnswerError, match="not active: why"):
            s.reply(form["id"], {"kind": "a", "why": "x"})
        with pytest.raises(F.InvalidAnswerError, match="too large: n"):
            s.reply(form["id"], {"kind": "a", "n": 9})
        with pytest.raises(F.InvalidAnswerError, match="Unknown form field: q"):
            s.reply(form["id"], {"kind": "a", "q": 1})
        s.reply(form["id"], {"kind": "b", "why": "because", "n": 2})
        assert s.state(form["id"])["status"] == "answered"
        with pytest.raises(F.AlreadySettledError):
            s.cancel(form["id"])

    asyncio.run(main())


def test_form_ask_cancel_on_interrupt_and_close():
    s = FormService()

    async def main():
        field = [{"key": "a", "type": "string"}]
        task = asyncio.ensure_future(s.ask("s", "t", field))
        await asyncio.sleep(0.02)
        fid = s.list("s")[0]["id"]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert s.state(fid)["status"] == "cancelled" and s.list() == []
        pending = asyncio.ensure_future(s.ask("s", "t", field))
        await asyncio.sleep(0.02)
        s.close()
        assert (await pending)["status"] == "cancelled"
        assert (await s.ask("s", "late", field))["status"] == "cancelled"

    asyncio.run(main())


def test_settled_forms_expire():
    clock = [0.0]
    s = FormService(clock=lambda: clock[0])

    async def main():
        form = s.create("s", "t", [{"key": "a", "type": "boolean"}])
        s.reply(form["id"], {"a": True})
        clock[0] = F.RETENTION_SECONDS - 1
        s.get(form["id"])
        clock[0] = F.RETENTION_SECONDS + 1
        with pytest.raises(F.NotFoundError):
            s.get(form["id"])

    asyncio.run(main())
