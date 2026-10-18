"""Named worktrees of a project (opencode: packages/core/src/worktree.ts, worktree/*.ts).

A worktree is an extra checkout of the project that a session or an agent can work in without disturbing the main one. They are tracked
per project in the database so they can be listed, removed and rediscovered. A *strategy* does the actual work; "git" (git worktree
add/remove/list) is built in and is the default. Only worktrees a strategy created can be removed through this service."""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from harness.db.database import Database
from harness.git import Git, GitError, WorktreeError
from harness.location import Location
from harness.util.global_paths import GlobalPaths

ADJECTIVES = ["brave", "calm", "clever", "cosmic", "crisp", "curious", "eager", "gentle", "glowing", "happy", "hidden", "jolly", "kind", "lucky",
              "mighty", "misty", "neon", "nimble", "playful", "proud", "quick", "quiet", "shiny", "silent", "stellar", "sunny", "swift", "tidy", "witty"]
NOUNS = ["cabin", "cactus", "canyon", "circuit", "comet", "eagle", "engine", "falcon", "forest", "garden", "harbor", "island", "knight", "lagoon",
         "meadow", "moon", "mountain", "nebula", "orchid", "otter", "panda", "pixel", "planet", "river", "rocket", "sailor", "squid", "star", "tiger",
         "wizard", "wolf"]


def slug() -> str:
    return f"{random.choice(ADJECTIVES)}-{random.choice(NOUNS)}"


class WorktreeServiceError(Exception):
    pass


class DirectoryUnavailableError(WorktreeServiceError):
    def __init__(self, directory: str) -> None:
        super().__init__(f"Directory unavailable: {directory}")
        self.directory = directory


class SourceDirectoryNotFoundError(WorktreeServiceError):
    def __init__(self, directory: str) -> None:
        super().__init__(f"Source directory is not a known worktree of this project: {directory}")
        self.directory = directory


class DestinationExistsError(WorktreeServiceError):
    def __init__(self, directory: str) -> None:
        super().__init__(f"Destination already exists: {directory}")
        self.directory = directory


class InvalidDirectoryError(WorktreeServiceError):
    def __init__(self, directory: str) -> None:
        super().__init__(f"Not a worktree of this project: {directory}")
        self.directory = directory


class StrategyUnavailableError(WorktreeServiceError):
    def __init__(self, strategy: str) -> None:
        super().__init__(f"Worktree strategy unavailable: {strategy}")
        self.strategy = strategy


class OperationError(WorktreeServiceError):
    def __init__(self, message: str, force_required: bool = False) -> None:
        super().__init__(message)
        self.force_required = force_required


def canonical(directory: str) -> str:
    resolved = os.path.realpath(directory)
    if not os.path.isdir(resolved):
        raise DirectoryUnavailableError(directory)
    return resolved


class Strategy(Protocol):
    id: str

    def create(self, source_directory: str, directory: str, branch: Optional[str]) -> str: ...
    def remove(self, directory: str, force: bool) -> None: ...
    def list(self, directory: str) -> list[dict[str, str]]: ...


class GitStrategy:
    id = "git"

    def __init__(self, git: Git) -> None:
        self.git = git

    def create(self, source_directory: str, directory: str, branch: Optional[str] = None) -> str:
        repo = self.git.discover(source_directory)
        if repo is None:
            raise DirectoryUnavailableError(source_directory)
        self.git.worktree_create(repo, directory, branch)
        return canonical(directory)

    def remove(self, directory: str, force: bool) -> None:
        repo = self.git.discover(directory)
        if repo is None:
            raise DirectoryUnavailableError(directory)
        self.git.worktree_remove(repo, directory, force)

    def list(self, directory: str) -> list[dict[str, str]]:
        repo = self.git.discover(directory)
        if repo is None:
            raise DirectoryUnavailableError(directory)
        out = []
        for entry in self.git.worktree_list(repo):
            try:
                out.append({"directory": canonical(entry.directory), "type": "root" if entry.kind == "main" else "worktree"})
            except DirectoryUnavailableError:
                continue
        return out


@dataclass
class WorktreeInfo:
    directory: str
    strategy: Optional[str] = None


