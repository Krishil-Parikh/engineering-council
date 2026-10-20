from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class UuidIds:
    def new_id(self, prefix: str = "") -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}" if prefix else uuid.uuid4().hex[:12]


class FixedClock:
    """A clock the test moves by hand."""

    def __init__(self, start: datetime | None = None) -> None:
        self.current = start or datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


class SequentialIds:
    def __init__(self) -> None:
        self.count = 0

    def new_id(self, prefix: str = "") -> str:
        self.count += 1
        return f"{prefix or 'id'}-{self.count:05d}"
