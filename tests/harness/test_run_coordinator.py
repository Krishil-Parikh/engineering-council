"""The run coordinator, ported from opencode's session-run-coordinator tests."""

import asyncio

import pytest

from harness.session.run_coordinator import ExecutionInterrupted, RunCoordinator


def run(coro):
    return asyncio.run(coro)


async def settle(times=3):
    for _ in range(times):
        await asyncio.sleep(0)


def test_concurrent_resumes_for_one_key_share_one_execution():
    async def main():
        gate, runs = asyncio.Event(), []

        async def drain(key, force, scope):
            runs.append(1)
            await gate.wait()

        c = RunCoordinator(drain)
        first = asyncio.ensure_future(c.run("s"))
        await settle()
        second = asyncio.ensure_future(c.run("s"))
        await settle()
        assert len(runs) == 1
        gate.set()
        await asyncio.gather(first, second)
        assert len(runs) == 1

    run(main())


def test_joining_a_wake_started_execution_does_not_force_a_successor():
    async def main():
        started, gate, forces = asyncio.Event(), asyncio.Event(), []

        async def drain(key, force, scope):
            forces.append(force)
            started.set()
            await gate.wait()

        c = RunCoordinator(drain)
        c.wake("s")
        await started.wait()
        resumed = asyncio.ensure_future(c.run("s"))
        await settle()
        gate.set()
        await resumed
        assert forces == [False]

    run(main())


def test_a_wake_while_idle_starts_an_execution():
    async def main():
        drained = asyncio.Event()

        async def drain(key, force, scope):
            drained.set()

        RunCoordinator(drain).wake("s")
        await asyncio.wait_for(drained.wait(), 2)

    run(main())


def test_only_active_executions_are_reported():
    async def main():
        started = {"first": asyncio.Event(), "second": asyncio.Event()}
        gates = {"first": asyncio.Event(), "second": asyncio.Event()}

        async def drain(key, force, scope):
            started[key].set()
            await gates[key].wait()

        c = RunCoordinator(drain)
        assert c.active() == set() and not c.is_active("first")
        first = asyncio.ensure_future(c.run("first"))
        await started["first"].wait()
        assert c.active() == {"first"} and c.is_active("first") and not c.is_active("second")
        second = asyncio.ensure_future(c.run("second"))
        await started["second"].wait()
        assert c.active() == {"first", "second"}
        gates["first"].set()
        await first
        assert c.active() == {"second"} and not c.is_active("first")
        gates["second"].set()
        await second
        assert c.active() == set()

    run(main())


def test_failures_clean_up_and_reach_the_settled_hook():
    async def main():
        settled = []

        async def drain(key, force, scope):
            raise ValueError(f"{key} failed")

        async def hook(key, exit_, reason):
            settled.append((key, type(exit_).__name__))

        c = RunCoordinator(drain, settled=hook)
        with pytest.raises(ValueError, match="failure failed"):
            await c.run("failure")
        assert c.active() == set()
        with pytest.raises(ValueError, match="defect failed"):
            await c.run("defect")
        assert c.active() == set() and settled == [("failure", "ValueError"), ("defect", "ValueError")]

    run(main())


def test_a_failing_settled_hook_is_reported_and_ownership_released():
    async def main():
        async def drain(key, force, scope):
            return None

        async def hook(key, exit_, reason):
            raise RuntimeError("terminal publication failed")

        c = RunCoordinator(drain, settled=hook)
        with pytest.raises(RuntimeError, match="terminal publication failed"):
            await c.run("s")
        assert c.active() == set()

    run(main())


def test_wakes_during_an_execution_are_coalesced_into_one_more_drain():
    async def main():
        first_started, first_gate, second_started, runs = asyncio.Event(), asyncio.Event(), asyncio.Event(), []

        async def drain(key, force, scope):
            runs.append(1)
            if len(runs) == 1:
                first_started.set()
                await first_gate.wait()
            else:
                second_started.set()

        c = RunCoordinator(drain)
        resumed = asyncio.ensure_future(c.run("s"))
        await first_started.wait()
        c.wake("s")
        c.wake("s")
        c.wake("s")
        first_gate.set()
        await second_started.wait()
        await resumed
        assert len(runs) == 2

    run(main())


