"""The work gate: days, rests, freezes. Developers stop between steps, never inside one."""

import asyncio

import pytest

from team.agile.gate import WorkGate


def run(coro):
    return asyncio.run(coro)


async def worker(gate, dev, log, tasks=2, steps=3):
    """A developer: each task takes `steps` steps; a task ends the day."""
    await gate.register(dev)
    session = f"ses-{dev}"
    gate.watch(dev, session)
    for task in range(tasks):
        for step in range(steps):
            await gate.before_step(session)
            log.append((dev, task, step, "start"))
            await asyncio.sleep(0)  # a step takes a moment
            log.append((dev, task, step, "end"))
        await gate.finish_task(dev)
    await gate.unregister(dev)


def test_a_day_ends_when_every_developer_has_finished_a_task():
    async def main():
        gate, log = WorkGate(steps_per_day=50), []
        a = asyncio.ensure_future(worker(gate, "ann", log))
        b = asyncio.ensure_future(worker(gate, "bob", log))
        await asyncio.sleep(0)
        assert await gate.wait_day_over(2) == []
        report = gate.day_report()
        assert {d.reason for d in report.values()} == {"task-done"} and all(d.steps == 3 for d in report.values())
        assert {(d, t) for d, t, _, kind in log if kind == "end"} == {("ann", 0), ("bob", 0)}  # only the first task so far
        await gate.begin_day()
        assert await gate.wait_day_over(2) == []
        await gate.begin_day()
        await asyncio.gather(a, b)
        assert gate.workers == set()

    run(main())


def test_the_step_budget_ends_a_day_in_the_middle_of_a_task():
    async def main():
        gate, log = WorkGate(steps_per_day=2), []
        task = asyncio.ensure_future(worker(gate, "ann", log, tasks=1, steps=5))
        await asyncio.sleep(0)
        assert await gate.wait_day_over(2) == []
        assert gate.day_report()["ann"].reason == "step-budget" and [e for e in log if e[3] == "end"] == [("ann", 0, 0, "end"), ("ann", 0, 1, "end")]
        await gate.begin_day()
        assert await gate.wait_day_over(2) == []
        assert len([e for e in log if e[3] == "end"]) == 4  # two more steps on day two
        await gate.begin_day()
        assert await gate.wait_day_over(2) == [] and gate.day_report()["ann"].reason == "task-done"  # the fifth step ended the task
        await gate.begin_day()
        await task

    run(main())


def test_a_freeze_stops_work_between_steps_and_a_thaw_continues_the_same_day():
    async def main():
        gate, log = WorkGate(steps_per_day=100), []
        task = asyncio.ensure_future(worker(gate, "ann", log, tasks=1, steps=6))
        await asyncio.sleep(0)
        await gate.freeze("human")
        assert await gate.wait_quiet(2) == []
        frozen_at = len(log)
        assert log[-1][3] == "end"  # parked between steps, never inside one
        await asyncio.sleep(0.05)
        assert len(log) == frozen_at  # nothing moves while frozen
        await gate.thaw("human")
        assert await gate.wait_day_over(2) == []
        assert len([e for e in log if e[3] == "end"]) == 6  # the task carried on in the same day
        await gate.begin_day()
        await task

    run(main())


def test_a_day_is_not_over_while_frozen_and_the_freeze_has_holders():
    async def main():
        gate, log = WorkGate(), []
        task = asyncio.ensure_future(worker(gate, "ann", log, tasks=1, steps=1))
        await asyncio.sleep(0)
        await gate.freeze("ceremony")
        await gate.freeze("human")
        waiter = asyncio.ensure_future(gate.wait_day_over(5))
        await asyncio.sleep(0.05)
        assert not waiter.done()
        await gate.thaw("ceremony")
        assert gate.frozen and gate.holders == {"human"}
        await gate.thaw("human")
        assert await waiter == []
        await gate.begin_day()
        await task

    run(main())


def test_consultation_sessions_are_not_gated():
    async def main():
        gate = WorkGate()
        await gate.register("ann")
        gate.watch("ann", "work")
        await gate.freeze("ceremony")
        await asyncio.wait_for(gate.before_step("a-consultation-session"), 1)  # unknown session: passes at once
        held = asyncio.ensure_future(gate.before_step("work"))
        await asyncio.sleep(0.05)
        assert not held.done()
        await gate.thaw("ceremony")
        await asyncio.wait_for(held, 1)
        await gate.unregister("ann")

    run(main())


def test_a_late_developer_is_reported_and_never_deadlocks_the_team():
    async def main():
        gate = WorkGate()
        await gate.register("slow")  # registered, never reaches the gate (stuck inside a long step)
        late = await gate.hold("ceremony", timeout=0.05)
        assert late == ["slow"] and gate.frozen
        assert await gate.wait_day_over(0.05) == ["slow"]
        await gate.unregister("slow")

    run(main())


def test_with_nobody_working_the_day_is_over_at_once():
    async def main():
        gate = WorkGate()
        assert await gate.wait_day_over(1) == [] and await gate.hold("x", 1) == []

    run(main())


def test_the_gate_does_nothing_for_a_developer_who_is_not_registered():
    async def main():
        gate = WorkGate(steps_per_day=1)
        gate.watch("ghost", "s")
        for _ in range(5):
            await asyncio.wait_for(gate.before_step("s"), 1)

    run(main())
