"""Reference repositories (opencode: reference.ts and repository-cache.ts).

A *reference* is another codebase the agent may read while working on this one: a library it integrates with, a sibling service, an example to
follow. References are named in configuration:

    {"references": {"fastapi": {"repository": "fastapi/fastapi", "branch": "master"},
                    "styleguide": {"path": "../styleguide"}}}

A `repository` (owner/name on GitHub, or any git URL) is cloned once, shallowly, into a cache under the harness data directory and refreshed
when it is older than a day; a `path` is used as it is. The agent gets the local directory and reads it with its ordinary tools, or hands the
question to the `scout` agent, which does nothing else."""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from harness.config import service as cfg
from harness.git import Git, GitError, run

TTL_SECONDS = 24 * 3600
MARKER = ".harness-fetched"


class ReferenceError_(Exception):
    pass


@dataclass
class Reference:
    name: str
    path: Optional[str] = None
    repository: Optional[str] = None
    branch: Optional[str] = None
    description: str = ""

    @property
    def source(self) -> str:
        return self.path or self.repository or ""


def remote_url(repository: str) -> str:
    """'owner/name' means GitHub; anything that already looks like a URL or a path is left alone."""
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) and not os.path.exists(repository):
        return f"https://github.com/{repository}.git"
    return repository


def parse_references(entries: list[cfg.Entry], base: Path) -> dict[str, Reference]:
    """The `references` of every configuration document; a later document overrides an earlier one of the same name."""
    found: dict[str, Reference] = {}
    for entry in entries:
        if not isinstance(entry, cfg.Document):
            continue
        raw = entry.info.get("references")
        if not isinstance(raw, dict):
            continue
        origin = entry.path.parent if entry.path else base
        for name, spec in raw.items():
            if not isinstance(spec, dict) or not re.fullmatch(r"[A-Za-z0-9_.-]+", str(name)):
                continue
            path = spec.get("path")
            if isinstance(path, str):
                path = str((origin / os.path.expanduser(path)).resolve())
            found[str(name)] = Reference(str(name), path if isinstance(path, str) else None, spec.get("repository") if isinstance(spec.get("repository"), str) else None,
                                         spec.get("branch") if isinstance(spec.get("branch"), str) else None, str(spec.get("description") or ""))
    return {n: r for n, r in found.items() if r.source}


class ReferenceCache:
    def __init__(self, root: Path, git: Optional[Git] = None, ttl: float = TTL_SECONDS, clock: Callable[[], float] = time.time) -> None:
        self.root, self.git, self.ttl, self.clock = Path(root), git or Git(), ttl, clock

    def directory_for(self, ref: Reference) -> Path:
        """The local directory holding the reference, cloning or refreshing it as needed."""
        if ref.path:
            path = Path(ref.path)
            if not path.is_dir():
                raise ReferenceError_(f"The reference {ref.name!r} points at {ref.path}, which is not a directory.")
            return path
        assert ref.repository
        url = remote_url(ref.repository)
        target = self.root / f"{re.sub(r'[^A-Za-z0-9_.-]+', '-', ref.name)}-{hashlib.sha1((url + (ref.branch or '')).encode()).hexdigest()[:8]}"
        self.root.mkdir(parents=True, exist_ok=True)
        if not (target / ".git").exists():
            try:
                self.git.clone(url, str(target), ref.branch, depth=1)
            except GitError as exc:
                raise ReferenceError_(f"Could not clone {ref.repository} for the reference {ref.name!r}: {exc.message}") from None
            self._stamp(target)
            return target
        if self.clock() - self._fetched(target) > self.ttl:
            self._refresh(target, ref)
        return target

    def _fetched(self, target: Path) -> float:
        try:
            return (target / MARKER).stat().st_mtime
        except OSError:
            return 0.0

    def _stamp(self, target: Path) -> None:
        (target / MARKER).write_text(str(self.clock()), encoding="utf-8")
        os.utime(target / MARKER, (self.clock(), self.clock()))

    def _refresh(self, target: Path, ref: Reference) -> None:
        """Best effort: an offline machine keeps using what it has."""
        branch = ref.branch
        if branch is None:
            head = run(["rev-parse", "--abbrev-ref", "HEAD"], str(target))
            branch = head.text.strip() if head.code == 0 else None
        if branch and run(["fetch", "--depth", "1", "origin", branch], str(target)).code == 0:
            run(["reset", "--hard", "FETCH_HEAD"], str(target))
        self._stamp(target)


class ReferenceService:
    def __init__(self, config: cfg.Config, cache: ReferenceCache, base: Path) -> None:
        self.config, self.cache, self.base = config, cache, base

    def all(self) -> dict[str, Reference]:
        return parse_references(self.config.entries(), self.base)

    def names(self) -> list[str]:
        return sorted(self.all())

    def resolve(self, name: str) -> Path:
        refs = self.all()
        if name not in refs:
            known = ", ".join(sorted(refs)) or "none are configured"
            raise ReferenceError_(f"There is no reference named {name!r} ({known}).")
        return self.cache.directory_for(refs[name])

    def describe(self) -> str:
        refs = self.all()
        if not refs:
            return "No references are configured."
        return "\n".join(f"- {r.name}: {r.description or r.source}" + (f" (branch {r.branch})" if r.branch else "") for r in sorted(refs.values(), key=lambda r: r.name))
