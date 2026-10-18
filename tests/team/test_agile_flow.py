"""A whole agile run on real git, with real harnesses and a scripted model: sprints, standups, review, report, retrospective, document sync,
a human interruption, and the promise that nobody codes while the team is in a ceremony."""

import asyncio
import json

from team.agile.ceremonies import AgileConfig
from team.engine import TeamConfig, TeamEngine
from team.repo import TeamRepo
from tests.team.fake_llm import TeamLLM
from tests.team.test_build import finished_meeting

PLAN = {
    "features": [
        {"id": "db", "title": "Database layer", "owner": "DEV_6", "depends_on": [], "tasks": [{"title": "write db module", "details": "create db.py"}, {"title": "test db module", "details": "create test_db.py"}]},
        {"id": "ui", "title": "Screens", "owner": "DEV_1", "depends_on": [], "tasks": [{"title": "write ui module", "details": "create ui.py"}, {"title": "test ui module", "details": "create test_ui.py"}]},
        {"id": "api", "title": "API", "owner": "DEV_2", "depends_on": ["db"], "tasks": [{"title": "write api module", "details": "create api.py using db"}]},
    ]
}


def write(path, content):
    return ("tool", "write", {"path": path, "content": content})


class RecordingLLM(TeamLLM):
    """Notes every request that comes from a developer's work session, in the same timeline as the engine's events."""

    def __init__(self, timeline):
        super().__init__()
        self.timeline = timeline

    async def stream(self, request):
        last = next((m for m in reversed(request.messages) if m.role == "user"), None)
        text = self._text(last) if last else ""
        if text.startswith("Feature:") and "Task:" in text:
            self.timeline.append(("work", text.split("Task:")[1].split("\n")[0].strip()))
        async for ev in super().stream(request):
            yield ev


def agile_llm(timeline):
    llm = RecordingLLM(timeline)
    llm.on(r"Turn the agreed specification", [("text", json.dumps(PLAN))])
    # work
    llm.on(r"Task: write db module", [write("db.py", "def connect():\n    return 'db'\n"), ("text", "db written")])
    llm.on(r"Task: test db module", [write("test_db.py", "from db import connect\n\n\ndef test_connect():\n    assert connect() == 'db'\n"), ("text", "db tested")])
    llm.on(r"Task: write ui module", [write("ui.py", "def render():\n    return 'ui'\n"), ("text", "ui written")])
    llm.on(r"Task: test ui module", [write("test_ui.py", "from ui import render\n\n\ndef test_render():\n    assert render() == 'ui'\n"), ("text", "ui tested")])
    llm.on(r"Task: write api module", [write("api.py", "from db import connect\n\n\ndef serve():\n    return connect()\n"), ("text", "api written")])
    # ceremonies
    llm.on(r"SPRINT PLANNING for sprint 1", [("text", json.dumps({"goal": "Storage and screens work", "features": ["db", "ui"], "rationale": "independent, so both can start"}))])
    llm.on(r"SPRINT PLANNING for sprint 2", [("text", json.dumps({"goal": "The API serves data", "features": ["api"], "rationale": "db is merged"}))])
    llm.on(r"SPRINT PLANNING, sprint", [("text", json.dumps({"commit": True, "concerns": ""}))])
    llm.on(r"DAILY STANDUP SUMMARY", [("text", json.dumps({"summary": "Work is on track.", "resolutions": [{"impediment": "IMP-001", "resolved": True, "instruction": "Use plain functions, no classes."}]}))])
    llm.on(r"DAILY STANDUP, sprint 1, day 1.*You are DEV_1", [("text", json.dumps({"done": "Wrote the ui module", "next": "tests", "blockers": "unsure whether to use classes or functions"}))])
    llm.on(r"DAILY STANDUP, sprint", [("text", json.dumps({"done": "Worked on my feature", "next": "continue", "blockers": "none"}))])
    llm.on(r"SPRINT REVIEW, sprint \d+\. You are the scrum master", [("text", json.dumps({"goal_met": True, "summary": "The increment works.", "carry_over": []}))])
    llm.on(r"SPRINT REVIEW, sprint \d+\. You are", [("text", json.dumps({"demo": "My feature works", "missing": "nothing", "warning": ""}))])
    llm.on(r"SPRINT REPORT, sprint", [("text", json.dumps({"narrative": "A steady sprint."}))])
    llm.on(r"SPRINT RETROSPECTIVE, sprint \d+\. You are the scrum master", [("text", json.dumps({"went_well": ["parallel work"], "went_badly": ["unclear style rule"], "actions": [{"action": "Agree the code style before starting", "owner": "team"}], "lesson": "Agree the code style before parallel work."}))])
    llm.on(r"SPRINT RETROSPECTIVE, sprint \d+\. You are", [("text", json.dumps({"went_well": "tests first", "went_badly": "none", "change": "agree style first"}))])
    llm.on(r"DOCUMENT SYNC after sprint 1", [("text", json.dumps({"amendments": [
        {"doc": "Design.md", "change": "Add a note that db.py exposes connect()", "why": "it was built", "major": False},
        {"doc": "PRD.md", "change": "Add a requirement for an admin screen", "why": "the team thinks it is needed", "major": True},
    ]}))])
    llm.on(r"DOCUMENT SYNC after sprint", [("text", json.dumps({"amendments": []}))])
    llm.on(r"You are updating the project documents", [("tool", "write", {"path": "docs/AMENDED.md", "content": "amendments applied\n"}), ("text", "docs/AMENDED.md")])
    return llm


