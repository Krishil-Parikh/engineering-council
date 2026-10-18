"""The whole team on real git, with real harnesses, driven by a scripted model."""

import asyncio
import json
from pathlib import Path

import pytest

from memory import LessonStore
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
    cfg.setdefault("plan_discussion_rounds", 0)  # most tests are not about the planning talk; it adds one consultation per developer
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


def audit(tmp_path):
    path = tmp_path / "team" / "a2a-audit.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_conflict_talk_and_planning_travel_over_a2a(tmp_path):
    plan = {"features": [
        {"id": "left", "title": "Left", "owner": "DEV_1", "tasks": [{"title": "write left"}]},
        {"id": "right", "title": "Right", "owner": "DEV_2", "tasks": [{"title": "write right"}]},
    ]}
    llm = TeamLLM()
    llm.on(r"Turn the agreed specification", [("text", json.dumps(plan))])
    llm.on(r"Task: write left", [write("shared.txt", "a = 'left'\n"), ("text", "ok")])
    llm.on(r"Task: write right", [write("shared.txt", "a = 'right'\n"), ("text", "ok")])
    llm.on(r"produced conflicts", [("text", "keep both")])
    llm.on(r"You are merging", [write("shared.txt", "a_left = 'left'\na_right = 'right'\n"), ("text", "combined")])
    eng, _, _ = engine(tmp_path, llm)
    result = asyncio.run(eng.run())
    assert [f.status for f in result.features] == ["merged", "merged"]
    log = audit(tmp_path)
    assert any(e["topic"] == "work plan" and e["sender"] == "system" and e["recipient"] == "integrator" for e in log)
    talks = [e for e in log if e["topic"].startswith("merge conflict in")]
    assert talks and all(e["sender"] == "integrator" and e["reply"] == "keep both" for e in talks)
    assert {e["recipient"] for e in talks} >= {"DEV_1"} or {e["recipient"] for e in talks} >= {"DEV_2"}


def test_design_votes_are_a2a_messages_to_every_other_developer(tmp_path):
    plan = {"features": [{"id": "core", "title": "Core", "owner": "DEV_2", "tasks": [{"title": "write core"}]}]}
    llm = TeamLLM()
    llm.on(r"Turn the agreed specification", [("text", json.dumps(plan))])
    llm.on(r"Task: write core", [("tool", "design_change", {"title": "Use bus", "reason": "r", "change": "c"}), write("core.py", "x = 1\n"), ("text", "ok")])
    llm.on(r"proposes a design change", [("text", json.dumps({"vote": "approve", "comment": "fine"}))])
    eng, _, _ = engine(tmp_path, llm)
    asyncio.run(eng.run())
    votes = [e for e in audit(tmp_path) if e["topic"].startswith("design change:")]
    assert {e["recipient"] for e in votes} == {"DEV_1", "DEV_3", "DEV_4", "DEV_5", "DEV_6", "integrator"} and all(e["sender"] == "DEV_2" for e in votes)
    assert len({e["context_id"] for e in votes}) == 1  # one meeting, one conversation


def test_local_transport_still_works_without_a2a(tmp_path):
    eng, _, _ = engine(tmp_path, base_llm(), transport="local")
    result = asyncio.run(eng.run())
    assert result.passed and not (tmp_path / "team" / "a2a-audit.jsonl").exists()


# ------------------------------------------------------------------ memory

def conflict_llm(extra=None):
    plan = {"features": [
        {"id": "left", "title": "Left", "owner": "DEV_1", "tasks": [{"title": "write left"}]},
        {"id": "right", "title": "Right", "owner": "DEV_2", "tasks": [{"title": "write right"}]},
    ]}
    llm = TeamLLM()
    llm.on(r"Turn the agreed specification", [("text", json.dumps(plan))])
    llm.on(r"Task: write left", [write("shared.txt", "a = 'left'\n"), ("text", "ok")])
    llm.on(r"Task: write right", [write("shared.txt", "a = 'right'\n"), ("text", "ok")])
    llm.on(r"produced conflicts", [("text", "keep both")])
    llm.on(r"You are merging", [write("shared.txt", "a_left = 'left'\na_right = 'right'\n"), ("text", "combined")])
    if extra:
        extra(llm)
    return llm


def renamed_meeting(tmp_path, name):
    tmp_path.mkdir(parents=True, exist_ok=True)
    meeting, spec = finished_meeting(tmp_path)
    (meeting / "specification.json").write_text(spec.model_copy(update={"project_name": name}).model_dump_json(), encoding="utf-8")
    return meeting


def test_codemap_and_project_log_are_kept_on_the_integration_branch(tmp_path):
    eng, _, _ = engine(tmp_path, base_llm())
    asyncio.run(eng.run())
    repo = TeamRepo(tmp_path / "team" / "remote")
    codemap = repo.file_at("viewer", "origin/final/r1", "docs/CODEMAP.md")
    memory = repo.file_at("viewer", "origin/final/r1", "docs/MEMORY.md")
    assert "`db.py`" in codemap and "def connect" in codemap and "`api.py`" in codemap and "`ui.py`" in codemap
    assert "Merged Database layer" in memory and "owner DEV_6" in memory and "files: " in memory and "db.py" in memory
    assert memory.index("Merged Database layer") < memory.index("Merged API")  # the API depends on the database, so it merges later
    assert "docs/CODEMAP.md" in repo.file_at("viewer", "origin/final/r1", "AGENTS.md")


