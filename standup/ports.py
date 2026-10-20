"""What the service needs from the outside world. Small, separate interfaces: a store knows nothing of transcripts, a clock nothing of streams."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from standup.events import MeetingEvent
from standup.state import MeetingState


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class IdGenerator(Protocol):
    def new_id(self, prefix: str = "") -> str: ...


@runtime_checkable
class MeetingEventStore(Protocol):
    """The append-only source of truth, one stream per meeting."""

    def append(self, workspace_id: str, event: MeetingEvent) -> None:
        """Adds the event after the last one. Adding the same event again is a no-op. Raises OutOfOrder for a gap, StoreError when it could not write."""
        ...

    def read(self, workspace_id: str, meeting_id: str, after: int = 0) -> list[MeetingEvent]:
        """The events with a sequence number above `after`, in order."""
        ...

    def meeting_ids(self, workspace_id: str) -> list[str]: ...


@runtime_checkable
class StreamPublisher(Protocol):
    """Tells whoever is watching that something happened (a live screen, a shared event stream). Called after the event is safely stored."""

    def publish(self, event: MeetingEvent) -> None: ...


@runtime_checkable
class MeetingWriter(Protocol):
    """A readable projection of the stream (the .txt transcript, the JSON summaries). It can always be rebuilt from the events."""

    def write(self, event: MeetingEvent, state: MeetingState) -> None: ...

    def rebuild(self, workspace_id: str, meeting_id: str, events: list[MeetingEvent]) -> None: ...