def test_a_wake_during_the_follow_up_runs_again():
    async def main():
        gates = [asyncio.Event(), asyncio.Event()]
        second_started, third_started, runs = asyncio.Event(), asyncio.Event(), []

        async def drain(key, force, scope):
            runs.append(1)
            if len(runs) == 1:
                await gates[0].wait()
            elif len(runs) == 2:
                second_started.set()
                await gates[1].wait()
            else:
                third_started.set()

        c = RunCoordinator(drain)
        resumed = asyncio.ensure_future(c.run("s"))
        await settle()
        c.wake("s")
        gates[0].set()
        await second_started.wait()
        c.wake("s")
        gates[1].set()
        await third_started.wait()
        await resumed
        assert len(runs) == 3

    run(main())


def test_interrupting_an_idle_key_does_nothing():
    async def main():
        reasons = []

        async def drain(key, force, scope):
            return None

        async def hook(key, exit_, reason):
            reasons.append(reason)

        c = RunCoordinator(drain, settled=hook)
        assert await c.interrupt("s", "user") is False
        await c.run("s")
        assert reasons == [None]

    run(main())


def test_a_late_interrupt_during_terminal_settlement_attaches_no_reason():
    async def main():
        settling, release, reasons = asyncio.Event(), asyncio.Event(), []

        async def drain(key, force, scope):
            return None

        async def hook(key, exit_, reason):
            settling.set()
            await release.wait()
            reasons.append(reason)

        c = RunCoordinator(drain, settled=hook)
        running = asyncio.ensure_future(c.run("s"))
        await settling.wait()
        assert await c.interrupt("s", "user") is False
        release.set()
        await running
        await c.run("s")
        assert reasons == [None, None]

    run(main())


def test_a_wake_in_the_settlement_window_starts_a_fresh_execution_with_its_own_scope():
    async def main():
        settling, release, scopes = asyncio.Event(), asyncio.Event(), []

        async def drain(key, force, scope):
            scopes.append(scope)

        async def hook(key, exit_, reason):
            settling.set()
            await release.wait()

        c = RunCoordinator(drain, settled=hook)
        c.wake("s", "steer")
        await settling.wait()
        c.wake("s", "input")
        release.set()
        await asyncio.wait_for(c.await_idle("s"), 2)
        assert scopes == ["steer", "input"]

    run(main())


def test_interrupting_stops_the_execution_clears_its_wake_and_interrupts_joiners():
    async def main():
        started, interrupted, runs, reasons = asyncio.Event(), asyncio.Event(), [], []

        async def drain(key, force, scope):
            runs.append(1)
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                interrupted.set()
                raise

        async def hook(key, exit_, reason):
            reasons.append(reason)

        c = RunCoordinator(drain, settled=hook)
        first = asyncio.ensure_future(c.run("s"))
        await started.wait()
        second = asyncio.ensure_future(c.run("s"))
        idle = asyncio.ensure_future(c.await_idle("s"))
        await settle()
        c.wake("s")
        assert await c.interrupt("s", "user") is True
        await interrupted.wait()
        results = await asyncio.gather(first, second, idle, return_exceptions=True)
        assert all(isinstance(r, ExecutionInterrupted) for r in results[:2]) and results[2] is None
        assert c.active() == set() and len(runs) == 1 and reasons == ["user"]

    run(main())


def test_a_wake_registered_during_interruption_cleanup_runs_afterwards():
    async def main():
        first_started, cleanup_started, cleanup_gate, second_started = (asyncio.Event() for _ in range(4))
        runs, starts = [], []

        async def drain(key, force, scope):
            runs.append(1)
            if len(runs) == 1:
                first_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cleanup_started.set()
                    await cleanup_gate.wait()
                    raise
            else:
                second_started.set()

        async def started(key):
            starts.append(1)

        c = RunCoordinator(drain, started=started)
        c.wake("s")
        await first_started.wait()
        interrupting = asyncio.ensure_future(c.interrupt("s"))
        await cleanup_started.wait()
        c.wake("s")  # a new admission, not part of the interrupted intent
        cleanup_gate.set()
        await interrupting
        await asyncio.wait_for(second_started.wait(), 2)
        assert len(runs) == 2 and len(starts) == 2

    run(main())


