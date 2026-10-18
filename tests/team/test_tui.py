"""The full-screen team view: it shows what the engine reports, and quitting cancels the build cleanly."""

import asyncio
import json

from textual.widgets import DataTable, RichLog

from team.engine import TeamConfig, TeamEngine
from team.events import describe, describe_talk
from team.tui import TeamApp
from tests.team.fake_llm import TeamLLM
from tests.team.test_build import finished_meeting
from tests.team.test_engine import PLAN, base_llm, write

PLAN_EVENT = {"plan": {"features": [
    {"id": "db", "owner": "DEV_6", "depends_on": [], "title": "Database"},
    {"id": "api", "owner": "DEV_2", "depends_on": ["db"], "title": "API"},
]}}


def cell(app, row, column):
    value = app.query_one("#features", DataTable).get_cell(row, column)
    return getattr(value, "plain", value)


def lines(app, log_id):
    return len(app.query_one(f"#{log_id}", RichLog).lines)


def test_events_become_readable_lines():
    assert describe("feature-done", {"feature": "db", "detail": "merged feature/db"}) == ("ok", "[merged]  db: merged feature/db")
    assert describe("feature-failed", {"feature": "db", "detail": "boom"})[0] == "bad"
    style, text = describe("git-trouble", {"dev": "DEV_2", "goal": "publish feature/x", "error": "rejected\nnon-fast-forward", "attempt": 1})
    assert style == "warn" and "DEV_2" in text and "rejected non-fast-forward" in text and "\n" not in text
    assert describe("git-fixed", {"dev": "DEV_2", "goal": "g", "how": "agent", "note": "I rebased"})[1].endswith("(I rebased)")
    assert describe("git-fixed", {"dev": "DEV_2", "goal": "g", "how": "rebased feature/x onto origin/feature/x"})[1].endswith("(rebased feature/x onto origin/feature/x)")
    assert describe("plan", PLAN_EVENT)[1].splitlines()[2] == "  api -> DEV_2 (after db): API"
    assert describe("some-internal-event", {}) is None and describe("DEV_1:message.user", {}) is None
    style, text = describe_talk({"sender": "integrator", "recipient": "DEV_1", "topic": "merge conflict", "text": "q" * 400, "reply": "answer"})
    assert "integrator -> DEV_1  [merge conflict]" in text and "answer" in text and len(text) < 600


def test_the_screen_follows_the_events():
    async def main():
        app = TeamApp("Todo")
        async with app.run_test(size=(150, 40)) as pilot:
            app.handle("plan", PLAN_EVENT)
            assert [cell(app, "db", c) for c in ("owner", "status")] == ["DEV_6", "waiting"]
            app.handle("feature-started", {"feature": "db", "owner": "DEV_6", "detail": "DEV_6"})
            app.handle("task", {"feature": "db", "owner": "DEV_6", "index": 1, "total": 2, "title": "schema"})
            assert cell(app, "db", "status") == "working" and cell(app, "db", "now") == "task 1/2"
            app.handle("conflict", {"feature": "db", "files": ["schema.sql"]})
            assert cell(app, "db", "status") == "conflict" and app.counts["conflicts"] == 1
            app.handle("feature-done", {"feature": "db", "owner": "DEV_6", "detail": "merged"})
            app.handle("feature-blocked", {"feature": "api", "owner": "DEV_2", "detail": "waiting"})
            assert cell(app, "db", "status") == "merged" and cell(app, "api", "status") == "blocked"
            app.handle("git-trouble", {"dev": "DEV_6", "goal": "publish", "error": "rejected", "attempt": 1})
            app.handle("git-fixed", {"dev": "DEV_6", "goal": "publish", "how": "rebased"})
            app.handle("talk", {"sender": "integrator", "recipient": "DEV_6", "topic": "conflict", "text": "how?", "reply": "keep both"})
            for tab in ("git", "talk", "activity"):  # a hidden log shows its lines once its tab is opened
                app.action_tab(tab)
                await pilot.pause(0.2)
            assert lines(app, "activity-log") >= 5 and lines(app, "git-log") == 2 and lines(app, "talk-log") >= 2
            assert app.counts == {"talk": 1, "git_trouble": 1, "git_fixed": 1, "conflicts": 1}
            status = str(app.query_one("#status").render())
            assert "1/2 merged" in status and "git trouble: 1 (fixed: 1)" in status

    asyncio.run(main())


def test_a_broken_event_never_stops_the_build():
    async def main():
        app = TeamApp()
        async with app.run_test(size=(120, 30)):
            app.handle("feature-started", {"feature": "not-in-the-plan", "owner": "x"})  # no such row
            app.handle("plan", {"plan": {}})  # malformed
            app.handle("talk", {})
            assert app.is_running

    asyncio.run(main())