def run_agile(tmp_path, llm, timeline, **agile):
    meeting = finished_meeting(tmp_path)[0]
    cfg = TeamConfig(run_id="r1", repair_rounds=0, plan_discussion_rounds=0, agile=AgileConfig(approvals="approve", default_capacity=4, max_days=4, **agile))
    eng = TeamEngine(meeting, tmp_path / "team", llm=llm, config=cfg, on_event=lambda k, d: timeline.append((k, d)))
    return eng


def kinds(timeline):
    return [k for k, _ in timeline]


def test_a_whole_agile_run_produces_every_document_and_nobody_codes_during_a_ceremony(tmp_path):
    timeline = []
    eng = run_agile(tmp_path, agile_llm(timeline), timeline)
    result = asyncio.run(eng.run())

    assert [f.status for f in result.features] == ["merged", "merged", "merged"] and result.passed
    repo = TeamRepo(tmp_path / "team" / "remote")
    for path in (
        "docs/agile/product_backlog.md", "docs/agile/velocity.md", "docs/agile/impediments.md", "docs/agile/CHANGELOG.md", "docs/agile/human_directives.md",
        "docs/agile/sprint-01/sprint_backlog.md", "docs/agile/sprint-01/standups/standup-01.md", "docs/agile/sprint-01/review.md",
        "docs/agile/sprint-01/sprint_report.md", "docs/agile/sprint-01/retrospective.md",
        "docs/agile/sprint-02/sprint_backlog.md", "docs/agile/sprint-02/review.md", "docs/agile/sprint-02/sprint_report.md", "docs/agile/sprint-02/retrospective.md",
    ):
        assert repo.file_at("viewer", "origin/final/r1", path), path
    assert "Storage and screens work" in repo.file_at("viewer", "origin/final/r1", "docs/agile/sprint-01/sprint_backlog.md")
    assert "unsure whether to use classes" in repo.file_at("viewer", "origin/final/r1", "docs/agile/sprint-01/standups/standup-01.md")
    report = repo.file_at("viewer", "origin/final/r1", "docs/agile/sprint-01/sprint_report.md")
    assert "4/4 tasks" in report and "A steady sprint." in report
    assert [(n, planned, done) for n, _, planned, done in result.sprints] == [(1, 4, 4), (2, 1, 1)]

    # nobody coded between a freeze and the next thaw
    frozen = False
    for kind, data in timeline:
        if kind == "gate-freeze":
            frozen = True
        elif kind == "gate-thaw":
            frozen = False
        elif kind == "work":
            assert not frozen, f"a developer worked during a ceremony: {data}"
    assert kinds(timeline).count("gate-freeze") >= 4  # planning, then one per work day
    # the ceremonies really happened in order
    order = [k for k in kinds(timeline) if k in ("sprint-planned", "standup", "sprint-review", "sprint-report", "sprint-retro", "doc-sync")]
    assert order[0] == "sprint-planned" and "standup" in order
    assert order.index("sprint-review") < order.index("sprint-report") < order.index("sprint-retro") < order.index("doc-sync")


