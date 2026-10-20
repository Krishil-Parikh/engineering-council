"""One append-only events.jsonl per meeting. A line is written whole and flushed to disk before the event counts as stored; a torn last line (a crash mid-write) is cut off on the next open."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from standup.adapters.layout import meeting_dir
from standup.errors import OutOfOrder, StoreError
from standup.events import MeetingEvent, check_id

log = logging.getLogger("standup")


class JsonlEventStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()
        self._last: dict[tuple[str, str], tuple[int, str]] = {}

    def _path(self, workspace_id: str, meeting_id: str) -> Path:
        return meeting_dir(self.root, workspace_id, meeting_id) / "events.jsonl"

    def append(self, workspace_id: str, event: MeetingEvent) -> None:
        path = self._path(workspace_id, event.meeting_id)
        with self._lock:
            key = (workspace_id, event.meeting_id)
            seq, eid = self._last.get(key) or self._load_last(path)
            if event.sequence_number <= seq:
                if event.sequence_number == seq and event.event_id == eid:
                    return  # the same event again
                raise StoreError(f"sequence {event.sequence_number} is already used in {event.meeting_id}")
            if event.sequence_number != seq + 1:
                raise OutOfOrder(f"expected sequence {seq + 1}, got {event.sequence_number}", seq + 1)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "ab") as fh:
                    fh.write((json.dumps(event.wire(), ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
                    fh.flush()
                    os.fsync(fh.fileno())
            except OSError as exc:
                raise StoreError(f"could not write {path}: {exc}") from exc
            self._last[key] = (event.sequence_number, event.event_id)

    def read(self, workspace_id: str, meeting_id: str, after: int = 0) -> list[MeetingEvent]:
        path = self._path(workspace_id, meeting_id)
        with self._lock:
            return [e for e in self._read_all(path) if e.sequence_number > after]

    def meeting_ids(self, workspace_id: str) -> list[str]:
        check_id(workspace_id, "workspace_id")
        base = Path(self.root).resolve() / workspace_id
        if not base.is_dir():
            return []
        return sorted(p.name for p in base.iterdir() if (p / "events.jsonl").is_file())

    # ------------------------------------------------------------------ internals

    def _load_last(self, path: Path) -> tuple[int, str]:
        events = self._read_all(path)
        return (events[-1].sequence_number, events[-1].event_id) if events else (0, "")

    def _read_all(self, path: Path) -> list[MeetingEvent]:
        if not path.is_file():
            return []
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise StoreError(f"could not read {path}: {exc}") from exc
        events: list[MeetingEvent] = []
        lines = raw.split(b"\n")
        clean_end = raw.endswith(b"\n")
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            torn_tail = index == len(lines) - 1 and not clean_end
            try:
                events.append(MeetingEvent.model_validate(json.loads(line.decode("utf-8"))))
            except (ValueError, UnicodeDecodeError) as exc:
                if torn_tail:
                    log.warning("standup: cutting a half-written last line from %s", path)
                    self._truncate(path, len(raw) - len(line))
                    break
                raise StoreError(f"{path} line {index + 1} is damaged: {exc}") from exc
        return events

    @staticmethod
    def _truncate(path: Path, size: int) -> None:
        try:
            with open(path, "r+b") as fh:
                fh.truncate(size)
        except OSError:
            pass
