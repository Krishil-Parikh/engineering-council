"""The work plan (validation, fallback, owners) and the scheduler (parallel, dependency-ordered, one feature per developer)."""

import asyncio
import json

import pytest

from meetings import synthesis
from meetings.models import Step
from team.plan import Feature, Plan, PlanError, Task, fallback_plan
from team.scheduler import FeatureOutcome, Scheduler
from tests.meetings.fakes import draft_spec

SKILLS = {"ana": "BACKEND", "bob": "FRONTEND", "cy": "DATABASE"}


def feature(fid, deps=(), owner=None, tasks=1):
    return Feature(fid, fid.title(), [Task(f"{fid} task {i}") for i in range(tasks)], owner=owner, depends_on=list(deps))


# ------------------------------------------------------------------ plan

def test_valid_plan_layers_and_readiness():
    plan = Plan([feature("db"), feature("api", ["db"]), feature("ui"), feature("wire", ["api", "ui"])])
    plan.validate()
    assert plan.layers() == [["db", "ui"], ["api"], ["wire"]]
    assert [f.id for f in plan.ready(set(), set())] == ["db", "ui"]
    assert [f.id for f in plan.ready({"db"}, {"db", "ui"})] == ["api"]
    assert plan.get("wire").branch == "feature/wire"


@pytest.mark.parametrize("features,message", [
    ([], "no features"),
    ([feature("a"), feature("a")], "must be unique: a"),
    ([feature("a", ["ghost"])], "unknown feature 'ghost'"),
    ([feature("a", ["a"])], "depends on itself"),
    ([feature("a", ["b"]), feature("b", ["a"])], "dependency cycle: a -> b -> a"),
    ([feature("a", tasks=0)], "has no tasks"),
    ([feature("Bad Id")], "lowercase letters"),
])
def test_invalid_plans_say_what_is_wrong(features, message):
    with pytest.raises(PlanError, match=message):
        Plan(features).validate()


def test_owner_must_be_on_the_team():
    with pytest.raises(PlanError, match="owned by 'zed', who is not on the team"):
        Plan([feature("a", owner="zed")]).validate(["ana", "bob"])
    Plan([feature("a", owner="ana")]).validate(["ana", "bob"])


def test_plan_round_trips_through_json_and_rejects_garbage():
    plan = Plan([feature("db", owner="cy"), feature("api", ["db"], owner="ana", tasks=2)])
    again = Plan.from_json(plan.to_json())
    assert [(f.id, f.owner, f.depends_on, len(f.tasks)) for f in again.features] == [("db", "cy", [], 1), ("api", "ana", ["db"], 2)]
    loose = Plan.from_json(json.dumps({"features": [{"id": "Add Login!", "depends_on": ["DB Layer"], "tasks": ["just a title"]}]}))
    assert loose.features[0].id == "add-login" and loose.features[0].depends_on == ["db-layer"] and loose.features[0].tasks[0].title == "just a title"
    with pytest.raises(PlanError, match="not valid JSON"):
        Plan.from_json("not json")
    with pytest.raises(PlanError, match="not valid JSON"):
        Plan.from_json('{"nope": 1}')


def test_owners_follow_skills_and_balance_load():
    spec = synthesis.finalize_spec(draft_spec(), [])
    plan = Plan([
        Feature("schema", "SQL schema and migrations", [Task("schema", "tables and indexes")]),
        Feature("screens", "Terminal screens", [Task("screens", "render the UI view")]),
        Feature("api", "HTTP API", [Task("api", "endpoint handlers")]),
    ])
    plan.assign_owners(spec, SKILLS)
    assert [f.owner for f in plan.features] == ["cy", "bob", "ana"]
    kept = Plan([Feature("x", "SQL schema", [Task("t")], owner="bob")])
    kept.assign_owners(spec, SKILLS)
    assert kept.features[0].owner == "bob"


