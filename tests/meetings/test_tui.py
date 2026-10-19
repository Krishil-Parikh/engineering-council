import asyncio

from meetings.config import Settings
from meetings.models import MeetingInput
from meetings.tui import CouncilApp, QuestionScreen, StartScreen, actor_of
from tests.meetings.fakes import FakeLLM

SETTINGS = Settings(api_key="k", model="fake")


def make_input(tmp_path):
    return MeetingInput(project_name="Todo CLI", problem="A command line task list.", output_dir=str(tmp_path))


async def drive(app, answer_keys=("enter",), timeout=30.0):
    """Run the app headlessly, answering any question modal, until the meeting ends."""
    async with app.run_test(size=(160, 50)) as pilot:
        waited = 0.0
        while not app.finished and waited < timeout:
            await pilot.pause(0.1)
            waited += 0.1
            if isinstance(app.screen, QuestionScreen):
                for k in answer_keys:
                    await pilot.press(k)
        await pilot.pause(0.5)
        return app


def test_actor_mapping():
    assert actor_of("talk2:DEV_4") == "DEV_4"
    assert actor_of("blind:DEV_1") == "DEV_1"
    assert actor_of("scrum:round1") == "SCRUM_MASTER"
    assert actor_of("decisions") == "SCRUM_MASTER"
    assert actor_of("spec_product_retry") == "SCRUM_MASTER"


def test_tui_runs_a_full_meeting_and_shows_everything(tmp_path):
    app = CouncilApp(SETTINGS, FakeLLM(), make_input(tmp_path), base_output=str(tmp_path))
    asyncio.run(drive(app))
    assert app.result is not None and app.result.report.passed, app.error
    # every member streamed something into their own tab and ended 'done'
    for who in ("DEV_1", "DEV_2", "DEV_3", "DEV_4", "DEV_5", "DEV_6", "SCRUM_MASTER"):
        assert len(app.streams[who]) > 0, who
        assert app.actors[who]["state"] in ("done", "stopped"), (who, app.actors[who]["state"])
    assert app.stage_n == 10


def test_tui_question_modal_records_the_answer(tmp_path):
    app = CouncilApp(SETTINGS, FakeLLM(), make_input(tmp_path), base_output=str(tmp_path))
    asyncio.run(drive(app, answer_keys=("up", "enter")))
    import json
    saved = json.loads((tmp_path / "todo-cli" / "questions.json").read_text())
    assert saved["answers"] and saved["answers"][0]["source"] in ("option", "default")


def test_tui_start_form_validates(tmp_path):
    app = CouncilApp(SETTINGS, FakeLLM(), None, base_output=str(tmp_path), auto_answers=True)

    async def run():
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause(0.3)
            assert isinstance(app.screen, StartScreen)
            await pilot.click("#start-btn")
            await pilot.pause(0.2)
            assert isinstance(app.screen, StartScreen)  # name/problem missing: stays open
            app.screen.query_one("#f-name").value = "Todo CLI"
            app.screen.query_one("#f-problem").text = "A command line task list."
            await pilot.click("#start-btn")
            waited = 0.0
            while not app.finished and waited < 60:
                await pilot.pause(0.1)
                waited += 0.1

    asyncio.run(run())
    assert app.result is not None and app.result.report.passed


def test_tui_reports_failure_and_resume_hint(tmp_path):
    app = CouncilApp(SETTINGS, FakeLLM(fail_stages=("proposal:",)), make_input(tmp_path), base_output=str(tmp_path), auto_answers=True)
    asyncio.run(drive(app))
    assert app.result is None and app.error and "quorum" in app.error


def test_selecting_text_in_a_log_copies_it_when_the_button_is_released(monkeypatch):
    import meetings.clipboard as clipboard
    from textual.geometry import Offset
    from textual.selection import Selection

    monkeypatch.setattr(clipboard, "native_copy", lambda text: None)
    from textual.app import App

    class Mini(clipboard.CopyOnSelect, App):
        def compose(self):
            yield clipboard.SelectableLog(id="log")

    async def mini():
        mini_app = Mini()
        async with mini_app.run_test(size=(80, 20)) as pilot:
            log = mini_app.query_one("#log")
            log.write("first line of the transcript")
            log.write("second line, the interesting one")
            await pilot.pause(0.2)
            mini_app.screen.selections = {log: Selection(Offset(0, 1), Offset(11, 1))}
            assert mini_app.screen.get_selected_text() == "second line"
            await pilot.mouse_up("#log", offset=(11, 1))
            await pilot.pause(0.3)
            assert mini_app.clipboard == "second line"
            mini_app.screen.selections = {log: Selection(Offset(0, 0), Offset(6, 1))}
            assert mini_app.screen.get_selected_text() == "first line of the transcript\nsecond"  # a selection can span lines

    asyncio.run(mini())
