"""The whole team on real git, with real harnesses, driven by a scripted model."""

import asyncio
import json
from pathlib import Path

import pytest

from team.engine import TeamConfig, TeamEngine
from team.repo import TeamRepo
from tests.team.fake_llm import TeamLLM
from tests.team.test_build import finished_meeting

PLAN = {
    "features": [
        {"id": "db", "title": "Database layer", "owner": "DEV_6", "depends_on": [], "tasks": [{"title": "write db module", "details": "create db.py"}]},
        {"id": "ui", "title": "Screens", "owner": "DEV_1", "depends_on": [], "tasks": [{"title": "write ui module", "details": "create ui.py"}]},
        {"id": "api", "title": "API", "owner": "DEV_2", "depends_on": ["db"], "tasks": [{"title": "write api module", "details": "create api.py using db"}]},
    ]
}


def write(path, content):
    return ("tool", "write", {"path": path, "content": content})


def base_llm():
    llm = TeamLLM()
    llm.on(r"Turn the agreed specification", [("text", json.dumps(PLAN))])
    llm.on(r"Task: write db module", [write("db.py", "def connect():\n    return 'db'\n"), ("text", "db written")])
    llm.on(r"Task: write ui module", [write("ui.py", "def render():\n    return 'ui'\n"), ("text", "ui written")])
    llm.on(r"Task: write api module", [write("api.py", "from db import connect\n\ndef serve():\n    return connect()\n"), ("text", "api written")])
    return llm


def engine(tmp_path, llm, meeting=None, **cfg):
    meeting = meeting or finished_meeting(tmp_path)[0]
    config = TeamConfig(run_id="r1", repair_rounds=0, **cfg)
    events = []
    eng = TeamEngine(meeting, tmp_path / "team", llm=llm, config=config, on_event=lambda k, d: events.append((k, d)))
    return eng, events, meeting


def test_features_run_in_parallel_merge_in_dependency_order_and_main_is_untouched(tmp_path):
    llm = base_llm()
    eng, events, meeting = engine(tmp_path, llm)
    result = asyncio.run(eng.run())

    assert [f.status for f in result.features] == ["merged", "merged", "merged"]
    assert result.passed and result.final_branch == "final/r1"
    repo = TeamRepo(tmp_path / "team" / "remote")
    branches = repo.branches("viewer")
    assert {"main", "integration/r1", "final/r1", "feature/db", "feature/ui", "feature/api"} <= set(branches)
    # the final branch has everyone's work plus the seeded specification; main has none of it
    for f in ("db.py", "ui.py", "api.py", "AGENTS.md", "docs/Design.md"):
        assert repo.file_at("viewer", "origin/final/r1", f) is not None, f
    assert repo.file_at("viewer", "origin/main", "db.py") is None and repo.file_at("viewer", "origin/main", "AGENTS.md") is None
    # api started only after db was merged: its branch contains db.py
    assert repo.file_at("viewer", "origin/feature/api", "db.py") is not None
    # ui did not wait for db
    assert repo.file_at("viewer", "origin/feature/ui", "db.py") is None
    started = [d["feature"] for k, d in events if k == "feature-started"]
    assert set(started[:2]) == {"db", "ui"} and started[2] == "api"
    report = (meeting / "team_report.md").read_text(encoding="utf-8")
    assert "final/r1" in report and "Nothing has been merged into main" in report


def test_each_developer_works_only_in_their_own_clone(tmp_path):
    eng, _, _ = engine(tmp_path, base_llm())
    asyncio.run(eng.run())
    sandboxes = tmp_path / "team" / "remote" / "sandboxes"
    assert (sandboxes / "dev-6").is_dir() and (sandboxes / "dev-1").is_dir() and (sandboxes / "dev-2").is_dir() and (sandboxes / "integrator").is_dir()
    # db.py was written in DEV_6's clone, not DEV_1's
    assert (sandboxes / "dev-6" / "db.py").exists() and not (sandboxes / "dev-1" / "db.py").exists()


def test_the_scrum_masters_bad_plan_falls_back_to_the_specification_sequence(tmp_path):
    llm = base_llm()
    llm.rules[0] = (llm.rules[0][0], [("text", "I could not decide.")])
    eng, _, _ = engine(tmp_path, llm)
    eng.cfg.planning_attempts = 2
    llm.on(r"Task: ", [("text", "nothing to do")])
    result = asyncio.run(eng.run())
    assert any("plan was unusable" in w for w in result.warnings)
    assert len(result.features) == len(eng.spec.implementation_sequence)


def test_a_cyclic_plan_is_sent_back_with_the_reason(tmp_path):
    cyclic = {"features": [
        {"id": "a", "title": "A", "depends_on": ["b"], "tasks": [{"title": "write db module"}]},
        {"id": "b", "title": "B", "depends_on": ["a"], "tasks": [{"title": "write ui module"}]},
    ]}
    seen = []

    def planner(text):
        seen.append(text)
        return [("text", json.dumps(cyclic if len(seen) == 1 else PLAN))]

    llm = base_llm()
    llm.rules[0] = (llm.rules[0][0], planner)
    eng, _, _ = engine(tmp_path, llm)
    result = asyncio.run(eng.run())
    assert "dependency cycle: a -> b -> a" in seen[1] and [f.id for f in result.features] == ["db", "ui", "api"]


def test_a_failing_feature_blocks_its_dependents_but_not_the_rest(tmp_path):
    llm = base_llm()
    llm.rules[1] = (llm.rules[1][0], [("text", "I give up")])  # db writes nothing... and still "succeeds"
    llm.on(r"Task: write db module", [("tool", "read", {"path": "does-not-exist.txt"}), ("text", "x")])
    eng, _, _ = engine(tmp_path, llm)
    result = asyncio.run(eng.run())
    by_id = {f.id: f for f in result.features}
    assert by_id["ui"].status == "merged"
    assert result.final_branch == "final/r1"


