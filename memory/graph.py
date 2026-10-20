"""The store behind the team's memory: a graph of memories in SQLite.

A memory is a node (a file, a module, a decision, a convention, a pitfall, a note, an insight) with text, tags, an importance, an owner and a validity window; links
between nodes are typed edges (`imports`, `touched`, `affects`, `done_by`, `supports`, `supersedes`, ...). A fact that is replaced by a newer one is not deleted: it
gets `valid_to` and `superseded_by`, so what was true then can still be read (the temporal model of Zep/Graphiti).

Each node can carry an embedding (a vector); retrieval over all of it lives in `memory.retrieval`. SQLite gives transactions and a single file per graph, so a run
that is stopped and resumed keeps everything, and several agents can write at once."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

MAX_TEXT = 1600
SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, text TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '[]', owner TEXT,
  importance REAL NOT NULL DEFAULT 5, mentions INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL, updated REAL NOT NULL,
  valid_from REAL NOT NULL, valid_to REAL, superseded_by TEXT);
CREATE TABLE IF NOT EXISTS edges(
  src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL, weight REAL NOT NULL DEFAULT 1, note TEXT NOT NULL DEFAULT '', owner TEXT,
  created REAL NOT NULL, valid_to REAL, PRIMARY KEY(src, rel, dst));
CREATE TABLE IF NOT EXISTS vectors(id TEXT PRIMARY KEY, model TEXT NOT NULL, vec BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS nodes_kind ON nodes(kind);
"""


def node_id(kind: str, name: str) -> str:
    return f"{kind}:{' '.join(name.split())}"


@dataclass
class Node:
    id: str
    kind: str
    name: str
    text: str = ""
    tags: list[str] = field(default_factory=list)
    owner: Optional[str] = None  # the agent that wrote it (None: the system noticed it)
    importance: float = 5.0  # 1 (trivia) .. 10 (the team must not forget this)
    mentions: int = 1
    created: float = 0.0
    updated: float = 0.0
    valid_from: float = 0.0
    valid_to: Optional[float] = None  # set when a newer fact replaces this one
    superseded_by: Optional[str] = None

    @property
    def active(self) -> bool:
        return self.valid_to is None

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "name": self.name, "text": self.text, "tags": self.tags, "owner": self.owner, "importance": self.importance,
                "mentions": self.mentions, "created": self.created, "updated": self.updated, "validFrom": self.valid_from, "validTo": self.valid_to,
                "supersededBy": self.superseded_by}


@dataclass
class Edge:
    src: str
    rel: str
    dst: str
    weight: float = 1.0
    note: str = ""
    owner: Optional[str] = None
    created: float = 0.0
    valid_to: Optional[float] = None

    def public(self) -> dict[str, Any]:
        return {"source": self.src, "relation": self.rel, "target": self.dst, "weight": self.weight, "note": self.note, "owner": self.owner, "validTo": self.valid_to}


def _row_node(r: sqlite3.Row) -> Node:
    return Node(r["id"], r["kind"], r["name"], r["text"], json.loads(r["tags"] or "[]"), r["owner"], r["importance"], r["mentions"], r["created"], r["updated"], r["valid_from"], r["valid_to"], r["superseded_by"])


def _row_edge(r: sqlite3.Row) -> Edge:
    return Edge(r["src"], r["rel"], r["dst"], r["weight"], r["note"], r["owner"], r["created"], r["valid_to"])


