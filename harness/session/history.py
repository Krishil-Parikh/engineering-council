"""Reading a session's history (opencode: packages/core/src/session/history.ts).

History starts at the latest completed compaction: that message is always first, and everything before it is only on disk.
(Native provider checkpoints are an OpenAI-style feature that Gemini does not have, so only local summaries bound a read.)"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from harness.db.database import Database
from harness.instructions import index as I
from harness.schema import message as M
from harness.session import instruction_state as InstructionState
from harness.session.store import SessionStore


def latest_compaction_seq(db: Database, session_id: str) -> Optional[int]:
    row = db.get(
        "select seq from session_message where session_id = ? and type = 'compaction' "
        "and json_extract(data, '$.status') = 'completed' order by seq desc limit 1",
        (session_id,),
    )
    return int(row["seq"]) if row else None


def message_entries(store: SessionStore, session_id: str) -> list[tuple[int, M.Info]]:
    seq = latest_compaction_seq(store.db, session_id)
    rows = store.db.all(
        "select * from session_message where session_id = ? and seq >= ? order by seq", (session_id, seq if seq is not None else 0)
    )
    return [(r["seq"], SessionStore.decode_row(r)) for r in rows]


def load(store: SessionStore, session_id: str) -> list[M.Info]:
    return [m for _, m in message_entries(store, session_id)]


@dataclass
class RunnerEntries:
    initial: str
    entries: list[tuple[int, M.Info]]


def entries_for_runner(store: SessionStore, session_id: str, instructions: I.List) -> RunnerEntries:
    with store.db.transaction():
        entries = message_entries(store, session_id)
        return RunnerEntries(InstructionState.initial(store.db, session_id, instructions), entries)


def first_user_message(store: SessionStore, session_id: str) -> Optional[M.User]:
    row = store.db.get("select * from session_message where session_id = ? and type = 'user' order by seq limit 1", (session_id,))
    if not row:
        return None
    msg = SessionStore.decode_row(row)
    return msg if isinstance(msg, M.User) else None
