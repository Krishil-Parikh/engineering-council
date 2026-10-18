"""The shared model limit: a few requests at a time, everyone served."""

import asyncio
import time

from team.throttle import ThrottledLLM


class Slow:
    model = "slow-model"

    def __init__(self, delay=0.15):
        self.delay, self.live, self.peak, self.calls = delay, 0, 0, 0

    async def stream(self, request):
        self.calls += 1
        self.live += 1
        self.peak = max(self.peak, self.live)
        try:
            await asyncio.sleep(self.delay)
            yield f"reply to {request}"
        finally:
            self.live -= 1


async def collect(llm, request):
    return [e async for e in llm.stream(request)]


def test_no_more_than_the_limit_are_in_flight_and_everybody_is_served():
    async def main():
        inner = Slow()
        llm = ThrottledLLM(inner, max_concurrent=2)
        replies = await asyncio.gather(*(collect(llm, i) for i in range(6)))
        assert [r[0] for r in replies] == [f"reply to {i}" for i in range(6)]
        assert inner.peak == 2 and llm.peak == 2 and llm.started == 6

    asyncio.run(main())


def test_requests_are_spaced_when_an_interval_is_set():
    async def main():
        inner = Slow(delay=0)
        llm = ThrottledLLM(inner, max_concurrent=5, min_interval=0.1)
        started = time.monotonic()
        await asyncio.gather(*(collect(llm, i) for i in range(4)))
        assert time.monotonic() - started >= 0.28  # three gaps of 0.1s between four starts

    asyncio.run(main())


def test_a_failing_request_gives_its_slot_back_and_other_attributes_pass_through():
    class Boom(Slow):
        async def stream(self, request):
            raise RuntimeError("provider down")
            yield  # pragma: no cover

    async def main():
        llm = ThrottledLLM(Boom(), max_concurrent=1)
        for _ in range(3):  # a held slot would make the second call hang
            try:
                await asyncio.wait_for(collect(llm, 1), 2)
            except RuntimeError:
                pass
        assert llm.model == "slow-model" and llm._active == 0

    asyncio.run(main())
