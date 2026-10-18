"""The session inbox: input that has been accepted but not yet shown to the model (opencode: packages/core/src/session/inbox.ts).

A prompt sent while a session is busy cannot just be appended: the model is mid-step. Instead it waits here, with a *delivery* that says when it
may be consumed:

  steer   at the next step boundary of the run in progress (the user is correcting course; a background command or subagent has finished);
  queue   only once the session is idle (a follow-up to be answered after the current work).

Items are `user` prompts, `synthetic` notices from the system, and `compaction` (a manual /compact). Rows are pending-only: *promoting* an item
turns it into a real message (with the same id, so a retry is idempotent) and deletes the row. A compaction ahead of prompts goes first, so the
prompts stay verbatim after the checkpoint instead of being folded into its summary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional

from harness.db.database import Database
from harness.schema import message as M

DELIVERIES = ("steer", "queue")
TYPES = ("user", "synthetic", "compaction")


class LifecycleConflict(Exception):
    """The item is not in the state the request assumes (already delivered, cancelled, or the id belongs to something else)."""

    def __init__(self, id: str) -> None:
        super().__init__(f"Inbox item {id} cannot be changed that way")
        self.id = id


@dataclass
class InboxItem:
    id: str
    session_id: str
    type: str
    payload: dict[str, Any]
    delivery: str
    enqueued_seq: int
    time_created: int


def _item(row: Any) -> InboxItem:
    return InboxItem(row["id"], row["session_id"], row["type"], json.loads(row["payload"]), row["delivery"], row["enqueued_seq"], row["time_created"])


class SessionInbox:
    def __init__(self, db: Database, observer: Optional[Callable[[str, dict[str, Any]], None]] = None) -> None:
        self.db = db
        self.observer = observer or (lambda kind, data: None)

    # ------------------------------------------------------------------ admitting

    def _message_exists(self, id: str) -> Optional[Any]:
        return self.db.get("select session_id, type from session_message where id = ?", (id,))

    def get(self, id: str) -> Optional[InboxItem]:
        row = self.db.get("select * from session_inbox where id = ?", (id,))
        return _item(row) if row else None

    def admit(self, session_id: str, type: str, payload: dict[str, Any], delivery: str = "queue", id: Optional[str] = None) -> InboxItem:
        """Accepts an item. The first admission of an id wins: asking again with the same session and type returns what is already there
        (pending, or already promoted to a message); any other claim on the id is a conflict."""
        if type not in TYPES or delivery not in DELIVERIES:
            raise ValueError(f"unknown inbox item: {type}/{delivery}")
        id = id or M.new_message_id()
        existing = self.get(id)
        if existing is not None:
            if existing.session_id != session_id or existing.type != type:
                raise LifecycleConflict(id)
            return existing
        promoted = self._message_exists(id)
        if promoted is not None:
            if promoted["session_id"] != session_id or promoted["type"] != type or type == "compaction":
                raise LifecycleConflict(id)
            return InboxItem(id, session_id, type, payload, delivery, 0, M.now_ms())  # already delivered: nothing to enqueue
        with self.db.transaction():
            seq = (self.db.get("select coalesce(max(enqueued_seq), 0) + 1 as n from session_inbox")["n"])
            self.db.execute(
                "insert into session_inbox (id, session_id, type, payload, delivery, enqueued_seq, time_created) values (?,?,?,?,?,?,?)",
                (id, session_id, type, json.dumps(payload), delivery, seq, M.now_ms()),
            )
        self.observer("inbox.enqueued", {"sessionID": session_id, "id": id, "type": type, "delivery": delivery})
        return self.get(id)  # type: ignore[return-value]

    def admit_compaction(self, session_id: str, delivery: str = "steer", id: Optional[str] = None) -> InboxItem:
        """At most one compaction waits at a time: asking again returns the one already pending."""
        pending = next((i for i in self.list(session_id) if i.type == "compaction"), None)
        if pending is not None and id is None:
            return pending
        return self.admit(session_id, "compaction", {}, delivery, id)

    # ------------------------------------------------------------------ reading

    def list(self, session_id: str) -> list[InboxItem]:
        return [_item(r) for r in self.db.all("select * from session_inbox where session_id = ? order by enqueued_seq asc", (session_id,))]

    def has(self, session_id: str, scope: str = "input") -> bool:
        """`scope` is 'steer', 'queue', or 'input' (either)."""
        if scope == "input":
            return self.db.get("select 1 from session_inbox where session_id = ? limit 1", (session_id,)) is not None
        return self.db.get("select 1 from session_inbox where session_id = ? and delivery = ? limit 1", (session_id, scope)) is not None

    def _pending_steers(self, session_id: str) -> list[InboxItem]:
        rows = [i for i in self.list(session_id) if i.delivery == "steer"]
        control = next((n for n, r in enumerate(rows) if r.type == "compaction"), -1)
        if control > 0:  # compact before promoting even earlier steers, so their text stays verbatim after the checkpoint
            rows.insert(0, rows.pop(control))
        return rows

    def next_promotable(self, session_id: str, promotable: str = "input") -> Optional[InboxItem]:
        """The next item the runner may consume. Steers always; a queued item only for the 'input' scope (the idle boundary)."""
        steers = self._pending_steers(session_id)
        if steers:
            return steers[0]
        if promotable != "input":
            return None
        return next((i for i in self.list(session_id) if i.delivery == "queue"), None)

    # ------------------------------------------------------------------ changing

    def _require_pending(self, session_id: str, id: str) -> InboxItem:
        item = self.get(id)
        if item is None or item.session_id != session_id:
            raise LifecycleConflict(id)
        return item

    def cancel(self, session_id: str, id: str) -> None:
        self._require_pending(session_id, id)
        self.db.execute("delete from session_inbox where id = ? and session_id = ?", (id, session_id))
        self.observer("inbox.cancelled", {"sessionID": session_id, "id": id})

    def _set_delivery(self, session_id: str, id: str, to: str) -> None:
        item = self._require_pending(session_id, id)
        if item.delivery == to:
            raise LifecycleConflict(id)
        self.db.execute("update session_inbox set delivery = ? where id = ?", (to, id))
        self.observer("inbox.delivery", {"sessionID": session_id, "id": id, "delivery": to})

    def steer(self, session_id: str, id: str) -> None:
        """Changes a queued item to be taken at the next step boundary."""
        self._set_delivery(session_id, id, "steer")

    def queue(self, session_id: str, id: str) -> None:
        """Changes a steered item to wait until the session is idle."""
        self._set_delivery(session_id, id, "queue")

    def deliver(self, session_id: str, id: str) -> InboxItem:
        """Consumes one pending row (the runner does this for a compaction, whose result is its own message)."""
        item = self._require_pending(session_id, id)
        self.db.execute("delete from session_inbox where id = ?", (id,))
        self.observer("inbox.delivered", {"sessionID": session_id, "id": id, "type": item.type})
        return item

    # ------------------------------------------------------------------ promoting

    def _publish(self, store: Any, session_id: str, items: list[InboxItem]) -> int:
        for item in items:
            if item.type == "compaction":
                raise LifecycleConflict(item.id)
            message: M.Info = M.User(id=item.id, **item.payload) if item.type == "user" else M.Synthetic(id=item.id, **item.payload)
            with self.db.transaction():
                self.db.execute("delete from session_inbox where id = ?", (item.id,))
                if self._message_exists(item.id) is None:
                    store.add(session_id, message)
            self.observer("inbox.delivered", {"sessionID": session_id, "id": item.id, "type": item.type})
        return len(items)

    def promote(self, store: Any, session_id: str, scope: str = "input") -> Optional[int]:
        """Turns pending input into visible messages and returns how many, or None when a compaction must be handled first.

        A compaction at the head of the steers owns the boundary. Only the 'input' scope may fall through to one queued item, and then picks up
        any steers that arrived meanwhile."""
        steers = self._pending_steers(session_id)
        if steers or scope == "steer":
            control = next((n for n, r in enumerate(steers) if r.type == "compaction"), -1)
            if control == 0:
                return None
            return self._publish(store, session_id, steers if control == -1 else steers[:control])
        queued = next((i for i in self.list(session_id) if i.delivery == "queue"), None)
        if queued is None:
            return 0
        if queued.type == "compaction":
            return None
        promoted = self._publish(store, session_id, [queued])
        arrived = self._pending_steers(session_id)
        control = next((n for n, r in enumerate(arrived) if r.type == "compaction"), -1)
        return promoted + self._publish(store, session_id, arrived if control == -1 else arrived[:control])