def test_every_ceremony_conversation_travels_over_a2a(tmp_path):
    timeline = []
    eng = run_agile(tmp_path, agile_llm(timeline), timeline)
    asyncio.run(eng.run())
    audit = [json.loads(l) for l in (tmp_path / "team" / "a2a-audit.jsonl").read_text(encoding="utf-8").splitlines()]
    topics = {e["topic"] for e in audit if e["sender"] == "scrum-master"}
    assert {"sprint 1 planning", "sprint 1 commitment", "standup 1", "standup 1 summary", "sprint 1 review", "sprint 1 retrospective", "sprint 1 document sync"} <= topics


def test_a_blocker_becomes_an_impediment_and_its_resolution_reaches_the_developer(tmp_path):
    timeline = []
    llm = agile_llm(timeline)
    eng = run_agile(tmp_path, llm, timeline)
    asyncio.run(eng.run())
    state = eng.agile.store.state
    imp = state.impediments[0]
    assert imp.dev == "DEV_1" and imp.status == "resolved" and "plain functions" in imp.resolution
    ui_second = next(str(r.messages) for r in llm.requests if "Task: test ui module" in str(r.messages))
    assert "plain functions, no classes" in ui_second  # briefed before the next task


def test_retrospective_actions_become_working_agreements_for_the_next_sprint(tmp_path):
    timeline = []
    llm = agile_llm(timeline)
    eng = run_agile(tmp_path, llm, timeline)
    asyncio.run(eng.run())
    assert eng.agile.store.state.agreements == ["Agree the code style before starting"]
    api = next(str(r.messages) for r in llm.requests if "Task: write api module" in str(r.messages))
    assert "Working agreements" in api and "Agree the code style before starting" in api


def test_major_document_changes_wait_for_the_human_and_routine_ones_do_not(tmp_path):
    timeline = []
    llm = agile_llm(timeline)
    meeting = finished_meeting(tmp_path)[0]
    cfg = TeamConfig(run_id="r1", repair_rounds=0, plan_discussion_rounds=0, agile=AgileConfig(approvals="ask", default_capacity=4))
    eng = TeamEngine(meeting, tmp_path / "team", llm=llm, config=cfg, on_event=lambda k, d: timeline.append((k, d)))
    asked = []

    def on_event(kind, data):
        timeline.append((kind, data))
        if kind == "approval-requested":
            asked.append(data)
            # the human answers: yes to the documents, no to the admin screen
            approve = "admin screen" not in data["title"] + data["detail"]
            asyncio.get_running_loop().call_soon(lambda: eng.agile.desk.answer(data["id"], approve, "" if approve else "not now"))

    eng.on_event = on_event
    result = asyncio.run(eng.run())
    assert [a["kind"] for a in asked][0] == "docs" and "Accept the project documents" in asked[0]["title"]  # the first documents are always asked
    admin = [a for a in asked if "admin screen" in a["detail"]]
    assert len(admin) == 1
    changelog = eng.agile.store.state.changelog
    assert any("admin screen" in c["change"] and c["by"] == "rejected by the human" for c in changelog)
    assert any("db.py exposes connect" in c["change"] and "routine" in c["by"] for c in changelog)
    assert result.passed


def test_the_first_documents_can_be_sent_back_and_are_revised(tmp_path):
    timeline = []
    llm = agile_llm(timeline)
    llm.on(r"asked for changes", [("tool", "write", {"path": "docs/PRD.md", "content": "# PRD\nrevised on feedback\n"}), ("text", "docs/PRD.md")])
    meeting = finished_meeting(tmp_path)[0]
    cfg = TeamConfig(run_id="r1", repair_rounds=0, plan_discussion_rounds=0, agile=AgileConfig(approvals="ask", default_capacity=4))
    eng = TeamEngine(meeting, tmp_path / "team", llm=llm, config=cfg, on_event=lambda k, d: timeline.append((k, d)))
    answers = iter([(False, "Add offline support to the PRD"), (True, "")])

    def on_event(kind, data):
        timeline.append((kind, data))
        if kind == "approval-requested":
            approve, text = ("admin screen" not in data["detail"], "") if data["kind"] != "docs" or "Accept" not in data["title"] else next(answers)
            asyncio.get_running_loop().call_soon(lambda: eng.agile.desk.answer(data["id"], approve, text))

    eng.on_event = on_event
    asyncio.run(eng.run())
    assert (meeting / "PRD.md").read_text(encoding="utf-8").startswith("# PRD\nrevised on feedback")  # the human reads the revision in the meeting folder
    assert eng.agile.store.state.docs_accepted
    assert any("Add offline support" in c["change"] for c in eng.agile.store.state.changelog)
    # development did not start before the second approval
    approvals = [i for i, (k, _) in enumerate(timeline) if k == "approval-requested"]
    first_work = next(i for i, (k, _) in enumerate(timeline) if k == "work")
    assert len(approvals) >= 2 and first_work > approvals[1]