def test_coalesced_scopes_keep_the_widest_and_input_beats_steer():
    async def main():
        first_started, release, scopes = asyncio.Event(), asyncio.Event(), []

        async def drain(key, force, scope):
            scopes.append(scope)
            if len(scopes) == 1:
                first_started.set()
                await release.wait()

        c = RunCoordinator(drain)
        c.wake("s", "steer")
        await first_started.wait()
        c.wake("s", "steer")
        c.wake("s", "input")
        c.wake("s", "steer")  # does not narrow the recorded input scope
        release.set()
        await asyncio.wait_for(c.await_idle("s"), 2)
        assert scopes == ["steer", "input"]

    run(main())


def test_different_keys_run_concurrently():
    async def main():
        both, live = asyncio.Event(), set()

        async def drain(key, force, scope):
            live.add(key)
            if len(live) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 2)

        c = RunCoordinator(drain)
        await asyncio.gather(c.run("a"), c.run("b"))
        assert both.is_set()

    run(main())


def test_cancelling_a_joined_waiter_does_not_cancel_the_execution():
    async def main():
        gate, finished = asyncio.Event(), []

        async def drain(key, force, scope):
            await gate.wait()
            finished.append(1)

        c = RunCoordinator(drain)
        owner = asyncio.ensure_future(c.run("s"))
        await settle()
        joiner = asyncio.ensure_future(c.run("s"))
        await settle()
        joiner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await joiner
        gate.set()
        await owner
        assert finished == [1]

    run(main())


def test_settled_runs_once_per_execution_across_coalesced_drains():
    async def main():
        first_started, release, drains, settled = asyncio.Event(), asyncio.Event(), [], []

        async def drain(key, force, scope):
            drains.append(1)
            if len(drains) == 1:
                first_started.set()
                await release.wait()

        async def hook(key, exit_, reason):
            settled.append(exit_)

        c = RunCoordinator(drain, settled=hook)
        running = asyncio.ensure_future(c.run("s"))
        await first_started.wait()
        c.wake("s")
        c.wake("s")
        release.set()
        await running
        assert len(drains) == 2 and settled == [None]

    run(main())


def test_an_interrupt_is_acknowledged_before_slow_cleanup_finishes():
    async def main():
        started, cleanup_gate, settled = asyncio.Event(), asyncio.Event(), []

        async def drain(key, force, scope):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await cleanup_gate.wait()
                raise

        async def hook(key, exit_, reason):
            settled.append(reason)

        c = RunCoordinator(drain, settled=hook)
        asyncio.ensure_future(c.run("s")).add_done_callback(lambda f: f.exception())
        await started.wait()
        assert await asyncio.wait_for(c.interrupt("s", "user"), 1) is True  # returns while cleanup is still blocked
        assert c.is_active("s") and settled == []
        cleanup_gate.set()
        await asyncio.wait_for(c.await_idle("s"), 2)
        assert settled == ["user"]

    run(main())


def test_awaiting_settlement_waits_for_cleanup():
    async def main():
        started, cleanup_gate, settled = asyncio.Event(), asyncio.Event(), []

        async def drain(key, force, scope):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await cleanup_gate.wait()
                raise

        async def hook(key, exit_, reason):
            settled.append(reason)

        c = RunCoordinator(drain, settled=hook)
        asyncio.ensure_future(c.run("s")).add_done_callback(lambda f: f.exception())
        await started.wait()
        waiting = asyncio.ensure_future(c.interrupt("s", "user", await_settlement=True))
        await settle(5)
        assert not waiting.done()
        cleanup_gate.set()
        assert await asyncio.wait_for(waiting, 2) is True and settled == ["user"]

    run(main())


def test_close_interrupts_everything():
    async def main():
        started = asyncio.Event()

        async def drain(key, force, scope):
            started.set()
            await asyncio.Event().wait()

        c = RunCoordinator(drain)
        c.wake("s")
        await started.wait()
        await asyncio.wait_for(c.close(), 2)
        assert c.active() == set()

    run(main())
