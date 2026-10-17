import asyncio
import json

import pytest

from engineering_council import storage, synthesis
from engineering_council.config import Settings
from engineering_council.meeting import MeetingError, Reporter, revise_meeting, run_meeting
from engineering_council.models import Decision, Dispute, MeetingInput
from tests.fakes import FakeLLM

SETTINGS = Settings(api_key="k", model="fake")


def make_input(tmp_path, name="Todo CLI"):
    return MeetingInput(project_name=name, problem="A command line task list.", constraints=["Python"], output_dir=str(tmp_path))


def run(inp, llm, **kw):
    kw.setdefault("interactive", False)
    return asyncio.run(run_meeting(inp, SETTINGS, llm, Reporter(out=lambda _: None), **kw))


def test_full_meeting_produces_all_artifacts(tmp_path):
    llm = FakeLLM()
    result = run(make_input(tmp_path), llm)
    out = result.out_dir
    for name in ("input.md", "PRD.md", "Technical_Approach.md", "Design.md", "verification_report.md", "decisions.json",
                 "specification.json", "meeting.json", "minutes.md", "disputes.json", "questions.json", "usage.json"):
        assert (out / name).read_text(encoding="utf-8").strip(), name
    assert result.report.passed
    assert json.loads((out / "meeting.json").read_text())["status"] == "completed"
    assert sorted(p.stem for p in (out / "proposals").glob("*.json")) == sorted(["SYSTEMS_ARCHITECT", "PRODUCT_UX", "PRAGMATIC_MVP", "RED_TEAM_QA"])
    # one rebuttal call for the single agent that was objected to
    assert llm.calls["rebuttal:PRAGMATIC_MVP"] == 1
    minutes = (out / "minutes.md").read_text(encoding="utf-8")
    assert "DSP-001" in minutes and "Round 3" in minutes


def test_question_gate_never_exceeds_five(tmp_path):
    run(make_input(tmp_path), FakeLLM())
    saved = json.loads((tmp_path / "todo-cli" / "questions.json").read_text())
    assert len(saved["answers"]) <= 5


def test_one_failed_agent_is_reported_not_hidden(tmp_path):
    result = run(make_input(tmp_path), FakeLLM(fail_stages=("proposal:RED_TEAM_QA",)))
    assert any("RED_TEAM_QA did not contribute" in w for w in result.warnings)
    assert not (result.out_dir / "proposals" / "RED_TEAM_QA.json").exists()
    assert "Absent" in (result.out_dir / "minutes.md").read_text(encoding="utf-8")


def test_transient_proposal_failure_gets_one_second_chance(tmp_path):
    llm = FakeLLM(fail_once=("proposal:RED_TEAM_QA",))
    result = run(make_input(tmp_path), llm)
    assert llm.calls["proposal:RED_TEAM_QA"] == 2 or (result.out_dir / "proposals" / "RED_TEAM_QA.json").exists()
    assert (result.out_dir / "proposals" / "RED_TEAM_QA.json").exists()
    assert not any("did not contribute" in w for w in result.warnings)


def test_below_quorum_stops_but_keeps_completed_work(tmp_path):
    llm = FakeLLM(fail_stages=("proposal:RED_TEAM_QA", "proposal:PRODUCT_UX"))
    with pytest.raises(MeetingError, match="quorum"):
        run(make_input(tmp_path), llm)
    out = tmp_path / "todo-cli"
    assert (out / "proposals" / "SYSTEMS_ARCHITECT.json").exists()
    assert json.loads((out / "meeting.json").read_text())["status"] == "failed"


def test_resume_skips_completed_stages(tmp_path):
    with pytest.raises(Exception):
        run(make_input(tmp_path), FakeLLM(fail_stages=("decisions",)))
    llm = FakeLLM()
    result = run(make_input(tmp_path), llm, resume=True)
    assert result.report.passed
    assert llm.calls["proposal:SYSTEMS_ARCHITECT"] == 0 and llm.calls["review:RED_TEAM_QA"] == 0
    assert llm.calls["decisions"] == 1


def test_existing_meeting_requires_resume(tmp_path):
    run(make_input(tmp_path), FakeLLM())
    with pytest.raises(MeetingError, match="already holds"):
        run(make_input(tmp_path), FakeLLM())


