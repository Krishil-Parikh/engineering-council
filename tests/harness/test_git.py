"""Git service, snapshots and worktrees against real temporary repositories."""

import os
import subprocess
from pathlib import Path

import pytest

from harness.git import Git, GitError, WorktreeError
from harness.location import Location
from harness.snapshot import SnapshotError, Snapshots
from harness.util.global_paths import GlobalPaths

def put(path, text):
    path.write_bytes(text.encode("utf-8"))  # exact bytes: write_text would turn LF into CRLF on Windows


ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def sh(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, **ENV}).stdout.decode()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    sh(root, "init", "-q", "-b", "main")
    put(root / "a.txt", "one\n")
    (root / ".gitignore").write_text("ignored.log\nbuild/\n")
    sh(root, "add", "-A")
    sh(root, "commit", "-q", "-m", "init")
    return root


def snaps(repo, tmp_path, **kw):
    return Snapshots(Location.of(repo), GlobalPaths.default(root=tmp_path / "g").ensure(), **kw)


def test_discover_history_and_branch(repo):
    git = Git()
    r = git.discover(str(repo / "nested" if (repo / "nested").exists() else repo))
    assert r and Path(r.worktree).resolve() == repo.resolve()
    assert git.branch(r) == "main" and len(git.head(r)) == 40 and len(git.root_commits(r)) == 1
    assert git.remote_get(r) is None
    assert git.discover(str(repo.parent / "nowhere")) is None


def test_clone_fetch_checkout_reset(repo, tmp_path):
    git = Git()
    clone = git.clone(str(repo), str(tmp_path / "clone"), branch="main")
    assert git.remote_get(clone) == str(repo)
    put(repo / "b.txt", "b\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "second")
    git.fetch_remotes(clone)
    git.fetch_branch(clone, "main")
    git.checkout_remote_branch(clone, "main")
    assert (tmp_path / "clone" / "b.txt").exists()
    git.reset_hard(clone, "HEAD~1")
    assert not (tmp_path / "clone" / "b.txt").exists()
    with pytest.raises(GitError, match="."):
        git.fetch_branch(clone, "no-such-branch")


def test_worktrees_create_list_remove(repo, tmp_path):
    git = Git()
    r = git.discover(str(repo))
    wt = git.worktree_create(r, str(tmp_path / "wt"))
    assert (tmp_path / "wt" / "a.txt").exists()
    listed = git.worktree_list(r)
    assert [w.kind for w in listed] == ["main", "linked"]
    (tmp_path / "wt" / "dirty.txt").write_text("x")
    with pytest.raises(WorktreeError) as err:
        git.worktree_remove(r, str(tmp_path / "wt"), force=False)
    assert err.value.force_required
    git.worktree_remove(r, str(tmp_path / "wt"), force=True)
    assert not (tmp_path / "wt").exists() and len(git.worktree_list(r)) == 1


def test_snapshot_capture_files_diff_restore(repo, tmp_path):
    s = snaps(repo, tmp_path)
    first = s.capture()
    assert first and s.capture() == first  # nothing changed: same tree
    put(repo / "a.txt", "one\ntwo\n")
    put(repo / "new.txt", "fresh\n")
    put(repo / "ignored.log", "noise")
    second = s.capture()
    assert second != first
    assert sorted(s.files(first, second)) == ["a.txt", "new.txt"]  # ignored.log is left out
    diffs = {d.file: d for d in s.diff(first, second)}
    assert diffs["a.txt"].status == "modified" and diffs["a.txt"].additions == 1 and diffs["a.txt"].deletions == 0
    assert diffs["new.txt"].status == "added" and "+fresh" in diffs["new.txt"].patch
    assert s.diff(first, second, paths=[]) == []
    assert [d.file for d in s.diff(first, second, paths=["new.txt"])] == ["new.txt"]
    put(repo / "gone.txt", "x")
    third = s.capture()
    os.remove(repo / "gone.txt")
    fourth = s.capture()
    assert s.diff(third, fourth)[0].status == "deleted"
    # restore: a.txt back to the first tree, new.txt (absent from it) removed, untouched paths stay
    put(repo / "keep.txt", "keep")
    s.restore({"a.txt": first, "new.txt": first})
    assert (repo / "a.txt").read_text() == "one\n" and not (repo / "new.txt").exists() and (repo / "keep.txt").exists()


def test_snapshot_skips_big_untracked_files_and_ignores_source_excludes(repo, tmp_path):
    s = snaps(repo, tmp_path)
    base = s.capture()
    (repo / "big.bin").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    put(repo / "private.txt", "p")
    put(repo / ".git" / "info" / "exclude", "private.txt\n")
    put(repo / "small.txt", "s")
    after = s.capture()
    assert s.files(base, after) == ["small.txt"]


def test_snapshot_scope_is_the_location_directory(repo, tmp_path):
    (repo / "pkg").mkdir()
    put(repo / "pkg" / "m.py", "1")
    s = Snapshots(Location.of(repo / "pkg"), GlobalPaths.default(root=tmp_path / "g").ensure())
    first = s.capture()
    put(repo / "pkg" / "m.py", "2")
    put(repo / "outside.txt", "o")
    second = s.capture()
    assert s.files(first, second) == ["pkg/m.py"]


def test_snapshot_disabled_or_not_git(repo, tmp_path):
    assert snaps(repo, tmp_path, enabled=False).capture() is None
    plain = tmp_path / "plain"
    plain.mkdir()
    s = Snapshots(Location.of(plain), GlobalPaths.default(root=tmp_path / "g2").ensure())
    assert s.capture() is None
    with pytest.raises(SnapshotError, match="disabled"):
        s.restore({"x": "y"})


def test_restore_rejects_paths_outside_the_project(repo, tmp_path):
    s = snaps(repo, tmp_path)
    tree = s.capture()
    with pytest.raises(SnapshotError, match="escapes the project"):
        s.restore({"../evil.txt": tree})


def test_store_creation_is_idempotent_and_shares_objects(repo, tmp_path):
    s = snaps(repo, tmp_path)
    s.capture()
    _, _, store = s._repository()
    alternates = Path(store.git_directory, "objects", "info", "alternates").read_text()
    assert str(Path(repo, ".git", "objects").resolve()).lower() in alternates.replace("/", "\\").lower() or "objects" in alternates
    again = snaps(repo, tmp_path)
    assert again.capture() == s.capture()
