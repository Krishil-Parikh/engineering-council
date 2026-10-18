"""Design follow-through, shared model use, publishing, pull requests, and existing repositories: the engine around the edges."""

import asyncio
import json
import os
import subprocess

import pytest

from team.engine import TeamConfig, TeamEngine
from team.repo import TeamRepo
from tests.team.fake_llm import TeamLLM
from tests.team.test_build import finished_meeting
from tests.team.test_engine import base_llm, engine, write


def one_feature(owner="DEV_2"):
    return {"features": [{"id": "core", "title": "Core", "owner": owner, "tasks": [{"title": "write core"}]}]}


def approved_change_llm(follow_up):
    llm = TeamLLM()
    llm.on(r"Turn the agreed specification", [("text", json.dumps(one_feature()))])
    llm.on(r"Task: write core", [
        ("tool", "design_change", {"title": "Use bus", "reason": "decoupling", "change": "add an EventBus contract"}),
        write("core.py", "BUS = True\n"), ("text", "built it, forgot the document"),
    ])
    llm.on(r"proposes a design change", [("text", json.dumps({"vote": "approve", "comment": "yes"}))])
    llm.on(r"team approved a design change", follow_up)
    return llm


def test_an_approved_design_change_must_be_reflected_in_design_md(tmp_path):
    llm = approved_change_llm([
        ("tool", "write", {"path": "docs/Design.md", "content": "# Design\n\n## Contracts\n- EventBus: publish(topic, payload)\n"}),
        ("text", "Design.md now documents the EventBus."),
    ])
    eng, events, _ = engine(tmp_path, llm)
    result = asyncio.run(eng.run())
    assert [f.status for f in result.features] == ["merged"] and "design-followup" in [k for k, _ in events]
    repo = TeamRepo(tmp_path / "team" / "remote")
    assert "EventBus: publish" in repo.file_at("viewer", "origin/final/r1", "docs/Design.md")
    assert not any("docs/Design.md was not updated" in w for w in result.warnings)


def test_a_design_change_without_a_design_update_is_flagged_not_hidden(tmp_path):
    eng, _, _ = engine(tmp_path, approved_change_llm([("text", "I will not touch the document.")]))
    result = asyncio.run(eng.run())
    assert any("a design change was approved" in w and "docs/Design.md was not updated" in w for w in result.warnings)


def test_every_developer_shares_one_throttled_model_and_the_report_shows_use(tmp_path):
    llm = base_llm()
    eng, _, meeting = engine(tmp_path, llm, max_llm_concurrency=2)
    result = asyncio.run(eng.run())
    assert eng.shared_llm().peak <= 2 and eng.shared_llm().started == len(llm.requests)
    assert {"DEV_1", "DEV_2", "DEV_6"} <= set(result.usage) and all(u["sessions"] >= 1 for u in result.usage.values())
    assert "## Model use" in (meeting / "team_report.md").read_text(encoding="utf-8")


def bare_target(tmp_path, name="real-remote.git"):
    target = tmp_path / name
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(target)], check=True)
    return target


def branches_of(path):
    return set(subprocess.run(["git", "branch", "--list"], cwd=path, capture_output=True, text=True).stdout.replace("*", "").split())


def test_the_final_branch_can_be_published_to_the_real_repository_but_never_main(tmp_path):
    target = bare_target(tmp_path)
    eng, events, meeting = engine(tmp_path, base_llm(), publish=str(target))
    result = asyncio.run(eng.run())
    assert result.published_to == str(target) and "published" in [k for k, _ in events]
    assert branches_of(target) == {"final/r1"}  # only the final branch, and not main
    assert "## Published" in (meeting / "team_report.md").read_text(encoding="utf-8")
    with pytest.raises(Exception, match="protected"):
        eng.repo.push_to("integrator", str(target), "main")


def test_publishing_everything_includes_feature_branches(tmp_path):
    target = bare_target(tmp_path)
    eng, _, _ = engine(tmp_path, base_llm(), publish=str(target), publish_all=True)
    asyncio.run(eng.run())
    assert {"final/r1", "integration/r1", "feature/db", "feature/ui", "feature/api"} <= branches_of(target) and "main" not in branches_of(target)


def test_a_pull_request_is_opened_for_the_human_to_merge(tmp_path):
    target = bare_target(tmp_path)
    calls = []

    def fake_gh(args, cwd):
        calls.append((args, str(cwd)))
        return 0, "https://github.com/acme/app/pull/7\n"

    eng, events, meeting = engine(tmp_path, base_llm(), publish=str(target), pull_request=True)
    eng.run_gh = fake_gh
    result = asyncio.run(eng.run())
    assert result.pull_request_url == "https://github.com/acme/app/pull/7"
    args = calls[0][0]
    assert args[:2] == ["pr", "create"] and args[args.index("--head") + 1] == "final/r1" and args[args.index("--base") + 1] == "main" and "merge" not in args
    assert "pull request was opened" in (meeting / "team_report.md").read_text(encoding="utf-8")


def test_a_failed_pull_request_is_a_warning_not_a_crash(tmp_path):
    target = bare_target(tmp_path)
    eng, _, _ = engine(tmp_path, base_llm(), publish=str(target), pull_request=True)
    eng.run_gh = lambda args, cwd: (1, "gh: not logged in")
    result = asyncio.run(eng.run())
    assert result.passed and any("could not open a pull request: gh: not logged in" in w for w in result.warnings)


def test_publishing_with_nowhere_to_go_says_so(tmp_path):
    eng, _, _ = engine(tmp_path, base_llm(), publish="source")  # a new project has no source repository
    result = asyncio.run(eng.run())
    assert result.passed and any("nowhere to publish to" in w for w in result.warnings) and result.published_to is None


def test_building_on_an_existing_repo_starts_from_its_uncommitted_work_and_keeps_its_trunk(tmp_path):
    src = tmp_path / "existing"
    src.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    (src / "app.py").write_text("print('committed')\n")
    for args in (["init", "-q", "-b", "trunk"], ["add", "-A"], ["commit", "-q", "-m", "first"]):
        subprocess.run(["git", *args], cwd=src, check=True, env=env)
    (src / "wip.py").write_text("print('work in progress')\n")  # not committed
    meeting, _ = finished_meeting(tmp_path)
    config = TeamConfig(run_id="r1", repair_rounds=0, plan_discussion_rounds=0, publish="source")
    eng = TeamEngine(meeting, tmp_path / "team", llm=base_llm(), source=src, config=config)
    result = asyncio.run(eng.run())
    repo = TeamRepo(tmp_path / "team" / "remote", main_branch="trunk")
    assert repo.file_at("viewer", "origin/final/r1", "wip.py") is not None and repo.file_at("viewer", "origin/final/r1", "db.py")
    assert any("uncommitted change" in w for w in result.warnings)
    assert "trunk" in repo.branches("viewer") and repo.file_at("viewer", "origin/trunk", "db.py") is None
    assert "final/r1" in branches_of(src) and result.published_to == str(src.resolve())
