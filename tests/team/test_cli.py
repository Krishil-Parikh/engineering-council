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


def test_the_repository_from_the_start_form_is_the_one_the_team_builds_on(tmp_path):
    from argparse import Namespace

    from council.pipeline import carry_repo
    from meetings.models import MeetingInput

    meeting = tmp_path / "meeting"
    meeting.mkdir()
    repo = tmp_path / "existing"
    repo.mkdir()
    (meeting / "input.json").write_text(MeetingInput(project_name="X", problem="p", repo_path=str(repo), output_dir=str(tmp_path)).model_dump_json(), encoding="utf-8")
    args = Namespace(repo=None)
    carry_repo(args, meeting)
    assert args.repo == str(repo)
    explicit = Namespace(repo="  other  ")
    carry_repo(explicit, meeting)
    assert explicit.repo == "other"  # a flag wins over the form
    greenfield = tmp_path / "green"
    greenfield.mkdir()
    (greenfield / "input.json").write_text(MeetingInput(project_name="Y", problem="p", output_dir=str(tmp_path)).model_dump_json(), encoding="utf-8")
    none = Namespace(repo=None)
    carry_repo(none, greenfield)
    assert none.repo is None


# ---------------------------------------------------------------------------------------------- publishing


def make_repo(path, with_remote=None):
    import subprocess

    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"], cwd=path, check=True)
    if with_remote:
        subprocess.run(["git", "remote", "add", "origin", str(with_remote)], cwd=path, check=True)
    return path


def test_a_repository_you_gave_gets_the_finished_branches_by_default(tmp_path):
    remote = make_repo(tmp_path / "theirs")
    with_remote = make_repo(tmp_path / "clone", with_remote=remote)
    without_remote = make_repo(tmp_path / "local-only")
    assert cli.publish_choice(parse("--repo", str(with_remote))) == "source"
    assert cli.publish_choice(parse("--repo", str(without_remote))) is None  # nowhere to push: stays local
    assert cli.publish_choice(parse("--repo", str(with_remote), "--no-publish")) is None
    assert cli.publish_choice(parse("--repo", str(with_remote), "--publish", "https://example.com/x.git")) == "https://example.com/x.git"
    assert cli.publish_choice(parse()) is None  # no repository given at all
    config, _ = cli.config_from_args(parse("--no-memory", "--repo", str(with_remote)))
    assert config.publish == "source" and config.publish_all is True  # and every branch, not only the final one
    assert cli.config_from_args(parse("--no-memory", "--repo", str(with_remote), "--final-only"))[0].publish_all is False


def finished_run(tmp_path, branches=("final/r1", "integration/r1", "feature/db", "feature/ui", "fix/r1-1")):
    """A meeting folder with the team's shared repository holding main and the given branches."""
    import subprocess

    meeting = tmp_path / "meeting"
    origin = meeting / "team" / "remote" / "origin.git"
    origin.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    work = make_repo(tmp_path / "work")
    subprocess.run(["git", "push", "-q", str(origin), "main"], cwd=work, check=True)
    for name in branches:
        subprocess.run(["git", "push", "-q", str(origin), f"main:refs/heads/{name}"], cwd=work, check=True)
    return meeting


def branches_of(path):
    import subprocess

    out = subprocess.run(["git", "--git-dir", str(path), "for-each-ref", "--format=%(refname:short)", "refs/heads"], capture_output=True, text=True).stdout
    return sorted(out.split())


def test_the_publish_command_pushes_the_newest_final_branch_and_never_main(tmp_path, capsys):
    import subprocess

    meeting = finished_run(tmp_path)
    target = tmp_path / "target.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(target)], check=True)
    assert cli.publish(["publish", str(meeting), str(target), "--only-final"]) == 0
    assert branches_of(target) == ["final/r1"] and "Nothing was merged into main" in capsys.readouterr().out
    assert cli.publish(["publish", str(meeting), str(target)]) == 0  # by default every branch of the run goes, so all of it can be browsed
    assert branches_of(target) == ["feature/db", "feature/ui", "final/r1", "fix/r1-1", "integration/r1"]
    assert cli.publish(["publish", str(meeting), str(target), "--branch", "main"]) == 1 and "main" not in branches_of(target)


def test_the_publish_command_says_what_is_wrong(tmp_path, capsys):
    assert cli.publish(["publish", str(tmp_path / "nothing-here")]) == 1 and "nothing was built" in capsys.readouterr().err
    meeting = finished_run(tmp_path, branches=())
    assert cli.publish(["publish", str(meeting), str(tmp_path / "t.git")]) == 1 and "no final branch" in capsys.readouterr().err
    meeting2 = finished_run(tmp_path / "second")
    assert cli.publish(["publish", str(meeting2)]) == 1 and "no target given" in capsys.readouterr().err


def test_the_publish_command_finds_the_repository_the_project_was_built_on(tmp_path):
    from meetings.models import MeetingInput

    meeting = finished_run(tmp_path)
    target = make_repo(tmp_path / "theirs")
    import subprocess

    subprocess.run(["git", "config", "receive.denyCurrentBranch", "ignore"], cwd=target, check=True)
    (meeting / "input.json").write_text(MeetingInput(project_name="X", problem="p", repo_path=str(target), output_dir=str(tmp_path)).model_dump_json(), encoding="utf-8")
    assert cli.publish(["publish", str(meeting)]) == 0
    assert "final/r1" in subprocess.run(["git", "branch", "--list"], cwd=target, capture_output=True, text=True).stdout
