"""Session and message persistence (opencode: session/store.ts, session/sql.ts and the message side of the projector).

Messages are stored as JSON with a monotonically increasing `seq`; history is read from the latest completed compaction."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from harness.db.database import Database, jdump, jload
from harness.schema import message as M
from harness.schema.permission import Rule


def new_session_id() -> str:
    return "ses_" + M.ascending()


@dataclass
class SessionInfo:
    id: str
    directory: str
    parent_id: Optional[str] = None
    title: Optional[str] = None
    agent: Optional[str] = None
    model: Optional[dict[str, Any]] = None
    permission: Optional[list[dict[str, str]]] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    revert: Optional[dict[str, Any]] = None  # set while part of the conversation is rewound (see harness/session/revert.py)
    cost: float = 0
    tokens: M.TokenUsage = field(default_factory=M.TokenUsage)
    time_created: int = 0
    time_updated: int = 0

    def permission_rules(self) -> list[Rule]:
        """Rules set on this session (they narrow the agent's rules)."""
        return _rules(self.permission)


def _rules(raw: Optional[list[dict[str, str]]]) -> list[Rule]:
    return [Rule(r["action"], r["resource"], r["effect"]) for r in (raw or [])]  # type: ignore[arg-type]


def _info(row: Any) -> SessionInfo:
    return SessionInfo(
        id=row["id"], directory=row["directory"], parent_id=row["parent_id"], title=row["title"], agent=row["agent"],
        model=jload(row["model"]), permission=jload(row["permission"]), metadata=jload(row["metadata"]) or {}, revert=jload(row["revert"]), cost=row["cost"],
        tokens=M.TokenUsage(
            input=row["tokens_input"], output=row["tokens_output"], reasoning=row["tokens_reasoning"],
            cache_read=row["tokens_cache_read"], cache_write=row["tokens_cache_write"],
        ),
        time_created=row["time_created"], time_updated=row["time_updated"],
    )


class SessionStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---- sessions
    def create(
        self, directory: str, *, agent: Optional[str] = None, model: Optional[dict[str, Any]] = None, parent_id: Optional[str] = None,
        title: Optional[str] = None, permission: Optional[list[dict[str, str]]] = None, metadata: Optional[dict[str, Any]] = None,
    ) -> SessionInfo:
        sid, now = new_session_id(), M.now_ms()
        self.db.execute(
            "insert into session (id, parent_id, directory, title, agent, model, permission, metadata, time_created, time_updated) "
            "values (?,?,?,?,?,?,?,?,?,?)",
            (sid, parent_id, directory, title, agent, jdump(model) if model else None, jdump(permission) if permission else None,
             jdump(metadata or {}), now, now),
        )
        return self.get(sid)  # type: ignore[return-value]

    def get(self, session_id: str) -> Optional[SessionInfo]:
        row = self.db.get("select * from session where id = ?", (session_id,))
        return _info(row) if row else None

    def list(self, directory: Optional[str] = None) -> list[SessionInfo]:
        rows = self.db.all("select * from session where (? is null or directory = ?) order by time_updated desc", (directory, directory))
        return [_info(r) for r in rows]

    def children(self, session_id: str) -> list[SessionInfo]:
        return [_info(r) for r in self.db.all("select * from session where parent_id = ? order by time_created", (session_id,))]

    def update(self, session_id: str, **fields: Any) -> None:
        cols = {"title", "directory", "agent", "model", "permission", "metadata", "revert"}
        sets, params = ["time_updated = ?"], [M.now_ms()]
        for k, v in fields.items():
            if k not in cols:
                raise KeyError(k)
            sets.append(f"{k} = ?")
            params.append(jdump(v) if k in ("model", "permission", "metadata", "revert") and v is not None else v)
        params.append(session_id)
        self.db.execute(f"update session set {', '.join(sets)} where id = ?", params)

    def touch(self, session_id: str) -> None:
        self.db.execute("update session set time_updated = ? where id = ?", (M.now_ms(), session_id))

    def add_usage(self, session_id: str, cost: float, tokens: M.TokenUsage) -> None:
        self.db.execute(
            "update session set cost = cost + ?, tokens_input = tokens_input + ?, tokens_output = tokens_output + ?, "
            "tokens_reasoning = tokens_reasoning + ?, tokens_cache_read = tokens_cache_read + ?, tokens_cache_write = tokens_cache_write + ?, "
            "time_updated = ? where id = ?",
            (cost, tokens.input, tokens.output, tokens.reasoning, tokens.cache_read, tokens.cache_write, M.now_ms(), session_id),
        )

    def remove(self, session_id: str) -> None:
        self.db.execute("delete from session where id = ?", (session_id,))

    # ---- messages
    def next_seq(self, session_id: str) -> int:
        row = self.db.get("select coalesce(max(seq), 0) + 1 as n from session_message where session_id = ?", (session_id,))
        return int(row["n"])

    def add(self, session_id: str, message: M.Info) -> tuple[M.Info, int]:
        """Append a message. Returns it with its assigned seq."""
        data = M.dump(message)
        msg_id, kind = data.pop("id"), data.pop("type")
        with self.db.transaction():
            seq = self.next_seq(session_id)
            now = M.now_ms()
            self.db.execute(
                "insert into session_message (id, session_id, type, seq, time_created, time_updated, data) values (?,?,?,?,?,?,?)",
                (msg_id, session_id, kind, seq, now, now, jdump(data)),
            )
        self.touch(session_id)
        return message, seq

    def save(self, session_id: str, message: M.Info) -> None:
        """Persist the new state of an existing message (the runner mutates assistant messages as a step progresses)."""
        data = M.dump(message)
        msg_id, _ = data.pop("id"), data.pop("type")
        self.db.execute(
            "update session_message set data = ?, time_updated = ? where id = ? and session_id = ?",
            (jdump(data), M.now_ms(), msg_id, session_id),
        )

    @staticmethod
    def decode_row(row: Any) -> M.Info:
        return M.parse({**jload(row["data"]), "id": row["id"], "type": row["type"]})

    def get_message(self, session_id: str, message_id: str) -> Optional[M.Info]:
        row = self.db.get("select * from session_message where session_id = ? and id = ?", (session_id, message_id))
        return self.decode_row(row) if row else None

    def messages(self, session_id: str) -> list[tuple[int, M.Info]]:
        rows = self.db.all("select * from session_message where session_id = ? order by seq", (session_id,))
        return [(r["seq"], self.decode_row(r)) for r in rows]

    def delete_from(self, session_id: str, seq: int) -> None:
        self.db.execute("delete from session_message where session_id = ? and seq >= ?", (session_id, seq))
