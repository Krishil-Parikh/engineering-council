"""The team's git layout: protected main, per-developer sandboxes, branches, merges and conflicts (real git)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from team.repo import MergeResult, RepoError, TeamRepo, _force_remove, slugify


def put(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


@pytest.fixture
def repo(tmp_path):
    r = TeamRepo(tmp_path / "team")
    r.init()
    return r


def test_new_project_gets_a_protected_main(repo):
    assert repo.branches("ana") == ["main"]
    assert (repo.sandbox("ana") / "README.md").exists()


def test_existing_repository_seeds_main_from_its_current_commit(tmp_path):
    src = tmp_path / "existing"
    src.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    import os

    for args in (["init", "-q", "-b", "trunk"], ["add", "-A"]):
        if args[0] == "add":
            put(src / "app.py", "print(1)\n")
        subprocess.run(["git", *args], cwd=src, check=True, env={**os.environ, **env})
    subprocess.run(["git", "commit", "-q", "-m", "first"], cwd=src, check=True, env={**os.environ, **env})
    r = TeamRepo(tmp_path / "team")
    r.init(src)
    assert r.branches("ana") == ["main"] and (r.sandbox("ana") / "app.py").read_text() == "print(1)\n"


def test_plain_folder_becomes_the_first_commit(tmp_path):
    src = tmp_path / "plain"
    put(src / "docs" / "a.md", "hello")
    r = TeamRepo(tmp_path / "team")
    r.init(src)
    assert (r.sandbox("ana") / "docs" / "a.md").read_text() == "hello"


def test_init_is_idempotent(repo):
    repo.init()
    assert repo.branches("ana") == ["main"]


def test_nobody_but_the_human_can_update_main(repo):
    ana = repo.sandbox("ana")
    repo.checkout_branch("ana", "feature/x")
    put(ana / "x.txt", "x")
    assert repo.commit_all("ana", "add x")
    repo.push("ana")  # a feature branch is fine
    assert "feature/x" in repo.branches("ana")

    subprocess.run(["git", "checkout", "-q", "-B", "main", "origin/main"], cwd=ana, check=True)
    put(ana / "y.txt", "y")
    repo.commit_all("ana", "straight to main")
    with pytest.raises(RepoError, match="protected"):  # the developer's own clone refuses first
        repo.push("ana", "main")
    bypass = subprocess.run(["git", "push", "--no-verify", "origin", "HEAD:refs/heads/main"], cwd=ana, capture_output=True)
    assert bypass.returncode != 0 and b"protected" in bypass.stderr  # and the remote refuses even when that hook is skipped
    repo.human_push("ana", "main", "main")  # the human can
    repo.fetch("bob")
    assert repo.file_at("bob", "origin/main", "y.txt") == "y"


def test_sandboxes_are_separate_working_trees(repo):
    a, b = repo.sandbox("ana"), repo.sandbox("bob")
    assert a != b
    repo.checkout_branch("ana", "feature/a")
    put(a / "only_ana.txt", "a")
    assert not (b / "only_ana.txt").exists()
    assert subprocess.run(["git", "config", "user.name"], cwd=b, capture_output=True, text=True).stdout.strip() == "bob (Council)"


def test_new_branch_starts_from_the_requested_base_and_existing_ones_resume(repo):
    repo.checkout_branch("ana", "integration/run1")
    put(repo.sandbox("ana") / "base.txt", "base")
    repo.commit_all("ana", "base work")
    repo.push("ana")
    repo.checkout_branch("bob", "feature/b", base="integration/run1")
    assert (repo.sandbox("bob") / "base.txt").exists()
    put(repo.sandbox("bob") / "b.txt", "b")
    repo.commit_all("bob", "b work")
    repo.push("bob")
    repo.checkout_branch("ana", "feature/b")  # someone else resumes the pushed branch
    assert (repo.sandbox("ana") / "b.txt").exists() and repo.current_branch("ana") == "feature/b"


def test_commit_all_reports_nothing_to_commit(repo):
    repo.checkout_branch("ana", "feature/n")
    assert repo.commit_all("ana", "nothing") is False


def test_clean_merge_and_up_to_date(repo):
    repo.checkout_branch("ana", "integration/r")
    repo.push("ana")
    repo.checkout_branch("bob", "feature/b", base="integration/r")
    put(repo.sandbox("bob") / "b.txt", "b")
    repo.commit_all("bob", "b")
    repo.push("bob")
    repo.checkout_branch("ana", "integration/r")
    result = repo.merge("ana", "feature/b", "Merge feature/b")
    assert result.status == "merged" and (repo.sandbox("ana") / "b.txt").exists()
    assert repo.merge("ana", "feature/b", "again").status == "up-to-date"
    assert repo.changed_files("ana", "main") == ["b.txt"]
    assert repo.log("ana")[0].endswith("Merge feature/b")


def test_conflict_is_reported_resolved_and_finished(repo):
    ana, bob = repo.sandbox("ana"), repo.sandbox("bob")
    repo.checkout_branch("ana", "integration/r")
    put(ana / "app.py", "x = 0\n")
    repo.commit_all("ana", "base")
    repo.push("ana")
    repo.checkout_branch("bob", "feature/b", base="integration/r")
    put(bob / "app.py", "x = 'bob'\n")
    repo.commit_all("bob", "bob edit")
    repo.push("bob")
    put(ana / "app.py", "x = 'ana'\n")
    repo.commit_all("ana", "ana edit")
    result = repo.merge("ana", "feature/b", "Merge feature/b")
    assert result.status == "conflict" and result.files == ["app.py"] and repo.merging("ana")
    text = repo.conflict_text("ana")["app.py"]
    assert "<<<<<<<" in text and "'bob'" in text and "'ana'" in text
    with pytest.raises(RepoError, match="conflict markers remain in: app.py"):
        repo.finish_merge("ana", "resolve")
    put(ana / "app.py", "x = 'both'\n")
    repo.finish_merge("ana", "Merge feature/b (resolved with bob)")
    assert not repo.merging("ana") and repo.file_at("ana", "HEAD", "app.py") == "x = 'both'\n"


def test_abort_merge_restores_the_branch(repo):
    ana, bob = repo.sandbox("ana"), repo.sandbox("bob")
    repo.checkout_branch("ana", "integration/r")
    put(ana / "f.txt", "0\n")
    repo.commit_all("ana", "base")
    repo.push("ana")
    repo.checkout_branch("bob", "feature/b", base="integration/r")
    put(bob / "f.txt", "bob\n")
    repo.commit_all("bob", "b")
    repo.push("bob")
    put(ana / "f.txt", "ana\n")
    repo.commit_all("ana", "a")
    assert repo.merge("ana", "feature/b", "m").status == "conflict"
    repo.abort_merge("ana")
    assert not repo.merging("ana") and (ana / "f.txt").read_text() == "ana\n"


def test_slugify():
    assert slugify("Add Login / OAuth2!") == "add-login-oauth2" and slugify("???") == "work" and len(slugify("x" * 100)) <= 48


# ------------------------------------------------------------------ existing repositories

def make_source(tmp_path, branch="trunk"):
    import os

    src = tmp_path / "existing"
    src.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    put(src / "app.py", "print('v1')\n")
    put(src / "old.py", "print('old')\n")
    put(src / ".gitignore", "secret.env\nbuild/\n")
    for args in (["init", "-q", "-b", branch], ["add", "-A"], ["commit", "-q", "-m", "first"]):
        subprocess.run(["git", *args], cwd=src, check=True, env=env)
    return src


def test_the_trunk_keeps_its_own_name_and_is_protected(tmp_path):
    src = make_source(tmp_path, "trunk")
    assert TeamRepo.detect_main(src) == "trunk" and TeamRepo.detect_main(None) == "main" and TeamRepo.detect_main(tmp_path / "plain") == "main"
    repo = TeamRepo(tmp_path / "team", main_branch="trunk")
    repo.init(src)
    assert repo.branches("ana") == ["trunk"] and set(repo.protected) >= {"trunk", "main", "master"}
    ana = repo.sandbox("ana")
    subprocess.run(["git", "checkout", "-q", "-B", "trunk", "origin/trunk"], cwd=ana, check=True)
    put(ana / "x.txt", "x")
    repo.commit_all("ana", "straight to trunk")
    with pytest.raises(RepoError, match="protected"):
        repo.push("ana", "trunk")
    bypass = subprocess.run(["git", "push", "--no-verify", "origin", "HEAD:refs/heads/trunk"], cwd=ana, capture_output=True)
    assert bypass.returncode != 0 and b"protected" in bypass.stderr


def test_uncommitted_work_is_part_of_the_starting_point(tmp_path):
    src = make_source(tmp_path)
    put(src / "app.py", "print('v2, not committed')\n")  # edited
    put(src / "new.py", "print('new')\n")  # untracked
    (src / "old.py").unlink()  # deleted
    put(src / "secret.env", "TOKEN=1")  # ignored
    put(src / "build" / "out.bin", "x")  # ignored folder
    repo = TeamRepo(tmp_path / "team", main_branch="trunk")
    repo.init(src)
    ana = repo.sandbox("ana")
    assert (ana / "app.py").read_text() == "print('v2, not committed')\n" and (ana / "new.py").exists()
    assert not (ana / "old.py").exists() and not (ana / "secret.env").exists() and not (ana / "build").exists()
    assert repo.seed_notes == ["3 uncommitted change(s) in the repository were included in the team's starting point"]
    assert repo.log("ana")[0].endswith("Working tree of the repository when the team started") and repo.log("ana")[1].endswith("first")


def test_a_clean_repository_adds_no_extra_commit(tmp_path):
    src = make_source(tmp_path)
    repo = TeamRepo(tmp_path / "team", main_branch="trunk")
    repo.init(src)
    assert repo.seed_notes == [] and repo.log("ana") == [repo.log("ana")[0]] and repo.log("ana")[0].endswith("first")


def test_a_repository_with_no_commits_is_treated_as_a_new_project(tmp_path):
    """A freshly created (empty) repository, for example an empty GitHub repo that was cloned, has a .git folder and nothing else."""
    import subprocess

    source = tmp_path / "empty"
    source.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=source, check=True)
    repo = TeamRepo(tmp_path / "remote", main_branch=TeamRepo.detect_main(source))
    repo.init(source)
    assert repo.branches("dev-1") == ["main"] and repo.file_at("dev-1", "origin/main", "README.md") is not None


def test_github_credentials_are_added_for_this_process_only(tmp_path, monkeypatch):
    import os

    import team.cli as cli

    monkeypatch.delenv("GIT_CONFIG_PARAMETERS", raising=False)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    assert cli.use_github_credentials() is False and "GIT_CONFIG_PARAMETERS" not in os.environ
    monkeypatch.setattr(cli.shutil, "which", lambda name: "gh")
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 0})())
    assert cli.use_github_credentials() is True
    value = os.environ["GIT_CONFIG_PARAMETERS"]
    assert "credential.https://github.com.helper=!gh auth git-credential" in value and value.startswith("'credential.https://github.com.helper='")
    monkeypatch.delenv("GIT_CONFIG_PARAMETERS")


def _shallow_clone(tmp_path):
    def git(*args, cwd=None):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)

    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "-q", cwd=origin)
    for n in range(3):
        put(origin / f"f{n}.txt", str(n))
        git("add", "-A", cwd=origin)
        git("commit", "-q", "-m", f"c{n}", cwd=origin)
    clone = tmp_path / "clone"
    git("clone", "-q", "--depth", "1", origin.as_uri(), str(clone))
    assert (clone / ".git" / "shallow").exists()
    return origin, clone


def test_a_shallow_source_is_given_its_full_history_and_seeds_main(tmp_path):
    """The meeting clones with --depth 1; git refuses to push from a shallow clone, so the full history is fetched first."""
    _origin, clone = _shallow_clone(tmp_path)
    r = TeamRepo(tmp_path / "team")
    r.init(clone)
    assert r.branches("ana") == ["main"]
    assert not (clone / ".git" / "shallow").exists()
    assert (r.sandbox("ana") / "f2.txt").exists()


def test_a_shallow_source_that_cannot_be_completed_still_seeds_main(tmp_path):
    origin, clone = _shallow_clone(tmp_path)
    shutil.rmtree(origin, onerror=_force_remove)  # its remote is gone: the history cannot be fetched
    r = TeamRepo(tmp_path / "team")
    r.init(clone)
    assert r.branches("ana") == ["main"]
    assert (r.sandbox("ana") / "f2.txt").exists()
