"""File snapshots of the working directory (opencode: packages/core/src/snapshot.ts).

`capture` records the Location's files as a content-addressed tree in a private store (kept under the harness data directory, sharing the
project's git objects) and returns its id, or None when snapshots are disabled, unsupported or the capture fails: snapshots are best
effort and never fail a step. Trees can be listed (`files`), diffed (`diff`) and restored (`restore`), always with project-relative
paths; paths the source repository ignores are left out of results."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

from harness.git import Git, GitError, Repository
from harness.location import Location
from harness.session.runner.step import Snapshots as SnapshotsProtocol
from harness.tool.file_diff import FileDiff
from harness.util import fs
from harness.util.global_paths import GlobalPaths

log = logging.getLogger("harness.snapshot")
MAXIMUM_UNTRACKED_FILE_BYTES = 2 * 1024 * 1024
PACK_INTERVAL_SECONDS = 10 * 60


class SnapshotError(Exception):
    def __init__(self, operation: str, message: str) -> None:
        super().__init__(message)
        self.operation, self.message = operation, message


def _hash(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


class Snapshots(SnapshotsProtocol):
    def __init__(self, location: Location, paths: GlobalPaths, git: Optional[Git] = None, enabled: bool = True) -> None:
        self.location, self.paths, self.git, self.enabled = location, paths, git or Git(), enabled
        self._repo: Optional[tuple[Repository, str, Repository]] = None
        self._last_pack = float("-inf")

    def _enabled(self) -> bool:
        return self.enabled and self.location.vcs == "git"

    def _repository(self) -> tuple[Repository, str, Repository]:
        """(source repository, its real worktree path, snapshot store)."""
        if self._repo is not None:
            return self._repo
        source = self.git.discover(str(self.location.project_directory))
        if source is None:
            raise SnapshotError("capture", "Project is not a Git repository")
        worktree = str(Path(source.worktree).resolve())
        store_dir = str(self.paths.data / "snapshot" / self.location.project_id / _hash(worktree))
        try:
            store = (
                Repository(worktree, store_dir, store_dir) if (Path(store_dir) / "HEAD").exists()
                else self.git.create(worktree, store_dir, seed=source)
            )
        except GitError as exc:
            raise SnapshotError("capture", exc.message) from exc
        self._repo = (source, worktree, store)
        return self._repo

    def _scope(self, worktree: str) -> str:
        directory = str(Path(self.location.directory).resolve())
        if not fs.contains(worktree, directory):
            raise SnapshotError("capture", "Location is outside the project")
        return os.path.relpath(directory, worktree).replace("\\", "/")

    def capture(self) -> Optional[str]:
        if not self._enabled():
            return None
        try:
            source, worktree, store = self._repository()
            tree = self.git.tree_capture(store, [self._scope(worktree)], ignores=source, maximum_untracked_file_bytes=MAXIMUM_UNTRACKED_FILE_BYTES)
            if time.monotonic() - self._last_pack >= PACK_INTERVAL_SECONDS:
                self._last_pack = time.monotonic()
                try:
                    self.git.pack(store)
                except GitError as exc:
                    log.warning("failed to pack snapshot objects: %s", exc)
            return tree
        except (SnapshotError, GitError, OSError) as exc:
            log.warning("failed to capture snapshot: %s", exc)
            return None

    def _failure(self, operation: str, exc: Exception) -> SnapshotError:
        if isinstance(exc, SnapshotError) and exc.operation == operation:
            return exc
        return SnapshotError(operation, getattr(exc, "message", None) or str(exc))

    def files(self, frm: str, to: str) -> list[str]:
        """Project-relative paths changed between two trees, without loading contents."""
        try:
            source, _, store = self._repository()
            changed = self.git.tree_files(store, frm, to)
            skipped = self.git.ignored(source, changed)
            return [f for f in changed if f not in skipped]
        except (SnapshotError, GitError) as exc:
            raise self._failure("files", exc) from None

    def diff(self, frm: str, to: str, context: Optional[int] = None, paths: Optional[list[str]] = None) -> list[FileDiff]:
        if paths is not None and not paths:
            return []
        try:
            source, _, store = self._repository()
            diffs = self.git.tree_diff(store, frm, to, context, paths)
            skipped = self.git.ignored(source, [d.file for d in diffs])
            return [d for d in diffs if d.file not in skipped]
        except (SnapshotError, GitError) as exc:
            raise self._failure("diff", exc) from None

    def restore(self, files: dict[str, str]) -> None:
        """Puts each project-relative path back as it was in its tree; a path absent from its tree is removed. Others are untouched."""
        if not self._enabled():
            raise SnapshotError("restore", "Snapshots are disabled")
        try:
            _, worktree, store = self._repository()
            for file in files:
                if not fs.contains(worktree, os.path.abspath(os.path.join(worktree, file))):
                    raise SnapshotError("restore", f"Path escapes the project: {file}")
            self.git.tree_restore(store, files)
        except (SnapshotError, GitError) as exc:
            raise self._failure("restore", exc) from None
