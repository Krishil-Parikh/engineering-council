from __future__ import annotations

import threading
from typing import Optional

from standup.errors import OutOfOrder, StoreError
from standup.events import MeetingEvent


class MemoryEventStore:
    """Events kept in memory: for tests and for a run that must leave nothing on disk. `fail_next(n)` makes the next n writes fail, to test recovery."""

    def __init__(self) -> None:
        self._events: dict[tuple[str, str], list[MeetingEvent]] = {}
        self._lock = threading.Lock()
        self._failures = 0

    def fail_next(self, count: int = 1) -> None:
        self._failures = count

    def append(self, workspace_id: str, event: MeetingEvent) -> None:
        with self._lock:
            if self._failures > 0:
                self._failures -= 1
                raise StoreError("injected write failure")
            stream = self._events.setdefault((workspace_id, event.meeting_id), [])
            last: Optional[MeetingEvent] = stream[-1] if stream else None
            if last is not None and event.sequence_number <= last.sequence_number:
                if any(e.event_id == event.event_id and e.sequence_number == event.sequence_number for e in stream[-8:]):
                    return
                raise StoreError(f"sequence {event.sequence_number} is already used")
            expected = (last.sequence_number if last else 0) + 1
            if event.sequence_number != expected:
                raise OutOfOrder(f"expected sequence {expected}, got {event.sequence_number}", expected)
            stream.append(event)

    def read(self, workspace_id: str, meeting_id: str, after: int = 0) -> list[MeetingEvent]:
        with self._lock:
            return [e for e in self._events.get((workspace_id, meeting_id), []) if e.sequence_number > after]

    def meeting_ids(self, workspace_id: str) -> list[str]:
        with self._lock:
            return sorted(mid for (ws, mid) in self._events if ws == workspace_id)
