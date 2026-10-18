"""One model, many developers: a shared limit on how many requests are in flight at once.

Every developer's harness calls the same model with the same key. On a free tier, six developers streaming at the same time would mostly collect
429s and spend their time retrying. This wrapper lets a few requests through at a time and keeps the rest waiting their turn, which is faster
overall and does not waste the rate limit. It also counts what went through."""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Optional


class ThrottledLLM:
    def __init__(self, inner: Any, max_concurrent: int = 4, min_interval: float = 0.0) -> None:
        self.inner, self.max_concurrent, self.min_interval = inner, max(1, max_concurrent), min_interval
        self._slots = asyncio.Semaphore(self.max_concurrent)
        self._next_start = 0.0
        self._lock = asyncio.Lock()
        self.started = 0
        self.peak = 0
        self._active = 0

    async def stream(self, request: Any) -> AsyncIterator[Any]:
        async with self._slots:
            if self.min_interval:
                async with self._lock:  # requests may not start closer together than min_interval
                    wait = self._next_start - time.monotonic()
                    if wait > 0:
                        await asyncio.sleep(wait)
                    self._next_start = time.monotonic() + self.min_interval
            self.started += 1
            self._active += 1
            self.peak = max(self.peak, self._active)
            try:
                async for event in self.inner.stream(request):
                    yield event
            finally:
                self._active -= 1

    def __getattr__(self, name: str) -> Any:  # anything else (model name, client...) is the wrapped client's
        return getattr(self.inner, name)
