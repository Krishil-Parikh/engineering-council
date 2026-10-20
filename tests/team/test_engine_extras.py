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


def kinds_with(events, kind):
    return [d for k, d in events if k == kind]


def test_every_branch_reaches_the_repository_while_the_team_works_not_only_at_the_end(tmp_path):
    target = bare_target(tmp_path)
    eng, events, _ = engine(tmp_path, base_llm(), publish=str(target), publish_all=True)
    asyncio.run(eng.run())
    order = [k for k, _ in events]
    pushed = [d["branch"] for d in kinds_with(events, "mirrored")]
    assert "integration/r1" in pushed and {"feature/db", "feature/ui", "feature/api"} <= set(pushed)
    assert order.index("mirroring") < order.index("mirrored") < order.index("final")  # the first push happened long before the run ended
    assert "main" not in pushed and "main" not in branches_of(target)  # never main
    first_feature_push = next(i for i, (k, d) in enumerate(events) if k == "mirrored" and d["branch"].startswith("feature/"))
    assert first_feature_push < order.index("final")


def test_each_feature_gets_a_pull_request_into_the_integration_branch_like_a_person_would_open(tmp_path):
    target = bare_target(tmp_path)
    calls = []

    def fake_gh(args, cwd):
        calls.append(args)
        return 0, f"https://github.com/acme/app/pull/{len(calls)}\n"

    eng, events, _ = engine(tmp_path, base_llm(), publish=str(target), publish_all=True)
    eng.run_gh = fake_gh
    asyncio.run(eng.run())
    heads = {c[c.index("--head") + 1]: c[c.index("--base") + 1] for c in calls}
    assert {"feature/db", "feature/ui", "feature/api"} <= set(heads) and set(heads.values()) == {"integration/r1"}  # never main
    assert len(calls) == len(heads)  # one pull request per feature, not one per push
    assert len(kinds_with(events, "feature-pr")) == len(heads)


def test_an_unreachable_repository_does_not_stop_the_build_and_live_pushing_gives_up(tmp_path):
    eng, events, _ = engine(tmp_path, base_llm(), publish=str(tmp_path / "does-not-exist.git"), publish_all=True)
    eng.run_gh = lambda args, cwd: (1, "no")
    result = asyncio.run(eng.run())
    assert result.passed and all(f.status == "merged" for f in result.features)
    assert len(kinds_with(events, "mirror-failed")) == 3  # then it stops trying for the rest of the run
    assert any("no more live pushes this run" in w for w in result.warnings)


def test_live_publishing_can_be_turned_off_and_the_end_of_run_publish_still_happens(tmp_path):
    target = bare_target(tmp_path)
    eng, events, _ = engine(tmp_path, base_llm(), publish=str(target), publish_all=True, live_publish=False)
    asyncio.run(eng.run())
    assert not kinds_with(events, "mirrored") and not kinds_with(events, "mirroring")
    assert {"final/r1", "integration/r1", "feature/db"} <= branches_of(target)


def test_without_the_github_cli_pull_requests_are_given_up_after_one_try_but_pushing_goes_on(tmp_path):
    target = bare_target(tmp_path)
    tries = []
    eng, events, _ = engine(tmp_path, base_llm(), publish=str(target), publish_all=True)
    eng.run_gh = lambda args, cwd: tries.append(args) or (127, "gh: command not found")
    result = asyncio.run(eng.run())
    assert len(tries) == 1 and result.passed
    assert {"feature/db", "feature/ui"} <= {d["branch"] for d in kinds_with(events, "mirrored")}


def stepwise_llm():
    """A developer who builds one task in several steps: a module, another module, then its tests."""
    llm = TeamLLM()
    llm.on(r"Turn the agreed specification", [("text", json.dumps(one_feature()))])
    llm.on(r"Task: write core", [
        write("jarvis/core/registry.py", "REGISTRY = {}\n"), write("jarvis/core/clock.py", "NOW = 0\n"),
        write("tests/test_registry.py", "def test_registry():\n    assert True\n"), ("text", "Registry, clock and tests are in."),
    ])
    return llm


def subjects(tmp_path, dev="DEV_2"):
    """The subjects of the commits the developer made, oldest first (after the merge they are part of the integration branch)."""
    out = subprocess.run(["git", "--git-dir", str(tmp_path / "team" / "remote" / "origin.git"), "log", "--reverse", "--format=%s", f"--author={dev}", "integration/r1"], capture_output=True, text=True)
    return [line for line in out.stdout.splitlines() if line]


def test_a_task_is_saved_as_several_small_commits_with_messages_from_what_changed(tmp_path):
    eng, events, _ = engine(tmp_path, stepwise_llm(), checkpoint_interval=0.0, push_interval=0.0)
    result = asyncio.run(eng.run())
    assert [f.status for f in result.features] == ["merged"]
    log = subjects(tmp_path)
    assert len(log) >= 2, log  # not one commit for the whole task (steps here take milliseconds, so several are saved together; real ones take seconds)
    assert any(s.startswith("feat(core): add") and "registry.py" in s for s in log) and any(s.startswith("test(registry)") for s in log), log
    assert all(len(s) <= 72 for s in log) and kinds_with(events, "checkpoint")


def test_one_commit_per_task_is_still_available(tmp_path):
    eng, events, _ = engine(tmp_path, stepwise_llm(), checkpoint_commits=False)
    asyncio.run(eng.run())
    assert subjects(tmp_path) == ["core: write core"] and not kinds_with(events, "checkpoint")


def test_the_branch_is_pushed_to_the_repository_many_times_as_the_work_goes_on_not_once(tmp_path):
    target = bare_target(tmp_path)
    eng, events, _ = engine(tmp_path, stepwise_llm(), publish=str(target), publish_all=True, checkpoint_interval=0.0, push_interval=0.0)
    asyncio.run(eng.run())
    pushes = [d["branch"] for d in kinds_with(events, "mirrored")]
    assert pushes.count("feature/core") >= 2, pushes  # after the commits, after the task, and at the end of the feature, not once
    on_github = subprocess.run(["git", "--git-dir", str(target), "log", "--format=%s", f"--author=DEV_2", "integration/r1"], capture_output=True, text=True).stdout.splitlines()
    assert len(on_github) >= 2 and any(s.startswith("feat(core)") for s in on_github), on_github  # the small commits are on the user's repository too
