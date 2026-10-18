"""SQLite storage (opencode keeps sessions in SQLite through drizzle: packages/core/src/session/sql.ts). One connection,
guarded by a lock so tool tasks and the runner can share it."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

SCHEMA = """
create table if not exists session (
  id text primary key,
  parent_id text,
  directory text not null,
  title text,
  agent text,
  model text,
  permission text,
  metadata text,
  revert text,
  cost real not null default 0,
  tokens_input integer not null default 0,
  tokens_output integer not null default 0,
  tokens_reasoning integer not null default 0,
  tokens_cache_read integer not null default 0,
  tokens_cache_write integer not null default 0,
  time_created integer not null,
  time_updated integer not null,
  time_idle integer
);
create index if not exists session_parent_idx on session(parent_id);

create table if not exists session_message (
  id text primary key,
  session_id text not null references session(id) on delete cascade,
  type text not null,
  seq integer not null,
  time_created integer not null,
  time_updated integer not null,
  data text not null
);
create unique index if not exists session_message_session_seq_idx on session_message(session_id, seq);
create index if not exists session_message_session_type_seq_idx on session_message(session_id, type, seq);

create table if not exists instruction_blob (hash text primary key, value text);
create table if not exists instruction_state (
  session_id text primary key references session(id) on delete cascade,
  epoch_start integer not null,
  through_seq integer not null,
  initial_values text not null,
  current_values text not null
);

create table if not exists permission_saved (
  project text not null,
  action text not null,
  resource text not null,
  effect text not null,
  primary key (project, action, resource)
);
"""


class Database:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma foreign_keys = on")
        if str(path) != ":memory:":
            self.conn.execute("pragma journal_mode = wal")
        self.lock = threading.RLock()
        self._depth = 0
        self.conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, params)

    def all(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def get(self, sql: str, params: tuple | list = ()) -> Optional[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Re-entrant: only the outermost call begins and commits; an error anywhere rolls the whole thing back."""
        with self.lock:
            outer = self._depth == 0
            self._depth += 1
            if outer:
                self.conn.execute("begin immediate")
            try:
                yield
            except BaseException:
                if outer:
                    self.conn.execute("rollback")
                raise
            else:
                if outer:
                    self.conn.execute("commit")
            finally:
                self._depth -= 1

    def close(self) -> None:
        with self.lock:
            self.conn.close()


def jdump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def jload(text: Optional[str]) -> Any:
    return None if text is None else json.loads(text)
