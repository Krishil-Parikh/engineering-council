"""Git, driven through the command line (opencode: packages/core/src/git.ts).

Three jobs. (1) Ordinary repository work: discover, clone, fetch, check out, reset, worktrees. (2) A private "snapshot" repository that
uses a project directory as its work tree and shares the source repository's objects: `tree_capture` records the files as a content-
addressed tree, and trees can be compared (`tree_files`, `tree_diff`) and restored. (3) Housekeeping for that store (`pack`).

All calls are synchronous; async callers run them with `asyncio.to_thread`. The snapshot store ignores whatever the source repository
ignores: its tracked files are never recorded, and untracked files larger than `maximum_untracked_file_bytes` are skipped.

Deviation: opencode refreshes the snapshot index with a threaded diff-files/ls-files pair and update-index; we use `git add -A` on the
scope, which does the same job with less code and the same ignore semantics."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from harness.tool.file_diff import FileDiff

SNAPSHOT_CONFIG_FILE = "harness.gitconfig"
SNAPSHOT_CONFIG_INCLUDE = f"[include]\n\tpath = {SNAPSHOT_CONFIG_FILE}\n"
SNAPSHOT_CONFIG = """[core]
	autocrlf = false
	longpaths = true
	symlinks = true
	fsmonitor = false
	untrackedCache = true
	# A split index cannot name its shared file once manyFiles skips index checksums.
	splitIndex = false
[feature]
	manyFiles = true
[index]
	version = 4
	threads = true
