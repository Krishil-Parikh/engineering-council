"""Instruction files discovered while reading (opencode: packages/core/src/session/instructions.ts).

When the agent reads a file or directory, AGENTS.md files between it and the project root that were not part of the initial
instructions are loaded into the conversation as a durable synthetic message. The message's metadata is the ledger of which
paths were injected, so a path is injected once per session; if that message is later lost to compaction or revert, the path is
discovered and injected again. An in-flight claim stops two parallel reads from injecting the same file twice."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from harness.location import Location
from harness.schema import message as M
from harness.session.store import SessionStore
from harness.util import fs


def describe_path(root: str, path: str) -> str:
    """Relative to the project root when inside it, else absolute (never `../..` chains)."""
    import os

    return os.path.relpath(path, root).replace("\\", "/") if fs.contains(root, path) else path


class SessionInstructions:
    def __init__(self, store: SessionStore, location: Location) -> None:
        self.store = store
        self.root = str(fs.resolve(location.project_directory))
        self._in_flight: dict[str, set[str]] = {}

    def previously_injected(self, session_id: str) -> set[str]:
        from harness.session import history

        out: set[str] = set()
        for message in history.load(self.store, session_id):
            if isinstance(message, M.Synthetic):
                paths = ((message.metadata or {}).get("instruction") or {}).get("paths")
                if isinstance(paths, list):
                    out |= {p for p in paths if isinstance(p, str)}
        return out

    def load(self, session_id: str, paths: list[str]) -> Optional[M.Synthetic]:
        existing = self._in_flight.setdefault(session_id, set())
        claimed = [p for p in paths if p not in existing]
        if not claimed:
            return None
        existing.update(claimed)
        try:
            already = self.previously_injected(session_id)
            to_inject = [p for p in claimed if p not in already]
            files = [(p, fs.read_text_safe(p)) for p in to_inject]
            readable = [(p, c) for p, c in files if c is not None]
            if not readable:
                return None
            msg = M.Synthetic(
                text="\n\n".join(f"Instructions from: {p}\n{c}" for p, c in readable),
                description=f"Loaded {', '.join(describe_path(self.root, p) for p, _ in readable)}",
                metadata={"instruction": {"paths": [p for p, _ in readable]}},
            )
            self.store.add(session_id, msg)
            return msg
        finally:
            existing.difference_update(claimed)
            if not existing:
                self._in_flight.pop(session_id, None)
