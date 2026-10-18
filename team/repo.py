"""The team's git layout: one shared remote, one private clone per developer.

    <root>/origin.git        a bare repository every clone pushes to; its pre-receive hook refuses updates to main/master
    <root>/sandboxes/<dev>   a developer's clone: the only place that developer works

Only a human may update the protected branches (`TEAM_HUMAN=1` in the environment of the push, which `human_push` sets). Developers
push feature branches, the integrator pushes the integration branch, and the final integrated branch is left for the human to merge.

Every operation takes the developer's name and acts in that developer's sandbox, so two developers never share a working tree."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from harness.git import run as git_run

HOOK = """#!/bin/sh
# Only the human updates the protected branches.
[ "$TEAM_HUMAN" = "1" ] && exit 0
protected="{protected}"
while read old new ref; do
  for p in $protected; do
    if [ "$ref" = "refs/heads/$p" ]; then
      echo "remote: refs/heads/$p is protected: the human merges into it" >&2
      exit 1
    fi
  done
done
exit 0
"""
MARKER = re.compile(r"^(<<<<<<< |=======$|>>>>>>> )", re.M)


class RepoError(Exception):
    pass


@dataclass
class MergeResult:
    status: str  # merged | up-to-date | conflict
    files: list[str] = field(default_factory=list)  # conflicted paths
    head: Optional[str] = None


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48].strip("-") or "work"


class TeamRepo:
    def __init__(self, root: Path, main_branch: str = "main", protected: tuple[str, ...] = ()) -> None:
        self.root = Path(root).resolve()
        self.main = main_branch
        self.protected = tuple(dict.fromkeys((main_branch, "main", "master", *protected)))  # the repository's own trunk, and the two usual names
        self.origin = self.root / "origin.git"
        self.sandboxes = self.root / "sandboxes"
        self.seed_notes: list[str] = []  # what was special about the starting point (for the report)

    @staticmethod
    def detect_main(source: Optional[Path]) -> str:
        """The branch an existing repository is on (its trunk, whatever it is called); 'main' for a new project."""
        if source is not None and (Path(source) / ".git").exists():
            result = git_run(["symbolic-ref", "--quiet", "--short", "HEAD"], str(source))
            name = result.text.strip()
            if result.code == 0 and name:
                return name
        return "main"

    def _overlay_working_tree(self, source: Path, seed: Path) -> None:
        """The team should start from what the user sees, not only from what was last committed: copy over uncommitted edits and new
        (non-ignored) files, remove files deleted in the working tree, and commit that as the starting point."""
        listing = git_run(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], str(source)).text.split("\0")
        deleted = {f for f in git_run(["ls-files", "-z", "--deleted"], str(source)).text.split("\0") if f}
        for rel in (f for f in listing if f and f not in deleted):
            origin_file = Path(source) / rel
            if origin_file.is_file() and not origin_file.is_symlink():
                target = seed / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(origin_file, target)
        for rel in deleted:
            try:
                (seed / rel).unlink()
            except OSError:
                pass
        self._git(seed, "add", "-A")
        changed = [l for l in self._git(seed, "status", "--porcelain").text.splitlines() if l.strip()]
        if changed:
            self._commit(seed, "Working tree of the repository when the team started", "Council", "council@council.local")
            self.seed_notes.append(f"{len(changed)} uncommitted change(s) in the repository were included in the team's starting point")

    # ------------------------------------------------------------------ plumbing

    def _git(self, cwd: Path | str, *args: str, check: bool = True, env: Optional[dict[str, str]] = None, stdin: Optional[bytes] = None):
        result = git_run(list(args), str(cwd), env, stdin)
        if check and result.code != 0:
            raise RepoError(f"git {' '.join(args[:3])} failed in {cwd}: {result.err.strip() or result.text.strip()}")
        return result

    def sandbox_path(self, dev: str) -> Path:
        return self.sandboxes / slugify(dev)

    # ------------------------------------------------------------------ setup

    def init(self, source: Optional[Path] = None) -> None:
        """Creates the remote and seeds `main` from an existing repository (its current commit) or an empty first commit."""
        if (self.origin / "HEAD").exists():
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self._git(self.root, "init", "--bare", "-q", "-b", self.main, str(self.origin))
        hook = self.origin / "hooks" / "pre-receive"
        hook.parent.mkdir(exist_ok=True)
        hook.write_bytes(HOOK.format(protected=" ".join(self.protected)).encode("utf-8"))
        os.chmod(hook, 0o755)
        seed = self.root / "_seed"
        shutil.rmtree(seed, ignore_errors=True)
        try:
            if source is not None and (Path(source) / ".git").exists():
                self._git(self.root, "clone", "-q", "-c", "core.autocrlf=false", str(source), str(seed))
                head = self._git(seed, "rev-parse", "--abbrev-ref", "HEAD").text.strip()
                if head != self.main:
                    self._git(seed, "branch", "-M", self.main)
                self._overlay_working_tree(Path(source), seed)
            else:
                seed.mkdir()
                self._git(seed, "init", "-q", "-b", self.main)
                if source is not None and Path(source).is_dir() and any(Path(source).iterdir()):
                    shutil.copytree(source, seed, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
                else:
                    (seed / "README.md").write_bytes(b"# New project\n")
                self._git(seed, "add", "-A")
                self._commit(seed, "Initial commit", "Council", "council@council.local")
            self._git(seed, "push", "-q", str(self.origin), f"HEAD:refs/heads/{self.main}", env={"TEAM_HUMAN": "1"})
        finally:
            shutil.rmtree(seed, ignore_errors=True, onerror=_force_remove)

    def _commit(self, cwd: Path, message: str, name: str, email: str, allow_empty: bool = False) -> bool:
        args = ["-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-q", "-m", message, *(["--allow-empty"] if allow_empty else [])]
        return self._git(cwd, *args, check=False).code == 0

    def sandbox(self, dev: str) -> Path:
        """The developer's clone, created on first use."""
        path = self.sandbox_path(dev)
        if (path / ".git").exists():
            return path
        self.sandboxes.mkdir(parents=True, exist_ok=True)
        self._git(self.root, "clone", "-q", "-c", "core.autocrlf=false", str(self.origin), str(path))
        self._git(path, "config", "user.name", f"{dev} (Council)")
        self._git(path, "config", "user.email", f"{slugify(dev)}@council.local")
        self._git(path, "config", "core.autocrlf", "false")
        # a developer's own clone refuses to push the protected branches even before the remote does
        hook = path / ".git" / "hooks" / "pre-push"
        hook.write_bytes(HOOK.replace("pre-receive", "pre-push").replace("while read old new ref", "while read lref lsha ref rsha").format(protected=" ".join(self.protected)).encode("utf-8"))
        os.chmod(hook, 0o755)
        return path

    # ------------------------------------------------------------------ branches

    def fetch(self, dev: str) -> None:
        self._git(self.sandbox(dev), "fetch", "-q", "--prune", "origin")

    def branches(self, dev: str) -> list[str]:
        self.fetch(dev)
        out = self._git(self.sandbox(dev), "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin").text.split()
        return sorted(b[len("origin/"):] for b in out if b.startswith("origin/") and b != "origin/HEAD")

    def exists(self, dev: str, branch: str) -> bool:
        return branch in self.branches(dev)

    def checkout_branch(self, dev: str, name: str, base: Optional[str] = None) -> str:
        """Checks out `name` in the developer's sandbox. A new branch starts from origin/<base> (default: main); an existing remote
        branch is resumed. Returns the head commit."""
        path = self.sandbox(dev)
        self.fetch(dev)
        if self.exists(dev, name):
            self._git(path, "checkout", "-q", "-B", name, f"origin/{name}")
        else:
            self._git(path, "checkout", "-q", "-B", name, f"origin/{base or self.main}")
        return self.head(dev)

    def head(self, dev: str, ref: str = "HEAD") -> str:
        return self._git(self.sandbox(dev), "rev-parse", ref).text.strip()

    def current_branch(self, dev: str) -> str:
        return self._git(self.sandbox(dev), "rev-parse", "--abbrev-ref", "HEAD").text.strip()

    def commit_all(self, dev: str, message: str) -> bool:
        """Commits whatever changed. False when there was nothing to commit."""
        path = self.sandbox(dev)
        self._git(path, "add", "-A")
        if not self._git(path, "status", "--porcelain").text.strip():
            return False
        self._git(path, "commit", "-q", "-m", message)
        return True

    def push(self, dev: str, branch: Optional[str] = None, force: bool = False) -> None:
        path = self.sandbox(dev)
        branch = branch or self.current_branch(dev)
        result = self._git(path, "push", "-q", *(["--force-with-lease"] if force else []), "origin", f"{branch}:refs/heads/{branch}", check=False)
        if result.code != 0:
            raise RepoError(f"push of {branch} refused: {result.err.strip()}")

    def push_to(self, dev: str, url: str, branch: str) -> None:
        """Publishes one branch to a repository outside the team (the project's own remote). A protected branch is refused here as well as by
        the sandbox hook, so no code path can update main from the team's side."""
        if branch in self.protected:
            raise RepoError(f"{branch} is protected: only the human updates it")
        self.fetch(dev)
        # push the team remote's copy of the branch: it exists there even when this clone never checked it out
        result = self._git(self.sandbox(dev), "push", "-q", url, f"refs/remotes/origin/{branch}:refs/heads/{branch}", check=False)
        if result.code != 0:
            raise RepoError(f"push of {branch} to {url} failed: {result.err.strip() or result.text.strip()}")

    def human_push(self, dev: str, branch: str, target: str) -> None:
        """What the human does at the end: update a protected branch. Never called by an agent."""
        self._git(self.sandbox(dev), "push", "-q", "origin", f"{branch}:refs/heads/{target}", env={"TEAM_HUMAN": "1"})

    # ------------------------------------------------------------------ merging

    def merge(self, dev: str, source: str, message: str) -> MergeResult:
        """Merges origin/<source> into the branch checked out in the developer's sandbox."""
        path = self.sandbox(dev)
        self.fetch(dev)
        ref = f"origin/{source}"
        result = self._git(path, "merge", "--no-ff", "-m", message, ref, check=False)
        text = result.text + result.err
        if result.code == 0:
            return MergeResult("up-to-date" if "Already up to date" in text else "merged", [], self.head(dev))
        files = self.conflicted_files(dev)
        if files:
            return MergeResult("conflict", files)
        self._git(path, "merge", "--abort", check=False)
        raise RepoError(f"merge of {source} failed: {text.strip()}")

    def conflicted_files(self, dev: str) -> list[str]:
        out = self._git(self.sandbox(dev), "diff", "--name-only", "--diff-filter=U", check=False).text
        return sorted(l.strip() for l in out.splitlines() if l.strip())

    def conflict_text(self, dev: str, max_chars: int = 6000) -> dict[str, str]:
        """The conflicted files as they are on disk, markers included, for the people resolving them."""
        path = self.sandbox(dev)
        out = {}
        for f in self.conflicted_files(dev):
            try:
                out[f] = (path / f).read_text(encoding="utf-8", errors="replace")[:max_chars]
            except OSError:
                out[f] = "(unreadable)"
        return out

    def unresolved(self, dev: str) -> list[str]:
        """Conflicted files that still contain conflict markers."""
        path = self.sandbox(dev)
        bad = []
        for f in self.conflicted_files(dev):
            try:
                if MARKER.search((path / f).read_text(encoding="utf-8", errors="replace")):
                    bad.append(f)
            except OSError:
                bad.append(f)
        return bad

    def finish_merge(self, dev: str, message: str) -> str:
        path = self.sandbox(dev)
        bad = self.unresolved(dev)
        if bad:
            raise RepoError("conflict markers remain in: " + ", ".join(bad))
        self._git(path, "add", "-A")
        self._git(path, "commit", "-q", "-m", message)
        return self.head(dev)

    def abort_merge(self, dev: str) -> None:
        self._git(self.sandbox(dev), "merge", "--abort", check=False)

    def merging(self, dev: str) -> bool:
        return (self.sandbox(dev) / ".git" / "MERGE_HEAD").exists()

    # ------------------------------------------------------------------ recovery

    def state_report(self, dev: str, branch: Optional[str] = None) -> str:
        """What a person would look at first when git misbehaves: status, branches with their upstreams, recent history, the remote."""
        path = self.sandbox(dev)
        parts = []
        for title, args in (
            ("git status -sb", ["status", "-sb"]),
            ("git branch -vv", ["branch", "-vv"]),
            ("git log --oneline -8", ["log", "--oneline", "-8"]),
            ("git remote -v", ["remote", "-v"]),
        ):
            result = self._git(path, *args, check=False)
            parts.append(f"$ {title}\n{(result.text + result.err).strip()}")
        if branch:
            remote = self._git(path, "log", "--oneline", "-5", f"origin/{branch}", check=False)
            parts.append(f"$ git log --oneline -5 origin/{branch}\n{(remote.text + remote.err).strip()}")
        for marker_file, what in (("MERGE_HEAD", "a merge is in progress"), ("rebase-merge", "a rebase is in progress"), ("rebase-apply", "a rebase is in progress"), ("CHERRY_PICK_HEAD", "a cherry-pick is in progress")):
            if (path / ".git" / marker_file).exists():
                parts.append(what)
        return "\n\n".join(parts)

    def clear_stale_locks(self, dev: str, older_than: float = 5.0) -> list[str]:
        """Removes git lock files left behind by a process that died. Only locks older than a few seconds, so a running git is never disturbed."""
        import time

        removed = []
        git_dir = self.sandbox(dev) / ".git"
        for lock in git_dir.rglob("*.lock"):
            try:
                if time.time() - lock.stat().st_mtime >= older_than:
                    lock.unlink()
                    removed.append(str(lock.relative_to(git_dir)))
            except OSError:
                continue
        return removed

    def rebase_onto_remote(self, dev: str, branch: str) -> bool:
        """The usual answer to a rejected push: fetch, then replay local commits on top of the remote branch. False (and nothing changed) when
        that would conflict or the remote has no such branch."""
        path = self.sandbox(dev)
        self.fetch(dev)
        if not self.exists(dev, branch):
            return False
        result = self._git(path, "rebase", f"origin/{branch}", check=False)
        if result.code == 0:
            return True
        self._git(path, "rebase", "--abort", check=False)
        return False

    def abort_in_progress(self, dev: str) -> list[str]:
        """Abandons a half-finished merge, rebase or cherry-pick so the working tree is usable again."""
        path = self.sandbox(dev)
        done = []
        for name, args in (("merge", ["merge", "--abort"]), ("rebase", ["rebase", "--abort"]), ("cherry-pick", ["cherry-pick", "--abort"])):
            if self._git(path, *args, check=False).code == 0:
                done.append(name)
        return done

    # ------------------------------------------------------------------ inspection

    def changed_files(self, dev: str, base: str, head: str = "HEAD") -> list[str]:
        out = self._git(self.sandbox(dev), "diff", "--name-only", f"origin/{base}...{head}").text
        return [l.strip() for l in out.splitlines() if l.strip()]

    def files_between(self, dev: str, a: str, b: str = "HEAD") -> list[str]:
        out = self._git(self.sandbox(dev), "diff", "--name-only", a, b).text
        return [l.strip() for l in out.splitlines() if l.strip()]

    def log(self, dev: str, ref: str = "HEAD", limit: int = 20) -> list[str]:
        return self._git(self.sandbox(dev), "log", f"-{limit}", "--format=%h %s", ref).text.splitlines()

    def file_at(self, dev: str, ref: str, path: str) -> Optional[str]:
        result = self._git(self.sandbox(dev), "show", f"{ref}:{path}", check=False)
        return result.text if result.code == 0 else None


def _force_remove(func, path, exc_info) -> None:  # Windows: .git objects are read-only
    try:
        os.chmod(path, 0o700)
        func(path)
    except OSError:
        pass