class WorktreeManager:
    def __init__(self, db: Database, location: Location, paths: GlobalPaths, git: Optional[Git] = None,
                 on_event: Optional[Callable[[str, dict[str, Any]], None]] = None) -> None:
        self.db, self.location, self.on_event = db, location, on_event or (lambda kind, data: None)
        self.project_id = location.project_id
        self.directory = str(paths.data / "worktree" / self.project_id[:6])
        git_strategy = GitStrategy(git or Git())
        self.strategies: dict[str, Strategy] = {git_strategy.id: git_strategy}
        self.selected = git_strategy.id
        root = canonical(str(location.project_directory))
        self._remember(root, None)

    def add_strategy(self, strategy: Strategy) -> None:
        self.strategies.pop(strategy.id, None)
        self.strategies[strategy.id] = strategy
        self.selected = strategy.id

    # ------------------------------------------------------------------ storage

    def _remember(self, directory: str, strategy: Optional[str], replace: bool = False) -> bool:
        """Records a worktree. Discovery may claim an unowned row but never replaces another strategy's ownership."""
        row = self.db.get("select strategy from worktree where project_id = ? and directory = ?", (self.project_id, directory))
        if row is None:
            self.db.execute("insert into worktree (project_id, directory, strategy, time_created) values (?,?,?,?)",
                            (self.project_id, directory, strategy, int(time.time() * 1000)))
            return True
        if replace or (strategy and row["strategy"] is None):
            self.db.execute("update worktree set strategy = ? where project_id = ? and directory = ?", (strategy, self.project_id, directory))
            return True
        return False

    def _forget(self, directory: str) -> bool:
        found = self.db.get("select 1 from worktree where project_id = ? and directory = ?", (self.project_id, directory)) is not None
        if found:
            self.db.execute("delete from worktree where project_id = ? and directory = ?", (self.project_id, directory))
        return found

    def _find(self, directory: str) -> Optional[WorktreeInfo]:
        row = self.db.get("select directory, strategy from worktree where project_id = ? and directory = ?", (self.project_id, directory))
        return WorktreeInfo(row["directory"], row["strategy"]) if row else None

    def list(self) -> list[WorktreeInfo]:
        rows = self.db.all("select directory, strategy from worktree where project_id = ? order by time_created desc, directory asc", (self.project_id,))
        return [WorktreeInfo(r["directory"], r["strategy"]) for r in rows]

    def _changed(self, changed: bool) -> None:
        if changed:
            self.on_event("updated", {"projectID": self.project_id})

    # ------------------------------------------------------------------ operations

    def _strategy(self, strategy_id: str) -> Strategy:
        found = self.strategies.get(strategy_id)
        if found is None:
            raise StrategyUnavailableError(strategy_id)
        return found

    def create(self, name: Optional[str] = None, directory: Optional[str] = None, from_directory: Optional[str] = None, branch: Optional[str] = None) -> dict[str, str]:
        strategy = self._strategy(self.selected)
        base = directory or self.directory
        source = canonical(from_directory or str(self.location.project_directory))
        if self._find(source) is None:
            raise SourceDirectoryNotFoundError(source)
        os.makedirs(base, exist_ok=True)
        stem = name or slug()
        suffix, target = 1, os.path.join(base, stem)
        while os.path.exists(target):
            suffix += 1
            if suffix > 10:
                raise DestinationExistsError(target)
            target = os.path.join(base, f"{stem}-{suffix}")
        try:
            created = strategy.create(source, target, branch)
        except (GitError, WorktreeServiceError) as exc:
            raise self._operation_error(strategy.id, "create", exc) from None
        result = canonical(created)
        self._changed(self._remember(result, strategy.id, replace=True))
        return {"directory": result}

    def remove(self, directory: str, force: bool = False) -> None:
        target = canonical(directory)
        stored = self._find(target)
        if stored is None or not stored.strategy:
            raise InvalidDirectoryError(target)
        strategy = self._strategy(stored.strategy)
        try:
            strategy.remove(target, force)
        except (GitError, WorktreeServiceError) as exc:
            raise self._operation_error(strategy.id, "remove", exc) from None
        self._changed(self._forget(target))

    def refresh(self) -> None:
        """Forgets worktrees whose directory is gone and records the ones strategies find under the known roots."""
        stored = self.list()
        exists = {w.directory: os.path.isdir(w.directory) for w in stored}
        roots = {canonical(str(self.location.project_directory)), *[w.directory for w in stored if exists[w.directory] and not w.strategy]}
        discovered: dict[str, Optional[str]] = {}
        for directory in roots:
            if not os.path.isdir(directory):
                continue
            for strategy in reversed(list(self.strategies.values())):
                try:
                    entries = strategy.list(directory)
                except (GitError, WorktreeServiceError):
                    continue
                for entry in entries:
                    try:
                        resolved = canonical(entry["directory"])
                    except DirectoryUnavailableError:
                        continue
                    if resolved not in discovered:
                        discovered[resolved] = strategy.id if entry["type"] == "worktree" else None
        updated = [d for d, s in discovered.items() if self._remember(d, s)]
        removed = [d for d, ok in exists.items() if not ok and self._forget(d)]
        self._changed(bool(updated or removed))

    @staticmethod
    def _operation_error(strategy: str, operation: str, exc: Exception) -> Exception:
        if isinstance(exc, (OperationError, DirectoryUnavailableError)):
            return exc
        if isinstance(exc, WorktreeError):
            return OperationError(exc.message, exc.force_required)
        return OperationError(f"Worktree strategy {strategy} failed to {operation}: {getattr(exc, 'message', None) or exc}")