def test_declining_the_documents_twice_stops_the_run_before_any_coding(tmp_path):
    import pytest

    from team.agile.playbook import AgileStopped

    timeline = []
    llm = agile_llm(timeline)
    llm.on(r"asked for changes", [("text", "nothing to change")])
    meeting = finished_meeting(tmp_path)[0]
    cfg = TeamConfig(run_id="r1", repair_rounds=0, plan_discussion_rounds=0, agile=AgileConfig(approvals="ask", approval_rounds=1))
    eng = TeamEngine(meeting, tmp_path / "team", llm=llm, config=cfg, on_event=lambda k, d: timeline.append((k, d)))

    def on_event(kind, data):
        timeline.append((kind, data))
        if kind == "approval-requested":
            asyncio.get_running_loop().call_soon(lambda: eng.agile.desk.answer(data["id"], False, "no"))

    eng.on_event = on_event
    with pytest.raises(AgileStopped):
        asyncio.run(eng.run())
    assert "work" not in kinds(timeline)


# ---------------------------------------------------------------------------------------------- the human interrupts


def interrupt_at_first_day(eng, timeline, text, kind):
    """The human interrupts as soon as the first work day starts, says something and lets the team carry on."""
    spoken = {}

    def on_event(k, d):
        timeline.append((k, d))
        if k == "day-start" and not spoken:
            spoken["started"] = True

            async def speak():
                await eng.agile.desk.interrupt()
                spoken["directive"] = await eng.agile.desk.say(text, kind)
                await eng.agile.desk.release()

            asyncio.get_running_loop().create_task(speak())

    eng.on_event = on_event
    return spoken


def test_an_interruption_with_a_note_freezes_the_team_and_reaches_every_developer(tmp_path):
    timeline = []
    llm = agile_llm(timeline)
    eng = run_agile(tmp_path, llm, timeline)
    spoken = interrupt_at_first_day(eng, timeline, "Keep every function under ten lines.", "note")
    result = asyncio.run(eng.run())

    d = spoken["directive"]
    assert d.kind == "note" and d.handled and "given to" in d.effect and result.passed
    # nobody worked between the interruption and the moment the human let go
    k = kinds(timeline)
    window = timeline[k.index("interrupted"): k.index("resumed")]
    assert not [e for e in window if e[0] == "work"]
    # the instruction reached the developers, and stays in force for later tasks
    later = next(str(r.messages) for r in llm.requests if "Task: test db module" in str(r.messages))
    assert "Keep every function under ten lines." in later
    api = next(str(r.messages) for r in llm.requests if "Task: write api module" in str(r.messages))
    assert "Standing instructions from the human" in api
    audit = [json.loads(l) for l in (tmp_path / "team" / "a2a-audit.jsonl").read_text(encoding="utf-8").splitlines()]
    briefings = [e for e in audit if e["topic"] == "briefing" and e["sender"] == "human"]  # the human's words reached the developers over A2A
    assert briefings and all("Keep every function under ten lines." in e["text"] and e["reply"] == "Noted." for e in briefings)
    repo = TeamRepo(tmp_path / "team" / "remote")
    assert "Keep every function under ten lines." in repo.file_at("viewer", "origin/final/r1", "docs/agile/human_directives.md")


def test_a_change_of_scope_drops_a_feature_that_is_already_running(tmp_path):
    timeline = []
    llm = agile_llm(timeline)
    llm.rules.insert(0, (__import__("re").compile(r"EMERGENCY REPLANNING", __import__("re").S), [("text", json.dumps({
        "drop": ["ui"], "add": [], "priority": [], "docs": "Remove the screens from the PRD.", "rationale": "The human does not want screens."}))]))
    eng = run_agile(tmp_path, llm, timeline)
    spoken = interrupt_at_first_day(eng, timeline, "We do not need the screens at all.", "scope")
    result = asyncio.run(eng.run())

    assert "dropped ui" in spoken["directive"].effect and "documents updated" in spoken["directive"].effect
    by_id = {f.id: f for f in result.features}
    assert by_id["ui"].status == "dropped" and by_id["db"].status == "merged" and by_id["api"].status == "merged" and result.passed
    assert eng.agile.store.state.dropped == ["ui"]
    repo = TeamRepo(tmp_path / "team" / "remote")
    assert repo.file_at("viewer", "origin/final/r1", "ui.py") is None and repo.file_at("viewer", "origin/final/r1", "db.py")
    assert repo.file_at("viewer", "origin/final/r1", "docs/AMENDED.md")  # the documents were updated
    assert any(c["by"] == "the human" and "screens" in c["change"] for c in eng.agile.store.state.changelog)
    assert "dropped" in repo.file_at("viewer", "origin/final/r1", "docs/agile/product_backlog.md")