def test_a_whole_build_is_shown_in_the_screen(tmp_path):
    seen = {}

    async def check(app, pilot):
        for tab in ("summary", "talk", "activity"):
            app.action_tab(tab)
            await pilot.pause(0.2)
        seen["rows"] = {k: (cell(app, k, "status"), cell(app, k, "owner")) for k in ("db", "ui", "api")}
        seen["summary"] = lines(app, "summary-log")
        seen["talk"] = lines(app, "talk-log")
        seen["activity"] = lines(app, "activity-log")

    meeting, _ = finished_meeting(tmp_path)
    app = TeamApp("Todo")
    eng = TeamEngine(meeting, tmp_path / "team", llm=base_llm(), config=TeamConfig(run_id="r1", repair_rounds=0, plan_discussion_rounds=0), on_event=app.handle)

    async def main():
        async with app.run_test(size=(160, 50)) as pilot:
            app.start(eng)
            waited = 0.0
            while not app.finished and waited < 120:
                await pilot.pause(0.2)
                waited += 0.2
            await pilot.pause(0.3)
            await check(app, pilot)

    asyncio.run(main())
    assert app.result is not None and app.result.passed and app.error is None
    assert seen["rows"] == {"db": ("merged", "DEV_6"), "ui": ("merged", "DEV_1"), "api": ("merged", "DEV_2")}
    assert seen["summary"] >= 5 and seen["activity"] >= 8


def test_quitting_mid_build_cancels_it_and_leaves_the_branches(tmp_path):
    llm = TeamLLM()
    llm.on(r"Turn the agreed specification", [("text", json.dumps(PLAN))])

    class Slow(TeamLLM):
        async def stream(self, request):
            await asyncio.sleep(0.5)
            async for ev in super().stream(request):
                yield ev

    slow = Slow()
    slow.rules = llm.rules + base_llm().rules[1:]
    meeting, _ = finished_meeting(tmp_path)
    app = TeamApp("Todo")
    eng = TeamEngine(meeting, tmp_path / "team", llm=slow, config=TeamConfig(run_id="r1", repair_rounds=0, plan_discussion_rounds=0), on_event=app.handle)

    async def main():
        async with app.run_test(size=(160, 50)) as pilot:
            app.start(eng)
            for _ in range(100):
                await pilot.pause(0.1)
                if app.status:
                    break
            await pilot.press("q")
            await pilot.pause(0.5)

    asyncio.run(main())
    assert not app.finished and app.return_code == 2


# ---------------------------------------------------------------------------------------------- the human's dialogs

from types import SimpleNamespace  # noqa: E402

from team.tui_desk import ApprovalScreen, InterruptScreen, NoteScreen, parse_spoken, read_documents  # noqa: E402


class StubDesk:
    def __init__(self):
        self.answers, self.notes, self.said, self.interrupts, self.released = [], [], [], 0, 0

    def answer(self, approval_id, approved, text=""):
        self.answers.append((approval_id, approved, text))

    def note(self, text):
        self.notes.append(text)

    async def interrupt(self):
        self.interrupts += 1
        return {"late": []}

    async def say(self, text, kind=None):
        self.said.append((text, kind))
        return SimpleNamespace(kind=kind or "note", effect="given to everyone")

    async def release(self):
        self.released += 1

    def status(self):
        return {"phase": "sprinting", "sprint": 1, "day": 2, "goal": "Ship storage", "workers": ["DEV_1"], "resting": {"DEV_1": "task-done"}, "open_impediments": ["need a schema"]}


def with_desk(app):
    desk = StubDesk()
    app.engine = SimpleNamespace(agile=SimpleNamespace(desk=desk))
    return desk


ASK = {"id": "APP-001", "title": "Accept the project documents?", "detail": "Read these:\n- nowhere.md", "kind": "docs"}


def test_a_decision_opens_a_dialog_and_the_answer_reaches_the_desk():
    async def main():
        app = TeamApp()
        async with app.run_test(size=(150, 45)) as pilot:
            desk = with_desk(app)
            app.handle("approval-requested", ASK)
            await pilot.pause(0.2)
            assert isinstance(app.screen, ApprovalScreen)
            assert "1 decision(s) waiting" in str(app.screen_stack[0].query_one("#status").render())
            await pilot.click("#approve")
            await pilot.pause(0.2)
            assert desk.answers == [("APP-001", True, "")] and not isinstance(app.screen, ApprovalScreen)

    asyncio.run(main())


def test_declining_carries_the_feedback_and_a_postponed_decision_comes_back_with_p():
    async def main():
        app = TeamApp()
        async with app.run_test(size=(150, 45)) as pilot:
            desk = with_desk(app)
            app.handle("approval-requested", ASK)
            await pilot.pause(0.2)
            await pilot.press("escape")  # decide later
            await pilot.pause(0.2)
            assert not isinstance(app.screen, ApprovalScreen) and desk.answers == [] and len(app.waiting) == 1
            await pilot.press("p")
            await pilot.pause(0.2)
            assert isinstance(app.screen, ApprovalScreen)
            app.screen.query_one("#feedback").value = "add offline support"
            await pilot.click("#decline")
            await pilot.pause(0.2)
            assert desk.answers == [("APP-001", False, "add offline support")]

    asyncio.run(main())