def test_unaddressed_dispute_becomes_visible_unresolved_decision(tmp_path):
    result = run(make_input(tmp_path), FakeLLM(cover_dispute=False))
    unresolved = [d for d in result.decisions if d.status == "UNRESOLVED"]
    assert unresolved and "DSP-001" in unresolved[0].dispute_ids
    assert result.report.passed  # explicitly unresolved is acceptable, silently dropped is not
    assert "UNRESOLVED" in (result.out_dir / "PRD.md").read_text(encoding="utf-8")


def test_invented_requirement_ids_are_retried_then_removed(tmp_path):
    llm = FakeLLM(bad_spec_once=True)
    result = run(make_input(tmp_path), llm)
    assert llm.calls["spec_product_retry"] == 1
    assert "FR-777" not in (result.out_dir / "PRD.md").read_text(encoding="utf-8")


def test_revision_preserves_previous_version_and_reverifies(tmp_path):
    result = run(make_input(tmp_path), FakeLLM())
    rev = asyncio.run(revise_meeting(result.out_dir, "Add due dates", SETTINGS, FakeLLM(), Reporter(out=lambda _: None)))
    assert rev.report.passed
    assert "optional due date" in (result.out_dir / "PRD.md").read_text(encoding="utf-8")
    backups = list((result.out_dir / "revisions").iterdir())
    assert len(backups) == 1 and "due date" not in (backups[0] / "PRD.md").read_text(encoding="utf-8")
    assert "Add due dates" in (result.out_dir / "revision_log.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ synthesis units


def _dispute(sev, target="PRODUCT_UX"):
    return Dispute(target_agent=target, claim="c", severity=sev, category="OTHER", failure_mechanism="f", counterproposal="p")


def test_collect_disputes_assigns_ids_and_caps():
    from engineering_council.models import AgentReview
    reviews = {"RED_TEAM_QA": AgentReview(disputes=[_dispute("NITPICK")] * 3 + [_dispute("CRITICAL")] * 9 + [_dispute("MAJOR", target="NOBODY")])}
    formal, nits, warns = synthesis.collect_disputes(reviews, Settings(max_disputes_per_reviewer=6))
    assert [d.dispute_id for d in formal] == [f"DSP-{i:03d}" for i in range(1, 7)]
    assert not nits and warns
    assert all(d.source_agent == "RED_TEAM_QA" for d in formal)


def test_unknown_target_is_mapped_to_council():
    from engineering_council.models import AgentReview
    formal, _, _ = synthesis.collect_disputes({"RED_TEAM_QA": AgentReview(disputes=[_dispute("MAJOR", target="NOBODY")])}, Settings())
    assert formal[0].target_agent == "COUNCIL"


def test_dispute_coverage_drops_unknown_ids_and_adds_unresolved():
    d = Decision(decision_id="DEC-001", statement="s", chosen_option="c", rationale="r", status="DECIDED", dispute_ids=["DSP-001", "DSP-099"])
    out, warns = synthesis.ensure_dispute_coverage([d], {"DSP-001", "DSP-002"})
    assert out[0].dispute_ids == ["DSP-001"]
    assert out[1].status == "UNRESOLVED" and out[1].dispute_ids == ["DSP-002"] and out[1].decision_id == "DEC-002"
    assert len(warns) == 2


def test_find_cycles():
    assert synthesis.find_cycles({"A": ["B"], "B": ["A"]})
    assert not synthesis.find_cycles({"A": ["B"], "B": []})


# ------------------------------------------------------------------ storage


def test_atomic_write_leaves_no_temp_file(tmp_path):
    p = tmp_path / "x" / "a.json"
    storage.write_json(p, {"k": 1})
    storage.write_json(p, {"k": 2})
    assert json.loads(p.read_text())["k"] == 2
    assert [f.name for f in p.parent.iterdir()] == ["a.json"]


def test_corrupt_checkpoint_counts_as_not_done(tmp_path):
    (tmp_path / "meeting.json").write_text("{not json")
    assert storage.MeetingStore(tmp_path).state.stage == "created"


def test_council_rediscusses_after_human_answers(tmp_path):
    llm = FakeLLM()
    result = run(make_input(tmp_path), llm)
    out = result.out_dir
    for agent in ("SYSTEMS_ARCHITECT", "PRODUCT_UX", "PRAGMATIC_MVP", "RED_TEAM_QA"):
        assert llm.calls[f"rediscuss:{agent}"] == 1
        assert (out / "reconsiderations" / f"{agent}.json").exists()
    assert "Re-discussion after the human's answers" in (out / "minutes.md").read_text(encoding="utf-8")
