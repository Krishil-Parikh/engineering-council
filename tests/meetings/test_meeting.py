import asyncio
import json

import pytest

from meetings import storage, synthesis
from meetings.config import Settings
from meetings.meeting import MeetingError, Reporter, revise_meeting, run_meeting
from meetings.models import Decision, Dispute, MeetingInput
from tests.meetings.fakes import FakeLLM

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
    assert sorted(p.stem for p in (out / "proposals").glob("*.json")) == sorted(f"DEV_{i}" for i in range(1, 7))
    # blind thinking and skill lens come from the same six developers; the conversation is not fixed rounds
    assert all(llm.calls[f"blind:DEV_{i}"] == 1 and llm.calls[f"proposal:DEV_{i}"] == 1 for i in range(1, 7))
    talks = {i: sum(n for k, n in llm.calls.items() if k.startswith("talk") and k.endswith(f":DEV_{i}")) for i in range(1, 7)}
    assert all(n >= 2 for n in talks.values()), talks  # everyone spoke more than once
    assert len(list((out / "conversation").glob("segment-*.json"))) >= 2
    assert json.loads((out / "roster.json").read_text())["skills"] == {
        "DEV_1": "FRONTEND", "DEV_2": "BACKEND", "DEV_3": "AIML", "DEV_4": "MLOPS", "DEV_5": "DEVOPS", "DEV_6": "DATABASE"}
    # the developer who was objected to answers it themself, in their own turn, not via a separate rebuttal agent
    segs = " ".join(p.read_text(encoding="utf-8") for p in (out / "conversation").glob("segment-*.json"))
    assert "DSP-001" in segs and "ACCEPT" in segs
    minutes = (out / "minutes.md").read_text(encoding="utf-8")
    assert "DSP-001" in minutes and "Part 4 — The conversation" in minutes and "Part 2 — Skills picked" in minutes


def test_question_gate_never_exceeds_five(tmp_path):
    run(make_input(tmp_path), FakeLLM())
    saved = json.loads((tmp_path / "todo-cli" / "questions.json").read_text())
    assert len(saved["answers"]) <= 5


def test_one_failed_agent_is_reported_not_hidden(tmp_path):
    result = run(make_input(tmp_path), FakeLLM(fail_stages=("proposal:DEV_4",)))
    assert any("DEV_4" in w and "did not contribute" in w for w in result.warnings)
    assert not (result.out_dir / "proposals" / "DEV_4.json").exists()
    assert "Absent" in (result.out_dir / "minutes.md").read_text(encoding="utf-8")


def test_transient_proposal_failure_gets_one_second_chance(tmp_path):
    llm = FakeLLM(fail_once=("proposal:DEV_4",))
    result = run(make_input(tmp_path), llm)
    assert llm.calls["proposal:DEV_4"] == 2 or (result.out_dir / "proposals" / "DEV_4.json").exists()
    assert (result.out_dir / "proposals" / "DEV_4.json").exists()
    assert not any("did not contribute" in w for w in result.warnings)


def test_below_quorum_stops_but_keeps_completed_work(tmp_path):
    llm = FakeLLM(fail_stages=("proposal:DEV_4", "proposal:DEV_2", "proposal:DEV_5"))
    with pytest.raises(MeetingError, match="quorum"):
        run(make_input(tmp_path), llm)
    out = tmp_path / "todo-cli"
    assert (out / "proposals" / "DEV_1.json").exists()
    assert json.loads((out / "meeting.json").read_text())["status"] == "failed"


def test_resume_skips_completed_stages(tmp_path):
    with pytest.raises(Exception):
        run(make_input(tmp_path), FakeLLM(fail_stages=("decisions",)))
    llm = FakeLLM()
    result = run(make_input(tmp_path), llm, resume=True)
    assert result.report.passed
    assert llm.calls["proposal:DEV_1"] == 0 and llm.calls["review:DEV_4"] == 0
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


def _dispute(sev, target="DEV_2"):
    return Dispute(target_agent=target, claim="c", severity=sev, category="OTHER", failure_mechanism="f", counterproposal="p")


def test_collect_disputes_assigns_ids_and_caps():
    from meetings.models import AgentReview
    reviews = {"DEV_4": AgentReview(disputes=[_dispute("NITPICK")] * 3 + [_dispute("CRITICAL")] * 9 + [_dispute("MAJOR", target="NOBODY")])}
    formal, nits, warns = synthesis.collect_disputes(reviews, Settings(max_disputes_per_reviewer=6))
    assert [d.dispute_id for d in formal] == [f"DSP-{i:03d}" for i in range(1, 7)]
    assert not nits and warns
    assert all(d.source_agent == "DEV_4" for d in formal)


def test_unknown_target_is_mapped_to_council():
    from meetings.models import AgentReview
    formal, _, _ = synthesis.collect_disputes({"DEV_4": AgentReview(disputes=[_dispute("MAJOR", target="NOBODY")])}, Settings())
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
    for agent in (f"DEV_{i}" for i in range(1, 7)):
        assert llm.calls[f"rediscuss:{agent}"] == 1
        assert (out / "reconsiderations" / f"{agent}.json").exists()
    assert "Rethink after the human's answers" in (out / "minutes.md").read_text(encoding="utf-8")