def test_a_change_of_scope_can_add_a_feature_to_the_running_sprint(tmp_path):
    timeline = []
    llm = agile_llm(timeline)
    import re

    llm.rules.insert(0, (re.compile(r"EMERGENCY REPLANNING", re.S), [("text", json.dumps({
        "drop": [], "priority": [], "docs": "", "rationale": "Logging is needed.",
        "add": [{"id": "logs", "title": "Logging", "summary": "log things", "owner": "DEV_6", "depends_on": [], "tasks": [{"title": "write logs module", "details": "create logs.py"}]}]}))]))
    llm.on(r"Task: write logs module", [write("logs.py", "def log(msg):\n    return msg\n"), ("text", "logs written")])
    eng = run_agile(tmp_path, llm, timeline)
    interrupt_at_first_day(eng, timeline, "Add logging.", "scope")
    result = asyncio.run(eng.run())
    assert {f.id: f.status for f in result.features}["logs"] == "merged" and result.passed
    repo = TeamRepo(tmp_path / "team" / "remote")
    assert repo.file_at("viewer", "origin/final/r1", "logs.py")


def test_stop_and_rethink_asks_the_team_then_the_human_and_changes_course(tmp_path):
    timeline = []
    llm = agile_llm(timeline)
    llm.on(r"STOP AND RETHINK\. The human", [("text", "The storage design is too heavy; use plain files.")])
    llm.on(r"STOP AND RETHINK, scrum master", [("text", json.dumps({"summary": "Switch to plain-file storage.", "drop": [], "instruction": "Store data in plain files, not a database.", "docs": ""}))])
    eng = run_agile(tmp_path, llm, timeline)
    spoken = interrupt_at_first_day(eng, timeline, "This is going the wrong way, the storage is overbuilt.", "rethink")
    result = asyncio.run(eng.run())
    assert "Switch to plain-file storage." in spoken["directive"].effect and result.passed
    later = next(str(r.messages) for r in llm.requests if "Task: test db module" in str(r.messages))
    assert "Course correction agreed with the human: Store data in plain files" in later
    approvals = eng.agile.store.state.approvals
    assert any(a.kind == "scope" and a.title == "Course correction" for a in approvals)


def test_an_unclassified_remark_is_classified_by_the_scrum_master(tmp_path):
    timeline = []
    llm = agile_llm(timeline)
    llm.on(r"The human supervising this project interrupted", [("text", json.dumps({"kind": "note", "summary": "use tabs"}))])
    eng = run_agile(tmp_path, llm, timeline)
    spoken = interrupt_at_first_day(eng, timeline, "please use tabs", None)
    asyncio.run(eng.run())
    assert spoken["directive"].kind == "note"
    audit = [json.loads(l) for l in (tmp_path / "team" / "a2a-audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e["topic"] == "human directive" and e["sender"] == "scrum-master" for e in audit)


def test_a_note_does_not_stop_anyone_and_arrives_at_the_next_standup(tmp_path):
    timeline = []
    llm = agile_llm(timeline)
    eng = run_agile(tmp_path, llm, timeline)
    sent = {}

    def on_event(k, d):
        timeline.append((k, d))
        if k == "day-start" and not sent:
            sent["x"] = True
            eng.agile.desk.note("Please prefer small commits.")

    eng.on_event = on_event
    asyncio.run(eng.run())
    assert "interrupted" not in kinds(timeline)
    standup = eng.agile.store.state.standups[0]
    assert standup.notes == ["Please prefer small commits."]
    repo = TeamRepo(tmp_path / "team" / "remote")
    assert "Please prefer small commits." in repo.file_at("viewer", "origin/final/r1", "docs/agile/sprint-01/standups/standup-01.md")
