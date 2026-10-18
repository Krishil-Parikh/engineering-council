"""Project instruction files as an instruction source (opencode: packages/core/src/instruction-discovery.ts and
config/plugin/instruction.ts).

Files found: the global AGENTS.md, then AGENTS.md (or CLAUDE.md) in the working directory and each parent up to the project root
(nearest first), then any files or URLs listed under `instructions` in a config document. A first read must succeed; later,
a source that cannot be read is simply kept as it was. When a file changes the model is shown a diff, or the new full text if
that is shorter."""

from __future__ import annotations

import difflib
import logging
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from harness.config import service as cfg
from harness.instructions import index as I
from harness.location import Location
from harness.util import fs
from harness.util.global_paths import GlobalPaths

log = logging.getLogger("harness.instructions")
KEY = "core/instructions"
FILE_NAMES = ("AGENTS.md", "CLAUDE.md")  # the first one found in a directory is used


@dataclass
class File:
    path: str  # an absolute file path, or the URL of a configured remote instruction
    content: str

    def to_json(self) -> dict[str, str]:
        return {"path": self.path, "content": self.content}


def render(files: list[dict[str, str]]) -> str:
    return "\n\n".join(f"Instructions from: {f['path']}\n{f['content']}" for f in files)


def _patch(path: str, before: str, after: str) -> str:
    lines = list(difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=3))
    body = [ln for ln in lines if not ln.startswith(("--- ", "+++ "))]
    return "\n".join(body).rstrip()


def render_update(previous: list[dict[str, str]], current: list[dict[str, str]]) -> str:
    changes = I.diff_by_key(previous, current, lambda f: f["path"], lambda b, a: b["content"] != a["content"])
    parts: list[str] = []
    parts += [f"The instructions from {f['path']} no longer apply." for f in changes["removed"]]
    parts += [f"New instructions apply from:\n{render([f])}" for f in changes["added"]]
    for c in changes["changed"]:
        before, after = c["previous"], c["current"]
        diff = "\n".join([f"The instructions from {after['path']} changed. Here's the diff:", "```diff", _patch(after["path"], before["content"], after["content"]), "```"])
        replacement = f"The instructions changed:\n{render([after])}"
        parts.append(diff if len(diff) < len(replacement) else replacement)
    return "\n\n".join(parts)


def source(value: Union[list[dict[str, str]], I.Unavailable, I.Removed]) -> I.List:
    return I.make(I.Definition(
        key=KEY, read=lambda: value, render_initial=render, render_changed=render_update,
        render_removed=lambda _: "Previously loaded instructions no longer apply.",
    ))


class InstructionDiscovery:
    """Finds the instruction files for a location. `load()` gives the instruction source; call it on every step, because
    the files may have changed since the model last saw them."""

    def __init__(self, location: Location, paths: GlobalPaths, config: cfg.Config, *, project: bool = True, global_: bool = True) -> None:
        self.location, self.paths, self.config = location, paths, config
        self.project, self.global_ = project, global_
        self._remote: dict[str, File] = {}
        self._remote_for: tuple[str, ...] = ()

    # ---- individual scopes
    def _first_in(self, directory: Path) -> Optional[Path]:
        for name in FILE_NAMES:
            p = directory / name
            if p.is_file():
                return p
        return None

    def _read(self, path: Path) -> Optional[File]:
        content = fs.read_text_safe(path)
        if content is None:
            log.debug("instruction file skipped: %s", path)
            return None
        return File(str(path), content)

    def _global_file(self) -> list[File]:
        if not self.global_:
            return []
        p = self._first_in(self.paths.config)
        f = self._read(p) if p else None
        return [f] if f else []

    def _project_files(self) -> Union[list[File], I._NonValue]:
        start, root, home = fs.resolve(self.location.directory), fs.resolve(self.location.project_directory), fs.resolve(self.paths.home)
        if not (self.project and fs.contains(root, start)):
            return []
        stop = home if fs.contains(home, start) else root
        global_file = fs.resolve(self.paths.config / "AGENTS.md")
        out: list[File] = []
        d = start
        while True:
            p = self._first_in(d)
            if p is not None and (self.global_ or fs.resolve(p) != global_file):
                f = self._read(p)
                if f is None:
                    return I.UNAVAILABLE  # a file that exists but cannot be read makes the whole set temporarily unavailable
                out.append(f)
            if fs.same_directory(d, stop) or d.parent == d:
                break
            d = d.parent
        return out

    def _match(self, pattern: str) -> list[str]:
        expanded = str(self.paths.home / pattern[2:]) if pattern.startswith("~/") else pattern
        if os.path.isabs(expanded):
            return fs.scan(os.path.basename(expanded), os.path.dirname(expanded), absolute=True, include="file", dot=True)
        if self.project:
            return fs.glob_up(expanded, self.location.directory, self.location.project_directory)
        if not self.global_:
            return []
        return fs.scan(expanded, self.paths.config, absolute=True, include="file", dot=True)

    def _fetch(self, url: str) -> Optional[File]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "agent-harness"})
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 - http(s) only, checked by the caller
                return File(url, resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001 - an unreachable URL must never block the session
            log.warning("failed to fetch instruction url %s: %s", url, exc)
            return self._remote.get(url)

    def _configured(self, entries: list[cfg.Entry]) -> list[File]:
        sources: list[str] = []
        for e in entries:
            if isinstance(e, cfg.Document):
                for s in e.info.get("instructions") or []:
                    if s not in sources:
                        sources.append(s)
        urls = tuple(s for s in sources if re.match(r"^https?://", s))
        if urls != self._remote_for:  # remote instructions are fetched when the set of URLs changes, not on every rescan
            self._remote = {u: f for u in urls if (f := self._fetch(u))}
            self._remote_for = urls
        files: list[File] = []
        watched: set[str] = set()
        for s in sources:
            if s in urls:
                if s in self._remote:
                    files.append(self._remote[s])
                continue
            for item in sorted(self._match(s)):
                resolved = str(fs.resolve(item))
                if resolved in watched:
                    continue
                watched.add(resolved)
                f = self._read(Path(resolved))
                if f:
                    files.append(f)
        return files

    # ---- the source
    def list(self) -> Union[list[File], I._NonValue]:
        project = self._project_files()
        if project is I.UNAVAILABLE:
            return I.UNAVAILABLE
        return [*self._global_file(), *project, *self._configured(self.config.entries())]  # type: ignore[list-item]

    def load(self) -> I.List:
        files = self.list()
        if not isinstance(files, list):
            return source(files)
        return source(I.REMOVED if not files else [f.to_json() for f in files])
