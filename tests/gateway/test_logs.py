"""What the terminal shows: a stuck run must not look like a working one."""

import logging
import time
from types import SimpleNamespace

from gateway.logs import heartbeat_line, one_line, setup_logging
from gateway.projection import Projection
from tests.gateway.conftest import WORKSPACE, command


def fake_run(state="building", quiet=0.0, pending=None, agents=()):
    projection = Projection(WORKSPACE)
    for agent in agents:
        projection.emit("agent.updated", agent)
    projection.last_event_at = time.monotonic() - quiet
    return SimpleNamespace(active=state in ("meeting", "building"), state=state, p=projection, questions=SimpleNamespace(pending=pending or {}))


def test_nothing_is_said_about_a_workspace_that_is_not_running():
    assert heartbeat_line(fake_run(state="idle")) is None


def test_a_running_workspace_says_what_it_is_doing():
    run = fake_run(agents=[{"id": "agent-01", "name": "DEV_1", "role": "Backend", "status": "active", "activeTask": "storage: write the JSON file"}])
    level, text = heartbeat_line(run)
    assert level == logging.INFO and "still running" in text and "DEV_1: storage: write the JSON file" in text


def test_a_run_that_waits_for_you_says_so_loudly():
    level, text = heartbeat_line(fake_run(pending={"q-1": object()}))
    assert level == logging.WARNING and "WAITING FOR YOU" in text and "browser" in text


def test_a_long_silence_is_a_warning():
    level, text = heartbeat_line(fake_run(quiet=400))
    assert level == logging.WARNING and "no activity for 4" in text


def test_long_text_is_one_short_line():
    assert one_line("a\n  b   c " * 100, 40).endswith("...") and "\n" not in one_line("a\nb")


def test_commands_from_the_browser_are_logged(client, caplog):
    caplog.set_level(logging.INFO)
    command(client, type="phase.advance", phaseId="kickoff")
    assert any("browser -> phase.advance" in record.getMessage() for record in caplog.records)


def test_setup_logging_writes_the_console_and_a_file(tmp_path):
    log_file = tmp_path / "gateway.log"
    setup_logging("INFO", log_file)
    logging.getLogger("gateway.test").info("hello from the test")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert "hello from the test" in log_file.read_text(encoding="utf-8")
    setup_logging("WARNING")  # leave the root logger quiet again