def test_the_next_decision_opens_after_the_first_is_answered():
    async def main():
        app = TeamApp()
        async with app.run_test(size=(150, 45)) as pilot:
            desk = with_desk(app)
            app.handle("approval-requested", ASK)
            app.handle("approval-requested", {**ASK, "id": "APP-002", "title": "Design change: cache", "kind": "decision", "detail": "use redis"})
            await pilot.pause(0.2)
            await pilot.click("#approve")
            await pilot.pause(0.3)
            assert isinstance(app.screen, ApprovalScreen) and app.screen.item["id"] == "APP-002"
            await pilot.click("#decline")
            await pilot.pause(0.2)
            assert [a[:2] for a in desk.answers] == [("APP-001", True), ("APP-002", False)]

    asyncio.run(main())


def test_the_documents_are_shown_in_full_before_the_human_accepts_them(tmp_path):
    prd = tmp_path / "PRD.md"
    prd.write_text("# PRD\nThe product shall do the thing.\n", encoding="utf-8")
    shown = read_documents(f"Read these:\n- {prd}\n- {tmp_path / 'missing.md'}")
    assert "PRD.md" in shown and "The product shall do the thing." in shown and "missing" not in shown


def test_interrupting_pauses_the_team_and_what_is_said_reaches_the_desk():
    async def main():
        app = TeamApp()
        async with app.run_test(size=(150, 45)) as pilot:
            desk = with_desk(app)
            await pilot.press("i")
            await pilot.pause(0.3)
            assert desk.interrupts == 1 and isinstance(app.screen, InterruptScreen)
            box = app.screen.query_one("#spoken")
            box.value = "/scope drop the admin panel"
            await box.action_submit()
            await pilot.pause(0.3)
            assert desk.said == [("drop the admin panel", "scope")]
            box.value = "keep it simple"
            await box.action_submit()
            await pilot.pause(0.3)
            assert desk.said[-1] == ("keep it simple", None) and desk.released == 0  # still paused until the human lets go
            await pilot.press("escape")
            await pilot.pause(0.3)
            assert desk.released == 1 and not isinstance(app.screen, InterruptScreen)

    asyncio.run(main())


def test_a_note_does_not_pause_anything():
    async def main():
        app = TeamApp()
        async with app.run_test(size=(150, 45)) as pilot:
            desk = with_desk(app)
            await pilot.press("n")
            await pilot.pause(0.2)
            assert isinstance(app.screen, NoteScreen)
            box = app.screen.query_one("#note")
            box.value = "prefer small commits"
            await box.action_submit()
            await pilot.pause(0.2)
            assert desk.notes == ["prefer small commits"] and desk.interrupts == 0

    asyncio.run(main())


def test_without_a_sprint_run_the_human_keys_explain_themselves():
    async def main():
        app = TeamApp()
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("i")
            await pilot.pause(0.2)
            assert not isinstance(app.screen, InterruptScreen) and app.is_running

    asyncio.run(main())


def test_sprint_events_fill_the_sprint_tab_and_the_status():
    async def main():
        app = TeamApp()
        async with app.run_test(size=(150, 45)) as pilot:
            app.handle("sprint-planned", {"sprint": 1, "goal": "Ship storage", "features": ["db"], "tasks": 2, "carried": []})
            app.handle("day-start", {"sprint": 1, "day": 1, "working": ["DEV_6"]})
            app.handle("gate-freeze", {"holder": "ceremony"})
            app.handle("standup", {"sprint": 1, "number": 1, "day": 1, "summary": "On track.", "impediments": []})
            status = str(app.query_one("#status").render())
            assert "sprint 1, day 1: Ship storage" in status and status.startswith("paused")
            app.handle("gate-thaw", {"holder": "ceremony"})
            app.action_tab("sprint")
            await pilot.pause(0.2)
            assert lines(app, "sprint-log") >= 2

    asyncio.run(main())


def test_spoken_prefixes_choose_the_kind():
    assert parse_spoken("/scope drop ui") == ("drop ui", "scope")
    assert parse_spoken("/rethink the storage is overbuilt") == ("the storage is overbuilt", "rethink")
    assert parse_spoken("just a remark") == ("just a remark", None)
    assert parse_spoken("/unknown thing") == ("/unknown thing", None)


def test_agile_events_read_as_words():
    assert describe("standup", {"number": 2, "day": 3, "summary": "On track.", "impediments": []})[1] == "[standup 2] day 3: On track."
    assert "SPRINT 1 PLANNED" in describe("sprint-planned", {"sprint": 1, "tasks": 4, "features": ["a"], "goal": "g", "carried": []})[1]
    assert describe("approval-requested", {"id": "A", "title": "Design change: cache", "detail": "", "kind": "decision"}) == ("warn", "[needs you] Design change: cache")
    assert describe("approval-answered", {"id": "A", "title": "x", "approved": False})[1] == "[decision] x: declined"
    assert describe("interrupted", {"late": ["DEV_2"]})[1].endswith("(still finishing a step: DEV_2)")