class MemoryGraph:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path) if self.path else ":memory:", check_same_thread=False, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            if self.path is not None:
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)
            self._db.commit()
        self.version = 0  # bumped by every write: indexes built from the graph know when they are stale

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------------ writing

    def node(self, kind: str, name: str, text: str = "", owner: Optional[str] = None, tags: Iterable[str] = (), importance: Optional[float] = None) -> Node:
        """Adds a memory, or adds to the one that is there: new text is appended (not repeated), it counts as mentioned once more, and its importance can only rise."""
        with self._lock:
            nid, now = node_id(kind, name), time.time()
            text = " ".join(text.split())[:MAX_TEXT]
            tags = [t for t in dict.fromkeys(str(t).strip().lower() for t in tags) if t]
            row = self._db.execute("SELECT * FROM nodes WHERE id=?", (nid,)).fetchone()
            if row is None:
                self._db.execute("INSERT INTO nodes(id,kind,name,text,tags,owner,importance,mentions,created,updated,valid_from) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                 (nid, kind, " ".join(name.split()), text, json.dumps(tags), owner, importance if importance is not None else 5.0, 1, now, now, now))
            else:
                current = _row_node(row)
                merged = (f"{current.text} | {text}" if current.text and text and text not in current.text else current.text or text)[-MAX_TEXT:]
                merged_tags = list(dict.fromkeys([*current.tags, *tags]))
                self._db.execute("UPDATE nodes SET text=?, tags=?, importance=?, mentions=mentions+1, updated=? WHERE id=?",
                                 (merged, json.dumps(merged_tags), max(current.importance, importance or 0), now, nid))
                if text and text not in current.text:  # new words: the old vector no longer describes it
                    self._db.execute("DELETE FROM vectors WHERE id=?", (nid,))
            self._db.commit()
            self.version += 1
            return self.get(nid)  # type: ignore[return-value]

    def link(self, src: tuple[str, str], rel: str, dst: tuple[str, str], note: str = "", owner: Optional[str] = None, weight: float = 1.0) -> Edge:
        """Links two things (each `(kind, name)`), creating either when it is not there yet."""
        with self._lock:
            a = self.get(node_id(*src)) or self.node(*src, owner=owner)
            b = self.get(node_id(*dst)) or self.node(*dst, owner=owner)
            row = self._db.execute("SELECT * FROM edges WHERE src=? AND rel=? AND dst=?", (a.id, rel, b.id)).fetchone()
            now = time.time()
            if row is None:
                self._db.execute("INSERT INTO edges(src,rel,dst,weight,note,owner,created) VALUES(?,?,?,?,?,?,?)", (a.id, rel, b.id, weight, note[:300], owner, now))
            else:
                old = _row_edge(row)
                merged = (f"{old.note} | {note}" if old.note and note and note not in old.note else old.note or note)[-300:]
                self._db.execute("UPDATE edges SET note=?, weight=weight+0.25 WHERE src=? AND rel=? AND dst=?", (merged, a.id, rel, b.id))
            self._db.commit()
            self.version += 1
            return _row_edge(self._db.execute("SELECT * FROM edges WHERE src=? AND rel=? AND dst=?", (a.id, rel, b.id)).fetchone())

    def supersede(self, old_id: str, new_id: str, reason: str = "") -> None:
        """A newer fact replaces an older one: the old one stays readable with the time it stopped being true."""
        with self._lock:
            now = time.time()
            self._db.execute("UPDATE nodes SET valid_to=?, superseded_by=? WHERE id=? AND valid_to IS NULL", (now, new_id, old_id))
            self._db.commit()
            self.version += 1
        self.link(tuple(new_id.split(":", 1)), "supersedes", tuple(old_id.split(":", 1)), reason)  # type: ignore[arg-type]

    def set_vector(self, nid: str, model: str, vector: list[float]) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO vectors(id, model, vec) VALUES(?,?,?)", (nid, model, array("f", vector).tobytes()))
            self._db.commit()

    # ------------------------------------------------------------------ reading

    def get(self, nid: str) -> Optional[Node]:
        with self._lock:
            row = self._db.execute("SELECT * FROM nodes WHERE id=?", (nid,)).fetchone()
        return _row_node(row) if row else None

    def nodes(self, active_only: bool = True, kinds: Optional[Iterable[str]] = None) -> list[Node]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM nodes" + (" WHERE valid_to IS NULL" if active_only else "")).fetchall()
        found = [_row_node(r) for r in rows]
        wanted = set(kinds) if kinds else None
        return [n for n in found if wanted is None or n.kind in wanted]

    def edges(self, active_only: bool = True) -> list[Edge]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM edges" + (" WHERE valid_to IS NULL" if active_only else "")).fetchall()
        return [_row_edge(r) for r in rows]

    def neighbors(self, nid: str) -> list[tuple[str, Node, bool, float]]:
        """(relation, other node, outgoing?, weight) for everything linked to a node (replaced facts are left out)."""
        with self._lock:
            rows = self._db.execute("SELECT e.*, n.* FROM edges e JOIN nodes n ON n.id = CASE WHEN e.src=? THEN e.dst ELSE e.src END WHERE (e.src=? OR e.dst=?) AND e.valid_to IS NULL",
                                    (nid, nid, nid)).fetchall()
        out = []
        for r in rows:
            node = Node(r["id"], r["kind"], r["name"], r["text"], json.loads(r["tags"] or "[]"), r["owner"], r["importance"], r["mentions"], r["created"], r["updated"], r["valid_from"], r["valid_to"], r["superseded_by"])
            if node.active:
                out.append((r["rel"], node, r["src"] == nid, r["weight"]))
        return out

    def vectors(self, model: Optional[str] = None) -> dict[str, list[float]]:
        with self._lock:
            rows = self._db.execute("SELECT id, vec FROM vectors" + (" WHERE model=?" if model else ""), (model,) if model else ()).fetchall()
        out = {}
        for r in rows:
            a = array("f")
            a.frombytes(r["vec"])
            out[r["id"]] = list(a)
        return out

    def missing_vectors(self, model: str) -> list[Node]:
        have = set(self.vectors(model))
        return [n for n in self.nodes() if n.id not in have]

    def history(self, name: str) -> list[Node]:
        """Every version of a fact: what was true, and when it stopped being true (oldest first)."""
        key = re.sub(r"\W+", " ", name.lower()).strip()
        found = [n for n in self.nodes(active_only=False) if key and key in re.sub(r"\W+", " ", n.name.lower())]
        return sorted(found, key=lambda n: n.valid_from)

    def stats(self) -> dict[str, int]:
        kinds: dict[str, int] = {}
        for n in self.nodes():
            kinds[n.kind] = kinds.get(n.kind, 0) + 1
        with self._lock:
            edge_count = self._db.execute("SELECT COUNT(*) FROM edges WHERE valid_to IS NULL").fetchone()[0]
            replaced = self._db.execute("SELECT COUNT(*) FROM nodes WHERE valid_to IS NOT NULL").fetchone()[0]
        return {"nodes": sum(kinds.values()), "edges": edge_count, "replaced": replaced, **{f"kind:{k}": v for k, v in sorted(kinds.items())}}

    def export(self, limit: int = 400) -> dict[str, Any]:
        """The graph as the browser draws it: the most connected and most important nodes, and the links among them."""
        nodes = self.nodes(active_only=True)
        degree: dict[str, int] = {}
        edges = self.edges()
        for e in edges:
            degree[e.src] = degree.get(e.src, 0) + 1
            degree[e.dst] = degree.get(e.dst, 0) + 1
        nodes.sort(key=lambda n: -(degree.get(n.id, 0) + n.importance * 0.3 + n.mentions * 0.2))
        chosen = nodes[:limit]
        ids = {n.id for n in chosen}
        return {
            "nodes": [{**n.public(), "degree": degree.get(n.id, 0)} for n in chosen],
            "edges": [e.public() for e in edges if e.src in ids and e.dst in ids],
            "stats": self.stats(),
        }
