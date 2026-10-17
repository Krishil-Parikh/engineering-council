"""A session is one conversation with an agent: an append-only message log plus a little metadata, saved under the harness
data directory so it can be resumed later. Compaction marks old messages as compacted instead of deleting them."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from coding_harness.memory import Instructions, SkillRegistry
from coding_harness.types import Message
from coding_harness.workspace import Workspace


def new_session_id() -> str:
    return f"ses_{int(time.time()):x}{os.urandom(3).hex()}"


class Session:
    def __init__(self, workspace: Workspace, agent: str, id: str | None = None, parent_id: str | None = None, title: str = "", cwd: Path | None = None) -> None:
        self.ws = workspace
        self.id = id or new_session_id()
        self.agent = agent
        self.parent_id = parent_id
        self.title = title
        self.cwd = cwd or workspace.cwd
        self.messages: list[Message] = []
        self.todos: list[dict[str, Any]] = []
        self.created = time.time()
        self.dir = workspace.sessions_dir / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.instructions = Instructions(workspace)
        self.skills = SkillRegistry(workspace)
        self.system_cache = ""  # the system prompt this session was started with
        self._n = 0
        self.save_meta()

    # ---- messages
    def next_message_id(self) -> str:
        self._n += 1
        return f"msg_{self._n:05d}"

    def add(self, message: Message) -> Message:
        self.messages.append(message)
        with open(self.dir / "messages.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(message.to_json(), ensure_ascii=False) + "\n")
        return message

    def active(self) -> list[Message]:
        return [m for m in self.messages if not m.compacted]

    def rewrite(self) -> None:
        """Rewrite the log after compaction flags changed (rare, atomic)."""
        tmp = self.dir / "messages.jsonl.tmp"
        tmp.write_text("".join(json.dumps(m.to_json(), ensure_ascii=False) + "\n" for m in self.messages), encoding="utf-8")
        os.replace(tmp, self.dir / "messages.jsonl")

    # ---- metadata
    def save_meta(self) -> None:
        meta = {"id": self.id, "agent": self.agent, "parent_id": self.parent_id, "title": self.title, "cwd": str(self.cwd),
                "created": self.created, "updated": time.time(), "todos": self.todos, "messages": len(self.messages)}
        tmp = self.dir / "session.json.tmp"
        tmp.write_text(json.dumps(meta, indent=1), encoding="utf-8")
        os.replace(tmp, self.dir / "session.json")

    @classmethod
    def load(cls, workspace: Workspace, session_id: str) -> "Session":
        d = workspace.sessions_dir / session_id
        meta = json.loads((d / "session.json").read_text(encoding="utf-8"))
        s = cls(workspace, meta["agent"], meta["id"], meta.get("parent_id"), meta.get("title", ""), Path(meta["cwd"]))
        s.created, s.todos = meta.get("created", s.created), meta.get("todos", [])
        log = d / "messages.jsonl"
        if log.exists():
            for line in log.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    s.messages.append(Message.from_json(json.loads(line)))
        s._n = len(s.messages)
        return s

    @classmethod
    def list(cls, workspace: Workspace) -> list[dict[str, Any]]:
        rows = []
        for d in workspace.sessions_dir.iterdir():
            f = d / "session.json"
            if f.exists():
                try:
                    rows.append(json.loads(f.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    pass
        return sorted(rows, key=lambda r: r.get("updated", 0), reverse=True)

    def last_text(self) -> str:
        for m in reversed(self.messages):
            if m.role == "assistant" and m.text.strip():
                return m.text
        return ""

    def depth(self, lookup: "dict[str, Session]") -> int:
        d, cur = 0, self
        while cur.parent_id and cur.parent_id in lookup:
            d += 1
            cur = lookup[cur.parent_id]
        return d
