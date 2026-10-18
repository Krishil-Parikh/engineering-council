"""The meeting's developer calls carried over A2A: each developer and the scrum master is an agent with a gRPC server."""

import asyncio
import json

import pytest

from meetings.a2a_llm import A2ALLM, agent_for, serve_meeting
from meetings.gemini_client import AuthError, MalformedOutputError, QuotaError
from meetings.models import BlindThoughts
from tests.meetings.fakes import FakeLLM
from tests.meetings.test_meeting import make_input, run


def test_stage_names_say_which_agent_is_called():
    assert agent_for("blind:DEV_3") == "DEV_3" and agent_for("talk2:DEV_1") == "DEV_1" and agent_for("proposal:DEV_5") == "DEV_5"
    assert agent_for("rediscuss:DEV_6") == "DEV_6" and agent_for("design1:DEV_2") == "DEV_2"
    for stage in ("scrum:wrapup", "question_curation", "decisions", "revision", "repair"):
        assert agent_for(stage) == "SCRUM_MASTER"


def test_a_call_reaches_the_right_developer_and_comes_back_typed():
    async def main():
        inner = FakeLLM()
        llm = await serve_meeting(inner)
        try:
            result = await llm.generate("think", BlindThoughts, stage="blind:DEV_4", system="you are a developer")
            assert isinstance(result, BlindThoughts) and result.agent_id == "DEV_4" and result.understanding
            entries = llm.network.audit.entries
            assert [(e["sender"], e["recipient"], e["topic"]) for e in entries] == [("meeting", "DEV_4", "blind:DEV_4")]
            assert json.loads(entries[0]["text"])["schema"] == "meetings.models:BlindThoughts"
            assert inner.calls["blind:DEV_4"] == 1
        finally:
            await llm.close()

    asyncio.run(main())


@pytest.mark.parametrize("error", [AuthError("bad key"), QuotaError("slow down"), MalformedOutputError("not json")])
def test_errors_keep_their_type_across_the_wire(error):
    class Failing(FakeLLM):
        async def generate(self, prompt, schema, *, stage, system=""):
            raise error

    async def main():
        llm = await serve_meeting(Failing())
        try:
            with pytest.raises(type(error), match=str(error)):
                await llm.generate("x", BlindThoughts, stage="blind:DEV_1")
        finally:
            await llm.close()

    asyncio.run(main())


def test_usage_and_observer_are_the_wrapped_clients():
    async def main():
        inner = FakeLLM()
        llm = await serve_meeting(inner)
        try:
            llm.observer = lambda event: None
            assert inner.observer is llm.observer and llm.usage is inner.usage
        finally:
            await llm.close()

    asyncio.run(main())


def test_a_whole_meeting_runs_over_a2a_and_produces_the_same_artifacts(tmp_path):
    llm = FakeLLM()
    result = run(make_input(tmp_path), llm, a2a=True)
    out = result.out_dir
    for name in ("PRD.md", "Technical_Approach.md", "Design.md", "specification.json", "minutes.md", "roster.json"):
        assert (out / name).read_text(encoding="utf-8").strip(), name
    assert result.report.passed and json.loads((out / "meeting.json").read_text())["status"] == "completed"
    log = [json.loads(line) for line in (out / "a2a-audit.jsonl").read_text(encoding="utf-8").splitlines()]
    recipients = {e["recipient"] for e in log}
    assert {f"DEV_{i}" for i in range(1, 7)} <= recipients and "SCRUM_MASTER" in recipients
    assert all(e["sender"] == "meeting" and "reply" in e for e in log)
    assert sum(llm.calls.values()) == len(log)  # every model call travelled as one A2A message
    assert (out / "usage.json").exists()


def test_a_failing_meeting_still_shuts_its_agents_down(tmp_path):
    class BadKey(FakeLLM):
        async def generate(self, prompt, schema, *, stage, system=""):
            if stage == "blind:DEV_1":
                raise AuthError("bad key")  # fatal: the meeting stops
            return await super().generate(prompt, schema, stage=stage, system=system)

    with pytest.raises(Exception, match="bad key"):
        run(make_input(tmp_path), BadKey(), a2a=True)
    # a second meeting in the same process starts fine: no port or event loop is left held
    assert run(make_input(tmp_path, "Second"), FakeLLM(), a2a=True).report.passed