def test_skill_assignment_gives_everyone_a_distinct_skill_even_on_clashes():
    from meetings.conversation import assign_skills
    from meetings.models import BlindThoughts, SKILLS
    same = {f"DEV_{i}": BlindThoughts(agent_id=f"DEV_{i}", understanding="u", skill_preferences=["backend", "AI/ML", "db"]) for i in range(1, 7)}
    roster = assign_skills(same, [f"DEV_{i}" for i in range(1, 7)])
    assert sorted(roster.values()) == sorted(SKILLS)
    assert roster["DEV_1"] == "BACKEND" and roster["DEV_2"] == "AIML" and roster["DEV_3"] == "DATABASE"


def test_later_speakers_hear_what_was_just_said_and_the_flow_is_not_rounds(tmp_path):
    prompts_seen = []

    class Spy(FakeLLM):
        async def _make(self, prompt, schema, stage):
            if stage.startswith("talk"):
                prompts_seen.append((stage, prompt))
            return await super()._make(prompt, schema, stage)

    run(make_input(tmp_path), Spy())
    assert "(nothing yet since the scrum master spoke)" in prompts_seen[0][1]
    assert "speaks in part 1" in prompts_seen[1][1]  # the second speaker heard the first
    first_speakers = [st.split(":")[1] for st, _ in prompts_seen[:3]]
    assert len(set(first_speakers)) == 3  # nobody monopolises the opening


def test_addressed_developer_is_called_on_next():
    from collections import Counter
    from meetings.conversation import pick_speaker
    from meetings.models import AgentTurn, ScrumNote, Utterance
    agents = [f"DEV_{i}" for i in range(1, 7)]
    spoken = Counter({a: 3 for a in agents})
    recent = [AgentTurn(agent_id="DEV_1", utterances=[Utterance(to="DEV_5", kind="CHALLENGE", text="x")])]
    nxt = pick_speaker(agents, spoken, "DEV_1", recent, {}, set(), ScrumNote(summary="s"), 2)
    assert nxt == "DEV_5"
    # someone who passed and was not addressed is not asked again
    assert pick_speaker(["DEV_2"], Counter({"DEV_2": 3}), "DEV_1", [], {}, {"DEV_2"}, ScrumNote(summary="s"), 2) is None


def test_conversation_ends_by_itself_when_everyone_has_nothing_to_add(tmp_path):
    from meetings.models import AgentTurn

    class Quiet(FakeLLM):
        async def _make(self, prompt, schema, stage):
            self.calls[stage] += 0
            if schema is AgentTurn and "talk1" not in stage:
                self.calls[stage] += 1
                return AgentTurn(agent_id="x", pass_turn=True)
            return await super()._make(prompt, schema, stage)

    result = run(make_input(tmp_path), Quiet())
    assert result.report.passed
    assert len(list((result.out_dir / "conversation").glob("segment-*.json"))) <= 4


def test_unanswered_objection_is_reported(tmp_path):
    dead = tuple(f"talk{n}:DEV_3" for n in range(1, 12))
    result = run(make_input(tmp_path), FakeLLM(fail_stages=dead))
    assert any("never answered" in w and "DSP-001" in w for w in result.warnings)


# --------------------------------------------------------------------------- diagrams and design review


def test_documents_carry_valid_mermaid_diagrams_and_the_directory_tree(tmp_path):
    from meetings import mermaid

    out = run(make_input(tmp_path), FakeLLM()).out_dir
    for name in ("PRD.md", "Technical_Approach.md", "Design.md"):
        text = (out / name).read_text(encoding="utf-8")
        blocks = mermaid.BLOCK.findall(text)
        assert blocks, name
        assert all(not mermaid.lint(b) for b in blocks), (name, [mermaid.lint(b) for b in blocks])
        assert "todo-cli/" in text, name  # the directory structure appears in each document
    assert "Part 6" in (out / "minutes.md").read_text(encoding="utf-8")


def test_invalid_model_diagram_is_replaced_by_one_built_from_the_components():
    from meetings import mermaid

    from tests.meetings.fakes import draft_spec

    bad = "flowchart TD" + chr(10) + "  A[(broken"
    spec = synthesis.finalize_spec(draft_spec().model_copy(update={"architecture_diagram": bad}), [])
    assert not mermaid.lint(spec.architecture_diagram)
    assert not mermaid.mentions(spec.architecture_diagram, [c.name for c in spec.components])


def test_design_review_applies_requests_then_asks_again(tmp_path):
    from meetings.models import DesignVote

    llm = FakeLLM()

    def vote(prompt, stage):
        agent = stage.split(":")[1]
        if stage.startswith("design1") and agent == "DEV_5":
            return DesignVote(agent_id=agent, directory_ok=False, directory_changes=["Add a docs/ folder"])
        return DesignVote(agent_id=agent)

    llm.overrides[DesignVote] = vote
    result = run(make_input(tmp_path), llm)
    review = json.loads((result.out_dir / "design_review.json").read_text())
    assert len(review["rounds"]) == 2 and review["agreed"] is True
    assert llm.calls["design1:revise"] == 1
    assert result.report.passed
    assert "Add a docs/ folder" in (result.out_dir / "minutes.md").read_text(encoding="utf-8")