"""
ARGUMENT_BUDGET = 24_000 if sys.platform == "win32" else 128 * 1024
LOOSE_OBJECT_LIMIT = 2048
PACK_COUNT_LIMIT = 16
PACK_LOCK_STALE_SECONDS = 60 * 60
IDENTITY = ["-c", "user.name=harness", "-c", "user.email=harness@localhost"]


@dataclass(frozen=True)
class Repository:
    worktree: str
    git_directory: str
    common_directory: str


@dataclass(frozen=True)
class Worktree:
    directory: str
    kind: str  # main | linked


class GitError(Exception):
    def __init__(self, operation: str, message: str, directory: Optional[str] = None) -> None:
        super().__init__(message)
        self.operation, self.message, self.directory = operation, message, directory


class WorktreeError(GitError):
    def __init__(self, operation: str, message: str, directory: Optional[str] = None, force_required: bool = False) -> None:
        super().__init__(operation, message, directory)
        self.force_required = force_required


@dataclass
class Result:
    code: int
    stdout: bytes
    stderr: bytes

    @property
    def text(self) -> str:
        return self.stdout.decode("utf-8", "replace")

    @property
    def err(self) -> str:
        return self.stderr.decode("utf-8", "replace")


def run(args: list[str], cwd: str, env: Optional[dict[str, str]] = None, stdin: Optional[bytes] = None) -> Result:
    """Raises OSError if git cannot be started; a non-zero exit is reported in the result."""
    proc = subprocess.run(
        ["git", *args], cwd=cwd, input=stdin if stdin is not None else None, stdin=None if stdin is not None else subprocess.DEVNULL,
        capture_output=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}, timeout=600,
    )
    return Result(proc.returncode, proc.stdout, proc.stderr)


def _resolve(base: str, value: str) -> str:
    return os.path.normpath(value if os.path.isabs(value) else os.path.join(base, value))


def _nuls(text: str) -> list[str]:
    return [p for p in text.split("\0") if p]


def literal_pathspec(path: str) -> str:
    return f":(literal){path}"


def _git_args(repo: Repository, args: list[str]) -> list[str]:
    return ["--git-dir", repo.git_directory, "--work-tree", repo.worktree, *args]


class Git:
    # ------------------------------------------------------------------ repositories

    def discover(self, start: str) -> Optional[Repository]:
        here = Path(start).resolve()
        for candidate in [here, *here.parents]:
            if (candidate / ".git").exists():
                cwd = str(candidate)
                break
        else:
            return None
        result = run(["rev-parse", "--git-dir", "--git-common-dir", "--show-toplevel"], cwd)
        if result.code != 0:
            return None
        lines = result.text.splitlines()
        if len(lines) < 2:
            return None
        git_dir, common_dir = lines[0], lines[1]
        top = lines[2] if len(lines) > 2 else None
        return Repository(_resolve(cwd, top) if top else cwd, _resolve(cwd, git_dir), _resolve(cwd, common_dir))

    def _operation(self, operation: str, directory: str, args: list[str]) -> None:
        try:
            result = run(args, directory)
        except OSError as exc:
            raise GitError(operation, str(exc), directory) from exc
        if result.code != 0:
            raise GitError(operation, result.err.strip() or result.text.strip() or f"Git {operation} failed", directory)

    def clone(self, remote: str, directory: str, branch: Optional[str] = None, depth: int = 100) -> Repository:
        self._operation("clone", os.path.dirname(directory), ["clone", "--depth", str(depth), *(["--branch", branch] if branch else []), "--", remote, directory])
        repo = self.discover(directory)
        if repo is None:
            raise GitError("clone", "Cloned repository could not be opened", directory)
        return repo

    def remote_get(self, repo: Repository, name: str = "origin") -> Optional[str]:
        result = run(["remote", "get-url", name], repo.worktree)
        return result.text.strip() or None if result.code == 0 else None

    def head(self, repo: Repository) -> Optional[str]:
        result = run(["rev-parse", "HEAD"], repo.worktree)
        return result.text.strip() or None if result.code == 0 else None

    def branch(self, repo: Repository) -> Optional[str]:
        result = run(["symbolic-ref", "--quiet", "--short", "HEAD"], repo.worktree)
        return result.text.strip() or None if result.code == 0 else None

    def default_remote_branch(self, repo: Repository, remote: str = "origin") -> Optional[str]:
        result = run(["symbolic-ref", f"refs/remotes/{remote}/HEAD"], repo.worktree)
        if result.code != 0:
            return None
        return re.sub(rf"^refs/remotes/{re.escape(remote)}/", "", result.text.strip()) or None

    def root_commits(self, repo: Repository) -> list[str]:
        result = run(["rev-list", "--max-parents=0", "HEAD"], repo.worktree)
        return sorted(l.strip() for l in result.text.splitlines() if l.strip()) if result.code == 0 else []

    def fetch_remotes(self, repo: Repository, prune: bool = True) -> None:
        self._operation("fetch", repo.worktree, ["fetch", "--all", *(["--prune"] if prune else [])])

    def fetch_branch(self, repo: Repository, branch: str, remote: str = "origin", force: bool = True) -> None:
        spec = f"refs/heads/{branch}:refs/remotes/{remote}/{branch}"
        self._operation("fetch", repo.worktree, ["fetch", remote, f"+{spec}" if force else spec])

    def checkout_remote_branch(self, repo: Repository, branch: str, remote: str = "origin", reset: bool = True) -> None:
        self._operation("checkout", repo.worktree, ["checkout", *(["-B", branch, f"{remote}/{branch}"] if reset else [branch])])

    def reset_hard(self, repo: Repository, revision: str) -> None:
        self._operation("reset", repo.worktree, ["reset", "--hard", revision])

    # ------------------------------------------------------------------ worktrees

    def _worktree_run(self, operation: str, args: list[str], cwd: str, directory: Optional[str] = None) -> str:
        try:
            result = run(args, cwd)
        except OSError as exc:
            raise WorktreeError(operation, str(exc), directory) from exc
        if result.code == 0:
            return result.text
        message = result.err.strip() or result.text.strip() or "Git failed"
        raise WorktreeError(operation, message, directory, operation == "remove" and bool(re.search(r"contains modified or untracked files|is dirty", message, re.I)))

    def worktree_create(self, repo: Repository, directory: str, ref: Optional[str] = None) -> Repository:
        self._worktree_run("create", ["worktree", "add", "--detach", "--", directory, ref or "HEAD"], repo.worktree, directory)
        created = self.discover(directory)
        if created is None:
            raise WorktreeError("create", "Created worktree could not be opened", directory)
        return created

    def worktree_remove(self, repo: Repository, directory: str, force: bool) -> None:
        self._worktree_run("remove", ["worktree", "remove", *(["--force"] if force else []), directory], repo.common_directory, directory)

    def worktree_list(self, repo: Repository) -> list[Worktree]:
        text = self._worktree_run("list", ["worktree", "list", "--porcelain"], repo.worktree)
        lines = [l for l in text.splitlines() if l.startswith("worktree ")]
        return [Worktree(_resolve(repo.worktree, l[len("worktree "):].strip()), "main" if i == 0 else "linked") for i, l in enumerate(lines)]

    # ------------------------------------------------------------------ the snapshot store

    def _repo_op(self, operation: str, repo: Repository, args: list[str], stdin: Optional[bytes] = None, env: Optional[dict[str, str]] = None) -> Result:
        try:
            result = run(_git_args(repo, args), repo.worktree, env, stdin)
        except OSError as exc:
            raise GitError(operation, str(exc), repo.worktree) from exc
        if result.code != 0:
            raise GitError(operation, result.err.strip() or result.text.strip() or f"Git {operation} failed", repo.worktree)
        return result

    def create(self, worktree: str, git_directory: str, seed: Optional[Repository] = None) -> Repository:
        """Creates (or adopts) a snapshot store at git_directory. A store is initialised beside its destination and renamed into place, so
        processes racing to create the same store never see a half-built one; the loser adopts the winner's."""
        repo = Repository(worktree, git_directory, git_directory)
        if (Path(git_directory) / "HEAD").exists():
            self._init(worktree, git_directory, git_directory, seed)
            return repo
        temporary = f"{git_directory}.init-{uuid.uuid4().hex[:8]}"
        try:
            self._init(worktree, git_directory, temporary, seed)
            try:
                os.rename(temporary, git_directory)
            except OSError as exc:
                if not (Path(git_directory) / "HEAD").exists():
                    raise GitError("create", "Failed to move Git storage into place", git_directory) from exc
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        return repo

    def _init(self, worktree: str, git_directory: str, directory: str, seed: Optional[Repository]) -> None:
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            raise GitError("create", "Failed to create Git storage", git_directory) from exc
        self._repo_op("create", Repository(worktree, directory, directory), ["init"])
        try:
            Path(directory, SNAPSHOT_CONFIG_FILE).write_text(SNAPSHOT_CONFIG, encoding="utf-8")
            config = Path(directory, "config")
            current = config.read_text(encoding="utf-8")
            if SNAPSHOT_CONFIG_INCLUDE not in current:
                config.write_text(current + ("\n" if current.endswith("\n") else "\n\n") + SNAPSHOT_CONFIG_INCLUDE, encoding="utf-8")
        except OSError as exc:
            raise GitError("create", "Failed to configure Git storage", git_directory) from exc
        if seed is None:
            return
        try:
            info = Path(directory, "objects", "info")
            info.mkdir(parents=True, exist_ok=True)
            (info / "alternates").write_bytes((os.path.join(seed.common_directory, "objects") + "\n").encode("utf-8"))  # LF even on Windows
        except OSError as exc:
            raise GitError("create", "Failed to configure shared Git objects", git_directory) from exc
        try:
            shutil.copyfile(Path(seed.git_directory, "index"), Path(directory, "index"))
        except OSError:
            pass

    def ignored(self, repo: Repository, paths: Iterable[str]) -> set[str]:
        """Which of the project-relative paths the repository's ignore rules exclude."""
        out: set[str] = set()
        batch = [p for p in paths]
        if not batch:
            return out
        for chunk in _chunks(batch):
            result = run(["check-ignore", "--no-index", "-z", "--stdin"], repo.worktree, stdin=("\0".join(chunk) + "\0").encode("utf-8"))
            if result.code not in (0, 1):
                raise GitError("list_files", result.err.strip() or "git check-ignore failed", repo.worktree)
            out.update(_nuls(result.text))
        return out

    def _sync_excludes(self, store: Repository, source: Optional[Repository]) -> None:
        """The snapshot store is a different git directory, so the source's private ignore file is copied across."""
        if source is None:
            return
        try:
            target = Path(store.git_directory, "info", "exclude")
            target.parent.mkdir(parents=True, exist_ok=True)
            src = Path(source.common_directory, "info", "exclude")
            if src.exists():
                shutil.copyfile(src, target)
        except OSError:
            pass

    def tree_capture(self, store: Repository, scopes: list[str], ignores: Optional[Repository] = None, maximum_untracked_file_bytes: Optional[int] = None) -> str:
        """Records the scoped files as a tree and returns its id."""
        self._sync_excludes(store, ignores)
        scoped = [literal_pathspec(s) for s in scopes] or ["."]
        oversized: list[str] = []
        if maximum_untracked_file_bytes:
            untracked = _nuls(self._repo_op("refresh", store, ["ls-files", "--others", "--exclude-standard", "-z", "--", *scoped]).text)
            for item in untracked:
                try:
                    if os.path.isfile(os.path.join(store.worktree, item)) and os.path.getsize(os.path.join(store.worktree, item)) > maximum_untracked_file_bytes:
                        oversized.append(item)
                except OSError:
                    continue
        self._add(store, scoped)
        if oversized:
            self._repo_op("refresh", store, ["update-index", "--force-remove", "-z", "--stdin"], stdin=("\0".join(oversized) + "\0").encode("utf-8"))
        return self.tree_write(store)

    def _add(self, store: Repository, scoped: list[str]) -> None:
        last: Optional[GitError] = None
        for attempt in range(3 if sys.platform == "win32" else 1):
            try:
                self._repo_op("refresh", store, ["add", "-A", "--", *scoped])
                return
            except GitError as exc:  # Windows: git exits non-zero instead of reusing a loose object another process is finalising
                last = exc
                time.sleep(0.05)
        assert last is not None
        raise last

    def tree_write(self, store: Repository) -> str:
        return self._repo_op("write_tree", store, ["write-tree"]).text.strip()

    def tree_files(self, store: Repository, frm: str, to: str) -> list[str]:
        return _nuls(self._repo_op("list_files", store, ["diff-tree", "-r", "--name-only", "--no-renames", "-z", frm, to]).text)

    def tree_diff(self, store: Repository, frm: str, to: str, context: Optional[int] = None, paths: Optional[list[str]] = None) -> list[FileDiff]:
        spec = ["--", *[literal_pathspec(p) for p in paths]] if paths else []
        status = self._repo_op("diff", store, ["diff-tree", "-r", "--name-status", "--no-renames", "-z", frm, to, *spec]).text.split("\0")
        entries = [(status[i], status[i + 1]) for i in range(0, len(status) - 1, 2) if status[i]]
        out: list[FileDiff] = []
        for code, file in entries:
            patch = self._repo_op("diff", store, ["diff", "--no-color", "--no-ext-diff", "--no-renames", f"-U{4 if context is None else context}", frm, to, "--", literal_pathspec(file)]).text
            body = [l for l in patch.splitlines() if not l.startswith(("diff --git", "index ", "--- ", "+++ ", "new file", "deleted file", "similarity", "rename "))]
            additions = sum(1 for l in body if l.startswith("+"))
            deletions = sum(1 for l in body if l.startswith("-"))
            out.append(FileDiff(file, patch, additions, deletions, {"A": "added", "D": "deleted"}.get(code[0], "modified")))
        return out

    def tree_restore(self, store: Repository, files: dict[str, str]) -> None:
        """Puts each path back as it was in its tree; a path absent from its tree is removed."""
        for file, tree in files.items():
            present = run(_git_args(store, ["cat-file", "-e", f"{tree}:{file}"]), store.worktree).code == 0
            target = os.path.join(store.worktree, file)
            if present:
                self._repo_op("restore", store, ["checkout", tree, "--", literal_pathspec(file)])
            else:
                try:
                    if os.path.isdir(target) and not os.path.islink(target):
                        shutil.rmtree(target)
                    elif os.path.lexists(target):
                        os.remove(target)
                except OSError as exc:
                    raise GitError("restore", f"Failed to remove {file}: {exc}", store.worktree) from exc

    # ------------------------------------------------------------------ housekeeping

    def pack(self, store: Repository) -> None:
        """Packs loose objects and combines small packs without dropping any object. Does nothing below the thresholds; a lock file keeps
        concurrent processes from repeating the work."""
        loose = self._repo_op("pack", store, ["count-objects", "-v"]).text
        stats = {k: int(v) for k, v in (l.split(": ", 1) for l in loose.splitlines() if ": " in l) if v.strip().isdigit()}
        if stats.get("count", 0) < LOOSE_OBJECT_LIMIT and stats.get("packs", 0) < PACK_COUNT_LIMIT:
            return
        lock = Path(store.git_directory, "harness-pack.lock")
        try:
            if lock.exists() and time.time() - lock.stat().st_mtime > PACK_LOCK_STALE_SECONDS:
                lock.unlink()
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            return
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            self._repo_op("pack", store, ["repack", "-d", "-q"])
        finally:
            try:
                lock.unlink()
            except OSError:
                pass


def _chunks(items: list[str]) -> Iterable[list[str]]:
    batch: list[str] = []
    size = 0
    for item in items:
        if batch and size + len(item) + 1 > ARGUMENT_BUDGET:
            yield batch
            batch, size = [], 0
        batch.append(item)
        size += len(item) + 1
    if batch:
        yield batch
