"""Taking a session out of the database and putting it back (opencode: the `export` and `import` commands).

`export_session` writes a session, its messages and its subagent sessions as plain JSON that stands on its own; `import_session` reads that
back into any database. When an id is already in use (importing a session into the database it came from, or importing the same file twice)
the imported copy gets fresh ids and every reference to the old ones inside it is rewritten, so the copy is a separate conversation that
still points at its own subagent sessions. `to_markdown` renders a readable transcript instead."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from harness.db.database import jdump
from harness.schema import message as M
from harness.session.store import SessionInfo, SessionStore, new_session_id

VERSION = 1


class ImportError_(Exception):
    pass


def export_session(store: SessionStore, session_id: str, include_children: bool = True) -> dict[str, Any]:
    info = store.get(session_id)
    if info is None:
        raise KeyError(f"Session not found: {session_id}")

    def one(s: SessionInfo) -> dict[str, Any]:
        return {
            "id": s.id, "parent_id": s.parent_id, "directory": s.directory, "title": s.title, "agent": s.agent, "model": s.model, "permission": s.permission,
            "metadata": s.metadata, "cost": s.cost, "tokens": s.tokens.model_dump(), "time_created": s.time_created, "time_updated": s.time_updated,
            "messages": [M.dump(m) for _, m in store.messages(s.id)],
        }

    sessions = [one(info)]
    if include_children:
        queue = [info]
        while queue:
            for child in store.children(queue.pop(0).id):
                sessions.append(one(child))
                queue.append(child)
    return {"version": VERSION, "root": session_id, "sessions": sessions}


def import_session(store: SessionStore, data: dict[str, Any], directory: Optional[str] = None) -> SessionInfo:
    """Adds the exported sessions to the database and returns the root. `directory` re-homes them (the folder they were exported from may not exist here)."""
    if not isinstance(data, dict) or data.get("version") != VERSION or not data.get("sessions"):
        raise ImportError_("This is not a session export (or it is from an incompatible version).")
    sessions: list[dict[str, Any]] = data["sessions"]
    taken_sessions = {s["id"] for s in sessions if store.get(s["id"]) is not None}
    taken_messages = {m["id"] for s in sessions for m in s["messages"] if store.db.get("select 1 from session_message where id = ?", (m["id"],))}
    mapping: dict[str, str] = {sid: new_session_id() for sid in taken_sessions}
    for mid in taken_messages:
        mapping[mid] = "msg_" + M.ascending()

    def rewrite(value: Any) -> Any:
        if not mapping:
            return value
        text = json.dumps(value)
        text = re.sub(r"\b(?:ses|msg)_[0-9A-Za-z]+", lambda m: mapping.get(m.group(0), m.group(0)), text)
        return json.loads(text)

    root_id = mapping.get(data["root"], data["root"])
    with store.db.transaction():
        for s in sessions:  # parents come before their children in an export
            sid = mapping.get(s["id"], s["id"])
            parent = mapping.get(s["parent_id"], s["parent_id"]) if s["parent_id"] else None
            store.db.execute(
                "insert into session (id, parent_id, directory, title, agent, model, permission, metadata, cost, tokens_input, tokens_output, tokens_reasoning, "
                "tokens_cache_read, tokens_cache_write, time_created, time_updated) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, parent, directory or s["directory"], s["title"], s["agent"], jdump(s["model"]) if s["model"] else None,
                 jdump(s["permission"]) if s["permission"] else None, jdump(rewrite(s["metadata"] or {})), s["cost"], s["tokens"]["input"], s["tokens"]["output"],
                 s["tokens"]["reasoning"], s["tokens"]["cache_read"], s["tokens"]["cache_write"], s["time_created"], s["time_updated"]),
            )
            for raw in s["messages"]:
                raw = rewrite(raw)
                message = M.parse(raw)
                store.add(sid, message)
    imported = store.get(root_id)
    assert imported is not None
    return imported


def dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def loads(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ImportError_(f"This is not valid JSON: {exc}") from None


def to_markdown(store: SessionStore, session_id: str) -> str:
    """A readable transcript: what you asked, what the agent said, and which tools it used."""
    info = store.get(session_id)
    if info is None:
        raise KeyError(f"Session not found: {session_id}")
    out = [f"# {info.title or 'Untitled session'}", "", f"Session `{info.id}` · agent `{info.agent or '-'}` · {info.directory}", ""]
    for _, m in store.messages(session_id):
        if isinstance(m, M.User):
            out += ["## You", "", m.text, ""]
        elif isinstance(m, M.Synthetic):
            out += ["## Notice", "", m.text, ""]
        elif isinstance(m, M.Assistant):
            out += [f"## Assistant (`{m.model.id}`)", ""]
            for part in m.content:
                if isinstance(part, M.AssistantText) and part.text:
                    out += [part.text, ""]
                elif isinstance(part, M.AssistantTool):
                    detail = json.dumps(getattr(part.state, "input", None), ensure_ascii=False)[:200] if getattr(part.state, "input", None) else ""
                    out.append(f"- tool `{part.name}` {detail} → {part.state.status}")
            out.append("")
    return "\n".join(out).rstrip() + "\n"
