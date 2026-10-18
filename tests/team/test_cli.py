"""The command line: flags become the right configuration, and `run --from-meeting` takes a finished meeting to a built project."""

import argparse

import pytest

import team.cli as cli
from council.pipeline import make_parser
from team.engine import TeamEngine
from tests.team.test_agile_flow import agile_llm
from tests.team.test_build import finished_meeting


def parse(*argv):
    p = argparse.ArgumentParser()
    p.add_argument("directory")
    cli.add_build_arguments(p)
    return p.parse_args(["dir", *argv])


def test_sprints_are_the_default_and_the_human_decides():
    config, _ = cli.config_from_args(parse("--no-memory"))
    assert config.agile is not None and config.agile.approvals == "ask" and config.agile.max_days == 4 and config.agile.steps_per_day == 40


def test_flags_shape_the_sprints():
    config, _ = cli.config_from_args(parse("--no-memory", "--sprint-capacity", "5", "--max-days", "3", "--steps-per-day", "25", "--unattended", "--run-id", "x1"))
    assert (config.agile.capacity, config.agile.max_days, config.agile.steps_per_day, config.agile.approvals, config.run_id) == (5, 3, 25, "approve", "x1")


def test_no_agile_turns_the_whole_process_off():
    config, memory = cli.config_from_args(parse("--no-memory", "--no-agile"))
    assert config.agile is None and memory is None


def test_the_combined_command_shares_the_meetings_flags_with_the_build():
    args = make_parser().parse_args(["--name", "Todo", "--problem", "a todo app", "--repo", "somewhere", "--plain", "--sprint-capacity", "6", "--unattended", "--from-meeting", "out/todo"])
    assert (args.name, args.repo, args.plain, args.sprint_capacity, args.unattended, args.from_meeting) == ("Todo", "somewhere", True, 6, True, "out/todo")


def patch_engine(monkeypatch, tmp_path, answers=None):
    timeline = []
    llm = agile_llm(timeline)

    def make(meeting, workdir, **kw):
        kw.pop("api_key", None)
        kw.pop("model", None)
        return TeamEngine(meeting, workdir, llm=llm, **kw)

    monkeypatch.setattr(cli, "TeamEngine", make)
    monkeypatch.setattr(cli, "load_settings", lambda: type("S", (), {"api_key": "k", "model": "m"})())
    return llm


def test_a_finished_meeting_is_built_in_sprints_from_the_command_line(tmp_path, monkeypatch, capsys):
    meeting = finished_meeting(tmp_path)[0]
    patch_engine(monkeypatch, tmp_path)
    code = cli.build(["build", str(meeting), "--plain", "--unattended", "--no-memory", "--run-id", "r1", "--max-days", "4", "--sprint-capacity", "4"])
    out = capsys.readouterr().out
    assert code == 0 and "3/3 features merged" in out and "2 sprint(s)" in out and "docs/agile/" in out
    assert "SPRINT 1 PLANNED" in out and "[standup 1]" in out and "[retro]" in out


def test_in_plain_mode_the_documents_are_put_to_the_human_at_the_prompt(tmp_path, monkeypatch, capsys):
    meeting = finished_meeting(tmp_path)[0]
    patch_engine(monkeypatch, tmp_path)
    asked = []

    def fake_input(prompt=""):
        asked.append(prompt)
        return "y"

    monkeypatch.setattr("builtins.input", fake_input)
    code = cli.build(["build", str(meeting), "--plain", "--no-memory", "--run-id", "r1", "--sprint-capacity", "4"])
    out = capsys.readouterr().out
    assert code == 0 and "Accept the project documents?" in out and asked and "Approve?" in asked[0]


def test_declining_the_documents_in_plain_mode_stops_with_a_clear_message(tmp_path, monkeypatch, capsys):
    meeting = finished_meeting(tmp_path)[0]
    llm = patch_engine(monkeypatch, tmp_path)
    llm.on(r"asked for changes", [("text", "nothing")])
    monkeypatch.setattr("builtins.input", lambda prompt="": "no, it misses offline support")
    code = cli.build(["build", str(meeting), "--plain", "--no-memory", "--run-id", "r1"])
    out = capsys.readouterr().out
    assert code == 3 and "documents were not accepted" in out and "Nothing was built" in out


def test_the_flat_build_still_works_without_sprints(tmp_path, monkeypatch, capsys):
    from tests.team.test_engine import base_llm

    meeting = finished_meeting(tmp_path)[0]
    llm = base_llm()
    monkeypatch.setattr(cli, "TeamEngine", lambda meeting, workdir, **kw: TeamEngine(meeting, workdir, llm=llm, **{k: v for k, v in kw.items() if k not in ("api_key", "model")}))
    monkeypatch.setattr(cli, "load_settings", lambda: type("S", (), {"api_key": "k", "model": "m"})())
    code = cli.build(["build", str(meeting), "--plain", "--no-agile", "--no-memory", "--run-id", "r1", "--repair-rounds", "0"])
    out = capsys.readouterr().out
    assert code == 0 and "3/3 features merged" in out and "sprint(s)" not in out