def test_fallback_plan_is_valid_and_keeps_independent_steps_apart():
    spec = synthesis.finalize_spec(draft_spec(), [])
    spec = spec.model_copy(update={"implementation_sequence": [
        Step(order=1, title="Storage layer", details="persist todos in the storage component"),
        Step(order=2, title="Terminal screens", details="render the list view in the ui"),
        Step(order=3, title="Integrate the CLI", details="wire storage and screens together end-to-end"),
    ]})
    plan = fallback_plan(spec)
    plan.validate()
    assert len(plan.features) == 3
    wire = plan.features[2]
    assert set(wire.depends_on) == {plan.features[0].id, plan.features[1].id}
    assert plan.features[0].depends_on == []


# ------------------------------------------------------------------ scheduler

def run(plan, runner, **kw):
    sched = Scheduler(plan, runner, **kw)
    asyncio.run(sched.run())
    return sched


def test_independent_features_run_at_the_same_time_and_dependents_wait():
    order = []
    running = set()
    peak = [0]

    async def runner(f):
        running.add(f.id)
        peak[0] = max(peak[0], len(running))
        order.append(("start", f.id))
        await asyncio.sleep(0.05)
        running.discard(f.id)
        order.append(("end", f.id))
        return FeatureOutcome(True)

    plan = Plan([feature("a", owner="ana"), feature("b", owner="bob"), feature("c", ["a", "b"], owner="cy")])
    s = run(plan, runner)
    assert peak[0] == 2 and s.done == {"a", "b", "c"}
    assert order.index(("start", "c")) > max(order.index(("end", "a")), order.index(("end", "b")))


def test_one_feature_at_a_time_per_developer():
    running = {"ana": 0}
    peak = [0]

    async def runner(f):
        running["ana"] += 1
        peak[0] = max(peak[0], running["ana"])
        await asyncio.sleep(0.03)
        running["ana"] -= 1
        return FeatureOutcome(True)

    s = run(Plan([feature("a", owner="ana"), feature("b", owner="ana"), feature("c", owner="ana")]), runner)
    assert peak[0] == 1 and s.done == {"a", "b", "c"}


def test_max_parallel_caps_concurrency():
    live = [0]
    peak = [0]

    async def runner(f):
        live[0] += 1
        peak[0] = max(peak[0], live[0])
        await asyncio.sleep(0.03)
        live[0] -= 1
        return FeatureOutcome(True)

    run(Plan([feature(x, owner=x) for x in "abcd"]), runner, max_parallel=2)
    assert peak[0] == 2


def test_a_failure_blocks_dependents_but_not_independent_work():
    events = []

    async def runner(f):
        return FeatureOutcome(f.id != "db", "db broke" if f.id == "db" else "")

    plan = Plan([feature("db", owner="a"), feature("api", ["db"], owner="b"), feature("docs", owner="c"), feature("wire", ["api", "docs"], owner="d")])
    s = run(plan, runner, on_event=lambda e, f, d: events.append((e, f.id)))
    assert s.done == {"docs"} and set(s.failed) == {"db"} and set(s.blocked) == {"api", "wire"}
    assert ("blocked", "wire") in events and ("failed", "db") in events and ("started", "api") not in events
    assert "db" in s.blocked["api"]


def test_a_crashing_runner_is_a_failed_feature_not_a_dead_scheduler():
    async def runner(f):
        if f.id == "a":
            raise RuntimeError("boom")
        return FeatureOutcome(True)

    s = run(Plan([feature("a", owner="x"), feature("b", owner="y"), feature("c", ["a"], owner="z")]), runner)
    assert s.failed["a"].startswith("crashed: RuntimeError: boom") and s.done == {"b"} and set(s.blocked) == {"c"}


def test_features_merged_in_an_earlier_run_are_not_run_again():
    ran = []

    async def runner(f):
        ran.append(f.id)
        return FeatureOutcome(True)

    plan = Plan([feature("a", owner="x"), feature("b", ["a"], owner="y"), feature("c", ["b"], owner="z")])
    s = Scheduler(plan, runner, done={"a"})
    asyncio.run(s.run())
    assert ran == ["b", "c"] and s.done == {"a", "b", "c"}
