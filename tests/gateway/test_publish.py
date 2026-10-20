"""The question "I saw '6 features merged' but there was nothing on GitHub": what reaches the user's repository, and when.

A local repository with its own bare remote stands in for the user's GitHub repository. A whole scripted run goes through the gateway on it."""

import subprocess
import time

from tests.gateway.conftest import command, drive, open_questions, snapshot, wait_for


def git(*args, cwd=None):
    out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout


def heads(remote):
    return {line.split("\t")[1].removeprefix("refs/heads/"): line.split("\t")[0] for line in git("ls-remote", "--heads", str(remote)).splitlines()}


def test_branches_reach_the_users_repository_as_the_team_works_and_never_main(client, tmp_path):
    remote = tmp_path / "github.git"
    git("init", "-q", "--bare", "-b", "main", str(remote))
    work = tmp_path / "work"
    git("clone", "-q", str(remote), str(work))
    (work / "README.md").write_text("# existing project\n")
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "first", cwd=work)
    git("push", "-q", "origin", "HEAD:main", cwd=work)
    main_before = heads(remote)["main"]

    started = command(client, type="sprint.start", brief="# Project: Todo CLI\n\nA small task list.", repo=str(work))
    assert started.status_code == 200 and started.json()["accepted"] is True

    # before anything is built there is nothing to push
    drive(client, lambda s: s["phaseId"] == "prd" and any(q["question"]["kind"] == "documents" for q in open_questions(s)), what="the documents")
    assert set(heads(remote)) == {"main"}
    assert command(client, type="prd.accept", artifactId="art-prd").json()["accepted"] is True

    # while the team works, every branch appears in the user's repository as it is created and merged (not only at the end), and main never moves
    snap = drive(client, lambda s: s["metrics"]["totalPRs"] >= 1, what="a first merged feature", timeout=300)
    midway = heads(remote)
    assert any(name.startswith("integration/") for name in midway) and any(name.startswith("feature/") for name in midway), midway
    assert midway["main"] == main_before and snap["phaseId"] != "ship"
    assert any(m["text"].startswith("GitHub: pushed ") for m in snap["messages"])  # and the browser says so

    # when the run is over, the final branch is there too
    snap = drive(client, lambda s: s["phaseId"] == "ship", what="the run to finish", timeout=420)
    pushed = heads(remote)
    assert pushed["main"] == main_before, "main must never be touched"
    assert any(name.startswith("final/") for name in pushed), pushed
    assert any(name.startswith("integration/") for name in pushed), pushed
    assert sum(1 for name in pushed if name.startswith("feature/")) >= 3, pushed
    texts = " ".join(m["text"] for m in snap["messages"])
    assert "Pushed" in texts  # the browser is told where they went
