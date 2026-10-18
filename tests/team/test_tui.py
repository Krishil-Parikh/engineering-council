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