def test_a_developer_starting_a_dependent_feature_is_told_what_exists(tmp_path):
    llm = base_llm()
    eng, _, _ = engine(tmp_path, llm)
    asyncio.run(eng.run())
    api_prompt = next(str(r.messages) for r in llm.requests if "Task: write api module" in str(r.messages))
    assert "What the team already knows" in api_prompt and "db.py" in api_prompt and "Merged Database layer" in api_prompt


def test_lessons_carry_from_one_project_to_the_next_and_become_skills(tmp_path):
    memory_dir = tmp_path / "memory"

    def reflect(llm):
        llm.on(r"Reflect on how the work went", [("text", json.dumps({"lessons": [{"text": "Agree the shared file layout before parallel work starts.", "skill": "", "tags": ["plan"]}]}))])

    # first project: a conflict happens, the team learns from it
    one = TeamEngine(renamed_meeting(tmp_path / "a", "Alpha"), tmp_path / "a" / "team", llm=conflict_llm(reflect), config=TeamConfig(run_id="r1", repair_rounds=0, plan_discussion_rounds=0, memory_dir=memory_dir))
    r1 = asyncio.run(one.run())
    assert r1.lessons_learned >= 2
    store = LessonStore(memory_dir)
    texts = [l.text for l in store.lessons]
    assert any("collided in shared.txt" in t for t in texts) and any("Agree the shared file layout" in t for t in texts)
    assert store.profiles["FRONTEND"].projects == 1 and store.profiles["BACKEND"].conversations == 1
    assert not list((memory_dir / "skills").glob("*"))  # seen on only one project: not yet a skill

    # second project: the planner is shown the lesson, and the same conflict makes it a skill
    llm2 = conflict_llm(reflect)
    two = TeamEngine(renamed_meeting(tmp_path / "b", "Beta"), tmp_path / "b" / "team", llm=llm2, config=TeamConfig(run_id="r2", repair_rounds=0, plan_discussion_rounds=0, memory_dir=memory_dir))
    asyncio.run(two.run())
    plan_prompt = next(str(r.messages) for r in llm2.requests if "Turn the agreed specification" in str(r.messages))
    assert "Lessons from earlier projects" in plan_prompt and "collided in shared.txt" in plan_prompt
    skill_files = list((memory_dir / "skills").glob("*/SKILL.md"))
    assert skill_files and "collided in shared.txt" in skill_files[0].read_text(encoding="utf-8")

    # third project: developers get the learned skill in their harness and their experience in their persona
    llm3 = conflict_llm(reflect)
    three = TeamEngine(renamed_meeting(tmp_path / "c", "Gamma"), tmp_path / "c" / "team", llm=llm3, config=TeamConfig(run_id="r3", repair_rounds=0, plan_discussion_rounds=0, memory_dir=memory_dir))
    asyncio.run(three.run())
    assert (tmp_path / "c" / "team" / "data" / "dev-1" / "skills" / skill_files[0].parent.name / "SKILL.md").exists()
    system = " ".join(p.text for r in llm3.requests for p in r.system)
    assert "Experience: 2 earlier project(s)" in system


def test_without_a_memory_directory_nothing_is_written_outside_the_project(tmp_path):
    eng, _, _ = engine(tmp_path, base_llm())
    result = asyncio.run(eng.run())
    assert eng.lessons is None and result.lessons_learned == 0


# ------------------------------------------------------------------ planning as a team discussion

def test_the_plan_is_written_after_the_developers_talk_it_through(tmp_path):
    llm = base_llm()

    def talk(text):
        speaker = text.split("It is your turn, ")[1].split(" ")[0]
        return [("text", f"{speaker}: I will take my area, and the database must exist before the API.")]

    llm.on(r"Group conversation about: work plan", talk)
    eng, events, _ = engine(tmp_path, llm, plan_discussion_rounds=1)
    result = asyncio.run(eng.run())
    assert [f.status for f in result.features] == ["merged", "merged", "merged"]
    plan_prompt = next(request_text(r) for r in llm.requests if "Turn the agreed specification" in request_text(r))
    assert "THE TEAM'S DISCUSSION" in plan_prompt
    for dev in ("DEV_1", "DEV_2", "DEV_3", "DEV_4", "DEV_5", "DEV_6"):
        assert f"{dev}: {dev}: I will take my area" in plan_prompt
    assert [k for k, _ in events].count("plan-discussion") == 1
    log = audit(tmp_path)
    turns = [e for e in log if e["topic"] == "work plan" and e["sender"] == "system" and e["recipient"].startswith("DEV_")]
    assert [e["recipient"] for e in turns] == ["DEV_1", "DEV_2", "DEV_3", "DEV_4", "DEV_5", "DEV_6"]  # one after another
    assert len({e["context_id"] for e in turns}) == 1  # one conversation
    assert "DEV_1: DEV_1: I will take my area" in turns[-1]["text"]  # the last speaker saw the first speaker's turn


def request_text(request):
    """The text of a model request's messages, as the model reads it (repr() would escape the apostrophes)."""
    return "\n".join(p.text for m in request.messages for p in m.content if hasattr(p, "text"))


def test_a_failing_discussion_does_not_stop_the_plan(tmp_path):
    eng, _, _ = engine(tmp_path, base_llm(), plan_discussion_rounds=1, transport="local")

    async def broken(*a, **kw):
        raise RuntimeError("network down")

    eng.channel.converse = broken
    result = asyncio.run(eng.run())
    assert [f.status for f in result.features] == ["merged", "merged", "merged"]
    assert any("planning discussion failed: network down" in w for w in result.warnings)
