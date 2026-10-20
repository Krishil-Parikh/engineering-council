from __future__ import annotations


class StandupError(Exception):
    """Base of everything this package raises on purpose."""


class InvalidEvent(StandupError):
    """The event is malformed or breaks an invariant of the meeting (an answer to a question nobody asked, a decision never proposed...)."""


class InvalidTransition(InvalidEvent):
    """The meeting is in a state where this event may not happen (a statement while paused, anything after the meeting ended)."""


class OutOfOrder(StandupError):
    """An event arrived whose sequence number is not the next one. `expected` tells the caller what was awaited."""

    def __init__(self, message: str, expected: int) -> None:
        super().__init__(message)
        self.expected = expected


class UnknownMeeting(StandupError):
    pass


class StoreError(StandupError):
    """The event store could not read or write. Nothing was published when this is raised on a write."""
