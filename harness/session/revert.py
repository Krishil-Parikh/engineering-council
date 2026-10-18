"""Undoing part of a conversation (opencode: session/revert.ts).

`stage(session, message)` rewinds a session to just before one of the user's messages: the files that the agent changed from that point on
are put back as they were (using the snapshots each step recorded), and the session remembers what it did so it can be undone. Nothing is
deleted yet:

  stage    files go back; the session is marked as reverted at that message (the conversation after it is still stored)
  unstage  files come back as they were before the revert; the mark is cleared
  commit   the conversation from that message on is deleted for good; the mark is cleared

Sending new input to a staged session commits the revert first (the service does this), so the model never sees the rewound part.
Staging again further back first undoes the earlier revert, so the files are always rewound from the session's real current state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from harness.schema import message as M
from harness.session.store import SessionInfo, SessionStore


class RevertError(Exception):
    pass


@dataclass
class RevertState:
    message_id: str
    start: Optional[str] = None  # the tree from before the first reverted step (None when nothing in the reverted part touched files)
    snapshot: Optional[str] = None  # the tree as it was when the revert began, so the revert can be undone
    files: list[str] = field(default_factory=list)
    diff: list[dict[str, Any]] = field(default_factory=list)  # what was rewound: file, additions, deletions

    def to_json(self) -> dict[str, Any]:
        return {"message_id": self.message_id, "start": self.start, "snapshot": self.snapshot, "files": self.files, "diff": self.diff}

    @staticmethod
    def from_json(raw: Optional[dict[str, Any]]) -> Optional["RevertState"]:
        return RevertState(raw["message_id"], raw.get("start"), raw.get("snapshot"), list(raw.get("files") or []), list(raw.get("diff") or [])) if raw else None


def staged(info: Optional[SessionInfo]) -> Optional[RevertState]:
    return RevertState.from_json(info.revert) if info is not None else None


class SessionRevert:
    def __init__(self, store: SessionStore, snapshots: Any, is_running: Callable[[str], bool] = lambda session_id: False, on_event: Optional[Callable[[str, dict], None]] = None) -> None:
        self.store, self.snapshots, self.is_running = store, snapshots, is_running
        self.on_event = on_event or (lambda kind, data: None)

    def state(self, session_id: str) -> Optional[RevertState]:
        return staged(self.store.get(session_id))

    # ------------------------------------------------------------------ the three moves

    def stage(self, session_id: str, message_id: str) -> RevertState:
        info = self.store.get(session_id)
        if info is None:
            raise RevertError(f"Session not found: {session_id}")
        if self.is_running(session_id):
            raise RevertError("The session is busy; interrupt it before reverting.")
        if staged(info) is not None:
            self.unstage(session_id)  # start again from the real current state of the files
        rows = self.store.messages(session_id)
        index = next((i for i, (_, m) in enumerate(rows) if m.id == message_id), None)
        if index is None:
            raise RevertError(f"Message not found: {message_id}")
        if not isinstance(rows[index][1], M.User):
            raise RevertError("A session can only be reverted to a message you sent.")
        steps = [m for _, m in rows[index:] if isinstance(m, M.Assistant) and m.snapshot is not None and m.snapshot.start]
        files = sorted({f for m in steps for f in (m.snapshot.files or [])})  # type: ignore[union-attr]
        state = RevertState(message_id)
        if steps and files:
            state.start = steps[0].snapshot.start  # type: ignore[union-attr]
            state.snapshot = self.snapshots.capture()
            state.files = files
            if state.snapshot is None:
                raise RevertError("The files could not be recorded before the revert, so it was not done.")
            self.snapshots.restore({f: state.start for f in files})
            try:
                state.diff = [{"file": d.file, "additions": d.additions, "deletions": d.deletions} for d in self.snapshots.diff(state.start, state.snapshot)]
            except Exception:  # noqa: BLE001 - the summary is a nicety
                state.diff = []
        self.store.update(session_id, revert=state.to_json())
        self.on_event("session.reverted", {"sessionID": session_id, "messageID": message_id, "files": state.files})
        return state

    def unstage(self, session_id: str) -> Optional[RevertState]:
        """Undoes a staged revert: the files return to how they were before it. Returns the state that was undone."""
        state = self.state(session_id)
        if state is None:
            return None
        if self.is_running(session_id):
            raise RevertError("The session is busy; interrupt it before undoing the revert.")
        if state.snapshot and state.files:
            self.snapshots.restore({f: state.snapshot for f in state.files})
        self._clear(session_id)
        self.on_event("session.unreverted", {"sessionID": session_id, "messageID": state.message_id})
        return state

    def commit(self, session_id: str) -> Optional[RevertState]:
        """Makes the revert final: the conversation from the reverted message on is deleted. Returns the state that was committed."""
        state = self.state(session_id)
        if state is None:
            return None
        rows = self.store.messages(session_id)
        boundary = next((seq for seq, m in rows if m.id == state.message_id), None)
        if boundary is not None:
            self.store.delete_from(session_id, boundary)
        self._clear(session_id)
        self.on_event("session.revert.committed", {"sessionID": session_id, "messageID": state.message_id})
        return state

    def _clear(self, session_id: str) -> None:
        self.store.db.execute("update session set revert = null, time_updated = ? where id = ?", (M.now_ms(), session_id))

    # ------------------------------------------------------------------ what the user can pick

    def points(self, session_id: str) -> list[dict[str, Any]]:
        """The user messages a session can be rewound to, oldest first, with what rewinding there would undo."""
        out = []
        rows = self.store.messages(session_id)
        for i, (_, m) in enumerate(rows):
            if not isinstance(m, M.User):
                continue
            later = [x for _, x in rows[i:] if isinstance(x, M.Assistant) and x.snapshot is not None]
            out.append({"message_id": m.id, "text": m.text[:80], "files": sorted({f for x in later for f in (x.snapshot.files or [])})})  # type: ignore[union-attr]
        return out
