"""The configuration service (opencode: packages/core/src/config.ts).

`entries()` returns configuration from lowest to highest priority: documents (parsed harness.json files) and directory
entries (folders that may hold skills/, agents/, commands/). Later entries override earlier ones; for a given key the
`latest()` document that sets it wins."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from harness.config import discovery
from harness.config.discovery import Options, Sources
from harness.config.variable import parse_jsonc, substitute
from harness.location import Location
from harness.util import fs
from harness.util.global_paths import GlobalPaths

log = logging.getLogger("harness.config")


@dataclass
class Document:
    info: dict[str, Any]
    path: Optional[Path] = None
    type: str = "document"


@dataclass
class Directory:
    path: Path
    type: str = "directory"


Entry = Document | Directory


def latest(entries: list[Entry], key: str) -> Any:
    for entry in reversed(entries):
        if isinstance(entry, Document) and entry.info.get(key) is not None:
            return entry.info[key]
    return None


class Config:
    def __init__(self, location: Location, paths: GlobalPaths, options: Optional[Options] = None) -> None:
        self.location, self.paths, self.options = location, paths, options or Options()
        self._sources: Optional[Sources] = None
        self._entries: Optional[list[Entry]] = None

    # ---- loading
    def _parse(self, text: str, source: str) -> Optional[dict[str, Any]]:
        try:
            data = parse_jsonc(text)
        except ValueError:
            log.warning("configuration rejected: malformed JSON in %s", source)
            return None
        if not isinstance(data, dict):
            log.warning("configuration rejected: %s is not an object", source)
            return None
        return data

    def _load_file(self, path: Path) -> Optional[Document]:
        text = fs.read_text_safe(path)
        if text is None:
            return None
        info = self._parse(substitute(text, path=path), str(path))
        return Document(info, path) if info is not None else None

    def _load_directory(self, directory: Path) -> list[Entry]:
        docs = [d for d in (self._load_file(directory / n) for n in discovery.NAMES) if d is not None]
        return [*docs, Directory(directory)]

    def reload(self) -> list[Entry]:
        sources = discovery.discover(self.location, self.paths, self.options)
        direct = [d for d in (self._load_file(p) for p in sources.direct) if d is not None]
        explicit = [d] if sources.explicit and (d := self._load_file(sources.explicit)) else []
        content: list[Entry] = []
        if self.options.content is not None:
            info = self._parse(substitute(self.options.content, directory=self.location.directory), "inline config")
            if info is not None:
                content = [Document(info)]
        global_entries = self._load_directory(sources.global_) if sources.global_ else []
        project_entries = [e for root, present in sources.project if present for e in self._load_directory(root)]
        self._sources = sources
        self._entries = [*global_entries, *explicit, *direct, *project_entries, *content]
        return self._entries

    def entries(self) -> list[Entry]:
        return self._entries if self._entries is not None else self.reload()

    def compatibility(self) -> dict[str, list[Path]]:
        """Existing ~/.claude, ~/.agents and project .claude/.agents directories (their skills/ folders are read as skills)."""
        if self._sources is None:
            self.reload()
        assert self._sources is not None
        return {"claude": [p for p in self._sources.claude if p.is_dir()], "agents": [p for p in self._sources.agents if p.is_dir()]}