def test_a_merge_conflict_is_talked_through_and_resolved(tmp_path):
    plan = {"features": [
        {"id": "left", "title": "Left", "owner": "DEV_1", "tasks": [{"title": "write left", "details": "shared.txt"}]},
        {"id": "right", "title": "Right", "owner": "DEV_2", "tasks": [{"title": "write right", "details": "shared.txt"}]},
    ]}
    llm = TeamLLM()
    llm.on(r"Turn the agreed specification", [("text", json.dumps(plan))])
    llm.on(r"Task: write left", [write("shared.txt", "greeting = 'left'\n"), ("text", "left done")])
    llm.on(r"Task: write right", [write("shared.txt", "greeting = 'right'\n"), ("text", "right done")])
    llm.on(r"produced conflicts", [("text", "Keep both greetings, one per line.")])
    llm.on(r"You are merging", [write("shared.txt", "greeting_left = 'left'\ngreeting_right = 'right'\n"), ("text", "combined both greetings")])
    eng, events, _ = engine(tmp_path, llm)
    result = asyncio.run(eng.run())

    assert [f.status for f in result.features] == ["merged", "merged"]
    assert sum(f.conflicts for f in result.features) == 1
    repo = TeamRepo(tmp_path / "team" / "remote")
    merged = repo.file_at("viewer", "origin/final/r1", "shared.txt")
    assert merged == "greeting_left = 'left'\ngreeting_right = 'right'\n"
    talk = [d for k, d in events if k == "conflict-talk"]
    assert talk and len(talk[0]["with_"]) >= 1  # the integrator consulted the developers involved
    assert any("Keep both greetings" in str(r.messages) for r in llm.requests)


def test_an_unresolvable_conflict_fails_the_feature_and_leaves_integration_clean(tmp_path):
    plan = {"features": [
        {"id": "left", "title": "Left", "owner": "DEV_1", "tasks": [{"title": "write left"}]},
        {"id": "right", "title": "Right", "owner": "DEV_2", "tasks": [{"title": "write right"}]},
    ]}
    llm = TeamLLM()
    llm.on(r"Turn the agreed specification", [("text", json.dumps(plan))])
    llm.on(r"Task: write left", [write("s.txt", "left\n"), ("text", "ok")])
    llm.on(r"Task: write right", [write("s.txt", "right\n"), ("text", "ok")])
    llm.on(r"produced conflicts", [("text", "no idea")])
    llm.on(r"You are merging", [("text", "I did nothing")])  # leaves the markers in place
    eng, _, _ = engine(tmp_path, llm, conflict_rounds=2)
    result = asyncio.run(eng.run())
    assert sorted(f.status for f in result.features) == ["failed", "merged"]
    repo = TeamRepo(tmp_path / "team" / "remote")
    assert "<<<<<<<" not in (repo.file_at("viewer", "origin/final/r1", "s.txt") or "")
    assert not repo.merging("integrator")


def test_design_change_meeting_records_an_adr_that_lands_with_the_feature(tmp_path):
    plan = {"features": [{"id": "core", "title": "Core", "owner": "DEV_2", "tasks": [{"title": "write core", "details": "needs a new contract"}]}]}
    llm = TeamLLM()
    llm.on(r"Turn the agreed specification", [("text", json.dumps(plan))])
    llm.on(r"Task: write core", [
        ("tool", "design_change", {"title": "Use event bus", "reason": "components need decoupling", "change": "add an EventBus contract"}),
        write("core.py", "BUS = True\n"), ("text", "built core with the bus"),
    ])
    llm.on(r"proposes a design change", [("text", json.dumps({"vote": "approve", "comment": "makes sense"}))])
    eng, _, _ = engine(tmp_path, llm)
    result = asyncio.run(eng.run())
    assert len(result.decisions) == 1 and result.decisions[0].approved and len(result.decisions[0].votes) == 6  # five developers and the integrator... minus the proposer
    adr = result.decisions[0].adr
    assert adr == "docs/adr/0001-use-event-bus.md"
    repo = TeamRepo(tmp_path / "team" / "remote")
    assert "components need decoupling" in repo.file_at("viewer", "origin/final/r1", adr)


def test_a_rejected_design_change_leaves_no_adr(tmp_path):
    plan = {"features": [{"id": "core", "title": "Core", "owner": "DEV_2", "tasks": [{"title": "write core"}]}]}
    llm = TeamLLM()
    llm.on(r"Turn the agreed specification", [("text", json.dumps(plan))])
    llm.on(r"Task: write core", [("tool", "design_change", {"title": "Rewrite everything", "reason": "taste", "change": "all of it"}), ("text", "gave up on it")])
    llm.on(r"proposes a design change", [("text", json.dumps({"vote": "reject", "comment": "no"}))])
    eng, _, _ = engine(tmp_path, llm)
    result = asyncio.run(eng.run())
    assert not result.decisions[0].approved and result.decisions[0].adr is None
    repo = TeamRepo(tmp_path / "team" / "remote")
    assert repo.file_at("viewer", "origin/final/r1", "docs/adr/0001-rewrite-everything.md") is None


def test_resume_does_not_redo_merged_features(tmp_path):
    llm = base_llm()
    eng, _, meeting = engine(tmp_path, llm)
    asyncio.run(eng.run())
    first_calls = len(llm.requests)
    again = base_llm()
    eng2, events, _ = engine(tmp_path, again, meeting=meeting)
    asyncio.run(eng2.run())
    assert not [k for k, _ in events if k == "feature-started"]  # everything was already merged
    assert len(again.requests) < first_calls
