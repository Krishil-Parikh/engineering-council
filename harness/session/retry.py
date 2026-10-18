"""Retry policy for model calls (opencode: packages/core/src/session/runner/retry.ts).

Delays grow 2s, 4s, 8s, then stay at 10s, for up to 10 retries (about 84s in total), each jittered by +-20%. A provider's
`retry-after` raises the delay (capped at 15 minutes). Timeouts, which already waited minutes before failing, get only 3 retries."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Optional

from harness.ai.errors import AIError, is_retryable

RETRY_AFTER_MAX_MS = 15 * 60 * 1000
MAX_RETRIES = 10
MAX_TIMEOUT_RETRIES = 3
BASE_DELAY_MS = 2000
CAP_DELAY_MS = 10_000


@dataclass
class Decision:
    retry: bool
    attempt: int = 0
    delay_ms: int = 0


def _is_timeout(err: AIError) -> bool:
    return err.reason.tag == "Transport" and err.reason.code == "Timeout"


def _retry_after(err: AIError) -> Optional[float]:
    if err.reason.tag in ("RateLimit", "ProviderInternal") and err.reason.retry_after_ms is not None:
        return min(err.reason.retry_after_ms, RETRY_AFTER_MAX_MS)
    return None


class RetryPolicy:
    """One per session run. `decide` is called once per failed attempt; `hook` may veto or change the decision."""

    def __init__(self, rng: Callable[[], float] = random.random, hook: Optional[Callable[[dict], None]] = None) -> None:
        self._rng = rng
        self._hook = hook
        self._recurrence = 0
        self._attempt = 1
        self._timeouts = 0

    def decide(self, cause: AIError, *, retry: Optional[bool] = None) -> Decision:
        want = is_retryable(cause) if retry is None else retry
        if self._recurrence >= MAX_RETRIES:
            return Decision(False)
        base = min(BASE_DELAY_MS * (2 ** self._recurrence), CAP_DELAY_MS)
        jittered = base * (0.8 + 0.4 * self._rng())
        self._recurrence += 1
        floor = _retry_after(cause)
        delay = max(jittered, floor) if floor is not None else jittered
        self._attempt += 1
        if _is_timeout(cause):
            self._timeouts += 1
        decision = Decision(want and self._timeouts <= MAX_TIMEOUT_RETRIES, self._attempt, int(-(-delay // 1)))
        if self._hook:
            event = {"attempt": self._attempt, "decision": decision}
            self._hook(event)
            decision = event["decision"]
        return decision
