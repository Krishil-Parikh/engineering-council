"""The use cases: start a meeting, publish what happens in it, read it back, replay it, time it out.

One service serves one workspace, so a meeting of another workspace cannot be reached through it. Every event is checked against the meeting's rules BEFORE it is
stored, stored durably BEFORE anyone is told, and only then shown (writers, then publishers). A watcher that fails is logged and skipped: it can never lose or block an event."""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Iterable, Optional, Sequence

from standup.adapters.system import SystemClock, UuidIds
from standup.enums import TERMINAL_STATUSES, ControlMode, MeetingType
from standup.errors import InvalidEvent, OutOfOrder, StandupError, StoreError, UnknownMeeting
from standup.events import MeetingEvent, check_id, redact_payload, validate_for_publish
from standup.models import Meeting
from standup.ports import Clock, IdGenerator, MeetingEventStore, MeetingWriter, StreamPublisher
from standup.state import MeetingState

log = logging.getLogger("standup")


class MeetingService:
    def __init__(
        self, workspace_id: str, store: MeetingEventStore, *, clock: Optional[Clock] = None, ids: Optional[IdGenerator] = None,
        publishers: Sequence[StreamPublisher] = (), writers: Sequence[MeetingWriter] = (), cache: int = 64, retries: int = 3,
    ) -> None:
        self.workspace_id = check_id(workspace_id, "workspace_id")
        self.store, self.clock, self.ids = store, clock or SystemClock(), ids or UuidIds()
        self.publishers: list[StreamPublisher] = list(publishers)
        self.writers: list[MeetingWriter] = list(writers)
        self.retries = max(1, retries)
        self._states: "OrderedDict[str, MeetingState]" = OrderedDict()
        self._cache = max(4, cache)
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.Lock()

    # ------------------------------------------------------------------ wiring

    def add_publisher(self, publisher: StreamPublisher) -> None:
        self.publishers.append(publisher)

    def add_writer(self, writer: MeetingWriter) -> None:
        self.writers.append(writer)

    # ------------------------------------------------------------------ writing

    def create_meeting(
        self, title: str, meeting_type: "MeetingType | str" = MeetingType.CUSTOM, *, meeting_id: Optional[str] = None, control_mode: "ControlMode | str" = ControlMode.HUMAN,
        duration_limit_seconds: Optional[float] = None, sprint_id: Optional[str] = None, created_by: str = "system",
    ) -> str:
        meeting_id = check_id(meeting_id or self.ids.new_id("mtg"), "meeting_id")
        payload: dict[str, Any] = {"title": title, "meeting_type": str(meeting_type), "control_mode": str(control_mode), "created_by": created_by}
        if duration_limit_seconds:
            payload["duration_limit_seconds"] = duration_limit_seconds
        if sprint_id:
            payload["sprint_id"] = sprint_id
        self.publish(meeting_id, "meeting_created", payload, actor_id="system", idempotency_key=f"create:{meeting_id}")
        return meeting_id

    def publish(
        self, meeting_id: str, event_type: str, payload: Optional[dict[str, Any]] = None, *, actor_id: Optional[str] = None, target_id: Optional[str] = None,
        correlation_id: Optional[str] = None, causation_id: Optional[str] = None, idempotency_key: Optional[str] = None,
    ) -> MeetingEvent:
        """Records one thing that happened. Raises InvalidEvent / InvalidTransition when the meeting's rules forbid it; nothing is stored then.
        Sending the same `idempotency_key` again returns the event that was already recorded."""
        check_id(meeting_id, "meeting_id")
        payload = redact_payload(dict(payload or {}))
        validate_for_publish(event_type, payload)
        with self._lock(meeting_id):
            state = self._state(meeting_id, creating=event_type == "meeting_created")
            if idempotency_key and idempotency_key in state.idempotency:
                again = self._find(meeting_id, state, state.idempotency[idempotency_key])
                if again is not None:
                    return again
            now = self.clock.now()
            started = state.meeting is not None and state.meeting.started_at is not None
            elapsed = max(state.last_elapsed, state.elapsed_at(now)) if started else state.last_elapsed
            event = MeetingEvent(
                event_id=self.ids.new_id("evt"), event_type=event_type, meeting_id=meeting_id, workspace_id=self.workspace_id, sequence_number=state.last_sequence + 1,
                timestamp=now, elapsed_seconds=elapsed, actor_id=actor_id, target_id=target_id, payload=payload, correlation_id=correlation_id or self.ids.new_id("cor"),
                causation_id=causation_id, idempotency_key=idempotency_key,
            )
            state.validate(event)  # the rules, before anything is written
            self._append(event)  # durable before anyone is told
            state.apply(event)
            self._touch(meeting_id)
        self._fan_out(event, state)
        return event

    def _append(self, event: MeetingEvent) -> None:
        last: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                self.store.append(self.workspace_id, event)
                return
            except OutOfOrder:
                raise
            except StoreError as exc:
                last = exc
                log.warning("standup: could not store event %s of %s (attempt %d/%d): %s", event.sequence_number, event.meeting_id, attempt + 1, self.retries, exc)
                time.sleep(0.02 * (attempt + 1))
        raise StoreError(f"the event could not be stored after {self.retries} attempts: {last}")

    def _fan_out(self, event: MeetingEvent, state: MeetingState) -> None:
        for writer in list(self.writers):
            try:
                writer.write(event, state)
            except Exception:  # noqa: BLE001 - a projection can be rebuilt from the events; it must not stop the meeting
                log.exception("standup: a writer failed on event %s of %s (rebuild it with rebuild_projections)", event.sequence_number, event.meeting_id)
        for publisher in list(self.publishers):
            try:
                publisher.publish(event)
            except Exception:  # noqa: BLE001 - a watcher must never lose or block an event
                log.exception("standup: a publisher failed on event %s of %s", event.sequence_number, event.meeting_id)

    # ------------------------------------------------------------------ reading

    def state(self, meeting_id: str) -> MeetingState:
        """The live state of a meeting. Treat it as read-only: it changes only through `publish`."""
        check_id(meeting_id, "meeting_id")
        with self._lock(meeting_id):
            return self._state(meeting_id)

    def events(self, meeting_id: str, after: int = 0) -> list[MeetingEvent]:
        check_id(meeting_id, "meeting_id")
        if after < 0:
            raise InvalidEvent("after must not be negative")
        return self.store.read(self.workspace_id, meeting_id, after)

    def state_at(self, meeting_id: str, sequence: int) -> MeetingState:
        """The meeting as it was after event `sequence` (the replay scrubber)."""
        state = MeetingState()
        for event in self.events(meeting_id):
            if event.sequence_number > sequence:
                break
            state.apply(event)
        return state

    def replay(self, meeting_id: str) -> MeetingState:
        """Rebuilds the state from the stored events alone. Equal to the live state by construction."""
        state = MeetingState()
        try:
            state.apply_all(self.events(meeting_id))
        except StandupError as exc:
            raise StoreError(f"the stored stream of {meeting_id} is damaged: {exc}") from exc
        return state

    def meetings(self) -> list[Meeting]:
        found = []
        for mid in self.store.meeting_ids(self.workspace_id):
            try:
                st = self.state(mid)
            except StandupError as exc:
                log.warning("standup: skipping %s: %s", mid, exc)
                continue
            if st.meeting is not None:
                found.append(st.meeting.model_copy(deep=True))
        return sorted(found, key=lambda m: (m.started_at or m.ended_at or self.clock.now(), m.meeting_id))

    def rebuild_projections(self, meeting_id: str) -> None:
        events = self.events(meeting_id)
        for writer in list(self.writers):
            writer.rebuild(self.workspace_id, meeting_id, events)

    # ------------------------------------------------------------------ time

    def check_timeouts(self) -> list[str]:
        """Ends the meetings that ran past their time limit. Call it now and then (the gateway does, once a second)."""
        ended = []
        now = self.clock.now()
        for meeting in self.meetings():
            if meeting.status in TERMINAL_STATUSES or meeting.started_at is None or not meeting.duration_limit_seconds:
                continue
            state = self.state(meeting.meeting_id)
            if not state.paused and state.elapsed_at(now) >= meeting.duration_limit_seconds:
                try:
                    self.publish(meeting.meeting_id, "meeting_timed_out", {"limit_seconds": meeting.duration_limit_seconds}, actor_id="system", idempotency_key=f"timeout:{meeting.meeting_id}")
                    ended.append(meeting.meeting_id)
                except StandupError:
                    log.exception("standup: could not time out %s", meeting.meeting_id)
        return ended

    # ------------------------------------------------------------------ internals

    def _lock(self, meeting_id: str) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault(meeting_id, threading.RLock())

    def _state(self, meeting_id: str, creating: bool = False) -> MeetingState:
        cached = self._states.get(meeting_id)
        if cached is not None:
            self._states.move_to_end(meeting_id)
            return cached
        events = self.store.read(self.workspace_id, meeting_id)
        if not events and not creating:
            raise UnknownMeeting(f"no meeting {meeting_id!r} in workspace {self.workspace_id!r}")
        state = MeetingState()
        try:
            state.apply_all(events)
        except StandupError as exc:
            raise StoreError(f"the stored stream of {meeting_id} is damaged: {exc}") from exc
        self._states[meeting_id] = state
        self._touch(meeting_id)
        return state

    def _touch(self, meeting_id: str) -> None:
        while len(self._states) > self._cache:
            oldest = next(iter(self._states))
            if oldest == meeting_id:
                break
            self._states.popitem(last=False)  # evicted states are rebuilt from the store when next needed

    def _find(self, meeting_id: str, state: MeetingState, event_id: str) -> Optional[MeetingEvent]:
        for event in reversed(state.recent):
            if event.event_id == event_id:
                return event
        for event in self.store.read(self.workspace_id, meeting_id):
            if event.event_id == event_id:
                return event
        return None


def many(events: Iterable[MeetingEvent]) -> list[dict[str, Any]]:
    return [e.wire() for e in events]
