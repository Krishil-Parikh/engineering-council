"""The git brain: failed git steps are diagnosed and fixed, first by certain quick fixes, then by the developer's own agent."""

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from team.engine import TeamConfig, TeamEngine
from team.repo import RepoError, TeamRepo
from tests.team.fake_llm import TeamLLM
from tests.team.test_build import finished_meeting


def put(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def build(tmp_path, llm=None, **cfg):
    meeting, _ = finished_meeting(tmp_path)
    cfg.setdefault("plan_discussion_rounds", 0)
    eng = TeamEngine(meeting, tmp_path / "team", llm=llm or TeamLLM(), config=TeamConfig(run_id="r1", repair_rounds=0, **cfg))
    eng.repo.init()
    return eng


def run(coro):
    return asyncio.run(coro)


def shell(command):
    return ("tool", "shell", {"command": command})


def write(path, content):
    return ("tool", "write", {"path": path, "content": content})


# ------------------------------------------------------------------ certain fixes

def test_a_rejected_push_is_fixed_by_rebasing_without_asking_the_model(tmp_path):
    eng = build(tmp_path)
    repo = eng.repo
    repo.checkout_branch("ana", "feature/x")
    put(repo.sandbox("ana") / "a.txt", "a")
    repo.commit_all("ana", "ana's work")
    repo.push("ana")
    repo.checkout_branch("bob", "feature/x")  # bob resumes the same branch and moves the remote on
    put(repo.sandbox("bob") / "b.txt", "b")
    repo.commit_all("bob", "bob's work")
    repo.push("bob")
    put(repo.sandbox("ana") / "c.txt", "c")  # ana is now behind and has a new commit
    repo.commit_all("ana", "ana's second commit")

    run(eng.brain.run("ana", "publish feature/x", repo.push, "ana", "feature/x", branch="feature/x"))

    assert eng.llm.requests == []  # certain fix: no model involved
    assert [a.fixed_by for a in eng.brain.history] == ["quick:rebased feature/x onto origin/feature/x"]
    repo.fetch("viewer")
    for name in ("a.txt", "b.txt", "c.txt"):
        assert repo.file_at("viewer", "origin/feature/x", name) is not None


def test_a_stale_lock_file_is_removed(tmp_path):
    eng = build(tmp_path)
    repo = eng.repo
    repo.checkout_branch("ana", "feature/x")
    put(repo.sandbox("ana") / "a.txt", "a")
    lock = repo.sandbox("ana") / ".git" / "index.lock"
    lock.write_text("")
    old = time.time() - 120
    os.utime(lock, (old, old))

    assert run(eng.brain.run("ana", "commit", repo.commit_all, "ana", "work")) is True
    assert not lock.exists() and eng.brain.history[0].fixed_by.startswith("quick:removed stale lock")


def test_an_unfinished_merge_is_abandoned(tmp_path):
    eng = build(tmp_path)
    repo = eng.repo
    ana, bob = repo.sandbox("ana"), repo.sandbox("bob")
    repo.checkout_branch("ana", "integration/r1")
    put(ana / "f.txt", "0\n")
    repo.commit_all("ana", "base")
    repo.push("ana")
    repo.checkout_branch("bob", "feature/b", base="integration/r1")
    put(bob / "f.txt", "bob\n")
    repo.commit_all("bob", "b")
    repo.push("bob")
    put(ana / "f.txt", "ana\n")
    repo.commit_all("ana", "a")
    assert repo.merge("ana", "feature/b", "m").status == "conflict"  # ana is left mid-merge

    run(eng.brain.run("ana", "check out the integration branch", repo.checkout_branch, "ana", "feature/c", "integration/r1", branch="feature/c"))
    assert not repo.merging("ana")


# ------------------------------------------------------------------ the agent

def test_the_agent_is_shown_the_failure_and_fixes_it_with_git(tmp_path):
    llm = TeamLLM()
    llm.on(r"A git step failed", [shell("git stash"), ("text", "Uncommitted changes were in the way; I stashed them.")])
    eng = build(tmp_path, llm)
    repo = eng.repo
    ana = repo.sandbox("ana")
    repo.checkout_branch("ana", "integration/r1")
    put(ana / "f.txt", "base\n")
    repo.commit_all("ana", "base")
    repo.push("ana")
    repo.checkout_branch("bob", "feature/b", base="integration/r1")
    put(repo.sandbox("bob") / "f.txt", "bob's version\n")
    repo.commit_all("bob", "b")
    repo.push("bob")
    repo.checkout_branch("ana", "feature/b")
    repo.checkout_branch("ana", "integration/r1")
    put(ana / "f.txt", "ana's uncommitted edit\n")  # in the way of checking out feature/b

    run(eng.brain.run("ana", "check out feature/b", repo.checkout_branch, "ana", "feature/b", "integration/r1", branch="feature/b"))

    assert repo.current_branch("ana") == "feature/b" and (ana / "f.txt").read_text() == "bob's version\n"
    assert subprocess.run(["git", "stash", "list"], cwd=ana, capture_output=True, text=True).stdout.strip()  # the edit was kept, not lost
    prompt = next(m for r in eng.llm.requests for m in r.messages if "A git step failed" in str(m))
    text = " ".join(p.text for p in prompt.content)
    assert "THE STEP: check out feature/b" in text and "overwritten" in text and "git status -sb" in text
    assert eng.brain.history[0].fixed_by == "agent" and "stashed" in eng.brain.history[0].note


def test_the_agent_can_resolve_a_rebase_that_conflicts(tmp_path):
    llm = TeamLLM()
    llm.on(r"A git step failed", [
        shell("git fetch origin && git merge origin/feature/x"),
        write("f.txt", "ana + bob\n"),
        shell("git add -A && git commit -m \"merge origin/feature/x\""),
        ("text", "Both sides edited f.txt; I merged them."),
    ])
    eng = build(tmp_path, llm)
    repo = eng.repo
    repo.checkout_branch("ana", "feature/x")
    put(repo.sandbox("ana") / "f.txt", "0\n")
    repo.commit_all("ana", "base")
    repo.push("ana")
    repo.checkout_branch("bob", "feature/x")
    put(repo.sandbox("bob") / "f.txt", "bob\n")
    repo.commit_all("bob", "bob edit")
    repo.push("bob")
    put(repo.sandbox("ana") / "f.txt", "ana\n")
    repo.commit_all("ana", "ana edit")

    run(eng.brain.run("ana", "publish feature/x", repo.push, "ana", "feature/x", branch="feature/x"))

    repo.fetch("viewer")
    assert repo.file_at("viewer", "origin/feature/x", "f.txt") == "ana + bob\n"
    assert eng.brain.history[0].fixed_by == "agent"  # the quick rebase hit the conflict, so the agent took over


def test_an_agent_cannot_cheat_by_pushing_main_or_forcing(tmp_path):
    llm = TeamLLM()
    llm.on(r"A git step failed", [shell("git push origin HEAD:main"), shell("git push --force origin feature/x"), ("text", "I tried everything.")])
    eng = build(tmp_path, llm, git_fix_rounds=1)
    repo = eng.repo
    repo.checkout_branch("ana", "feature/x")
    put(repo.sandbox("ana") / "a.txt", "a")
    repo.commit_all("ana", "work")

    def refuses(*args):
        raise RepoError("push of feature/x refused: something nobody can fix")

    with pytest.raises(RepoError, match="still failing after 1 repair attempt"):
        run(eng.brain.run("ana", "publish feature/x", refuses, branch="feature/x"))
    repo.fetch("viewer")
    assert repo.file_at("viewer", "origin/main", "a.txt") is None and "feature/x" not in repo.branches("viewer")
    results = [str(m) for r in eng.llm.requests for m in r.messages if getattr(m, "role", "") == "tool"]
    assert any("denied" in t.lower() or "permission" in t.lower() or "reject" in t.lower() for t in results)


def test_when_nothing_works_the_failure_is_reported_with_its_history(tmp_path):
    llm = TeamLLM()
    llm.on(r"A git step failed", [("text", "I could not find the cause.")])
    eng = build(tmp_path, llm, git_fix_rounds=2)
    events = []
    eng.brain.emit = lambda kind, **data: events.append(kind)

    def always(*args):
        raise RepoError("remote said no")

    with pytest.raises(RepoError, match="still failing after 2 repair attempt.*remote said no"):
        run(eng.brain.run("ana", "do the impossible", always))
    assert events.count("git-trouble") == 2 and events[-1] == "git-gave-up" and len(eng.brain.history) == 3


# ------------------------------------------------------------------ inside a real run

def flaky_remote(eng, branch, refusals=1):
    """The remote refuses the first `refusals` pushes of `branch` ('server is busy') and accepts later ones."""
    hook = eng.repo.origin / "hooks" / "update"
    marker = (eng.repo.origin / "flaky_seen").as_posix()
    script = (
        "#!/bin/sh" + chr(10) + f'n=$(cat "{marker}" 2>/dev/null || echo 0)' + chr(10)
        + f'if [ "$1" = "refs/heads/{branch}" ] && [ "$n" -lt {refusals} ]; then' + chr(10)
        + f'  echo $((n+1)) > "{marker}"' + chr(10)
        + '  echo "remote: server is busy, try again" >&2' + chr(10) + "  exit 1" + chr(10) + "fi" + chr(10) + "exit 0" + chr(10)
    )
    hook.write_bytes(script.encode())
    os.chmod(hook, 0o755)


def one_feature_plan(owner="DEV_2"):
    return {"features": [{"id": "flaky", "title": "Flaky", "owner": owner, "tasks": [{"title": "write flaky"}]}]}


def test_a_developer_whose_push_fails_reads_the_error_and_pushes_again(tmp_path):
    llm = TeamLLM()
    llm.on(r"Turn the agreed specification", [("text", json.dumps(one_feature_plan()))])
    llm.on(r"Task: write flaky", [
        write("flaky.py", "x = 1\n"),
        shell("git add -A && git commit -m flaky && git push origin feature/flaky"),  # refused: the server is busy
        shell("git push origin feature/flaky"),  # the developer reads the message and tries again
        ("text", "published after one retry"),
    ])
    eng = build(tmp_path, llm)
    flaky_remote(eng, "feature/flaky")
    result = run(eng.run())
    assert [f.status for f in result.features] == ["merged"]
    assert not eng.brain.history  # the developer coped on their own; the engine never had to step in
    assert TeamRepo(tmp_path / "team" / "remote").file_at("viewer", "origin/final/r1", "flaky.py") == "x = 1\n"


def test_if_the_developer_does_not_push_the_engines_brain_gets_it_published(tmp_path):
    llm = TeamLLM()
    llm.on(r"Turn the agreed specification", [("text", json.dumps(one_feature_plan()))])
    llm.on(r"Task: write flaky", [write("flaky.py", "x = 2\n"), ("text", "done, but I forgot to push")])
    llm.on(r"A git step failed", [shell("git push origin feature/flaky"), ("text", "The server was busy; I pushed again.")])
    eng = build(tmp_path, llm)
    eng.cfg.checkpoint_commits = False  # only the engine's own pushes: the one after the task (quietly retried later) and the one that has to succeed
    flaky_remote(eng, "feature/flaky", refusals=2)
    result = run(eng.run())
    assert [f.status for f in result.features] == ["merged"]
    assert [a.fixed_by for a in eng.brain.history] == ["agent"] and "server is busy" in eng.brain.history[0].error
    assert TeamRepo(tmp_path / "team" / "remote").file_at("viewer", "origin/final/r1", "flaky.py") == "x = 2\n"


def test_developers_cannot_push_the_integration_branch_but_the_integrator_can(tmp_path):
    from harness.permission import evaluate
    from team.persona import rules_for

    dev, integrator = rules_for("DEV_1"), rules_for("integrator", integrator=True)
    assert evaluate("shell", "git push origin feature/a", dev).effect == "allow"
    assert evaluate("shell", "git push origin integration/r1", dev).effect == "deny"
    assert evaluate("shell", "git push origin integration/r1", integrator).effect == "allow"
    for rules in (dev, integrator):
        assert all(evaluate("shell", c, rules).effect == "deny" for c in ("git push origin main", "git push origin HEAD:main", "git push -f origin feature/a"))
        assert evaluate("edit", ".git/hooks/pre-push", rules).effect == "deny"
