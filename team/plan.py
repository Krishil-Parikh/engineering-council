"""The work plan: features with tasks, and what each feature has to wait for.

A *feature* is the unit that gets a branch and an owner: `feature/<id>`. It holds an ordered list of tasks the owner does one after
another. Features depend on other features: a feature starts only after everything it depends on has been merged into the integration
branch, and then branches from it, so it always builds on the finished work. Features with no dependency between them run in parallel.

The plan normally comes from the scrum master (`PLAN_PROMPT`); `validate` checks it and `fallback_plan` builds a safe one from the
specification's implementation sequence when the model's plan is unusable."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from meetings.models import Spec, Step
from team.staffing import pick_developer
from team.repo import slugify

INTEGRATION_WORDS = ("integrat", "wire", "connect", "end-to-end", "e2e", "entrypoint", "entry point", "main ", "cli", "assemble", "glue")


class PlanError(ValueError):
    pass


@dataclass
class Task:
    title: str
    details: str = ""


@dataclass
class Feature:
    id: str
    title: str
    tasks: list[Task]
    owner: Optional[str] = None
    depends_on: list[str] = field(default_factory=list)
    summary: str = ""

    @property
    def branch(self) -> str:
        return f"feature/{self.id}"


@dataclass
class Plan:
    features: list[Feature]

    def get(self, feature_id: str) -> Feature:
        return next(f for f in self.features if f.id == feature_id)

    def validate(self, developers: Optional[list[str]] = None) -> None:
        """Raises PlanError with a message the planner can act on."""
        if not self.features:
            raise PlanError("the plan has no features")
        ids = [f.id for f in self.features]
        if len(set(ids)) != len(ids):
            raise PlanError("feature ids must be unique: " + ", ".join(sorted({i for i in ids if ids.count(i) > 1})))
        known = set(ids)
        for f in self.features:
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", f.id):
                raise PlanError(f"feature id '{f.id}' must be lowercase letters, digits and dashes")
            if not f.tasks:
                raise PlanError(f"feature '{f.id}' has no tasks")
            for d in f.depends_on:
                if d not in known:
                    raise PlanError(f"feature '{f.id}' depends on unknown feature '{d}'")
                if d == f.id:
                    raise PlanError(f"feature '{f.id}' depends on itself")
            if developers is not None and f.owner is not None and f.owner not in developers:
                raise PlanError(f"feature '{f.id}' is owned by '{f.owner}', who is not on the team")
        cycle = self.find_cycle()
        if cycle:
            raise PlanError("dependency cycle: " + " -> ".join(cycle))

    def find_cycle(self) -> list[str]:
        state: dict[str, int] = {}
        stack: list[str] = []

        def visit(fid: str) -> list[str]:
            state[fid] = 1
            stack.append(fid)
            for d in self.get(fid).depends_on:
                if state.get(d) == 1:
                    return stack[stack.index(d):] + [d]
                if state.get(d) is None:
                    found = visit(d)
                    if found:
                        return found
            stack.pop()
            state[fid] = 2
            return []

        for f in self.features:
            if state.get(f.id) is None:
                found = visit(f.id)
                if found:
                    return found
        return []

    def layers(self) -> list[list[str]]:
        """Feature ids grouped by how many dependency levels precede them: each layer could run fully in parallel."""
        depth: dict[str, int] = {}

        def d(fid: str) -> int:
            if fid not in depth:
                depth[fid] = 1 + max((d(x) for x in self.get(fid).depends_on), default=-1)
            return depth[fid]

        out: dict[int, list[str]] = {}
        for f in self.features:
            out.setdefault(d(f.id), []).append(f.id)
        return [out[k] for k in sorted(out)]

    def ready(self, merged: set[str], started: set[str]) -> list[Feature]:
        return [f for f in self.features if f.id not in started and all(d in merged for d in f.depends_on)]

    def assign_owners(self, spec: Spec, roster: dict[str, str]) -> None:
        load: dict[str, int] = {}
        for f in self.features:
            if f.owner is None:
                step = Step(order=0, title=f.title, details=f.summary + " " + " ".join(f"{t.title} {t.details}" for t in f.tasks))
                f.owner = pick_developer(step, spec, roster, load)
            load[f.owner] = load.get(f.owner, 0) + 1

    def to_json(self) -> str:
        return json.dumps({"features": [
            {"id": f.id, "title": f.title, "summary": f.summary, "owner": f.owner, "depends_on": f.depends_on,
             "tasks": [{"title": t.title, "details": t.details} for t in f.tasks]} for f in self.features]}, indent=2)

    @staticmethod
    def from_json(text: str) -> "Plan":
        try:
            data = json.loads(text)
            features = [
                Feature(
                    id=slugify(str(f["id"])), title=str(f.get("title") or f["id"]), summary=str(f.get("summary", "")), owner=f.get("owner") or None,
                    depends_on=[slugify(str(d)) for d in f.get("depends_on", [])],
                    tasks=[Task(str(t["title"]), str(t.get("details", ""))) if isinstance(t, dict) else Task(str(t)) for t in f.get("tasks", [])],
                )
                for f in data["features"]
            ]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise PlanError(f"the plan is not valid JSON of the expected shape: {exc}") from None
        return Plan(features)


def fallback_plan(spec: Spec) -> Plan:
    """One feature per implementation step. A step depends on the earlier steps that touch the same components; a step that integrates
    (wiring, CLI, end-to-end) depends on everything before it; a step that touches nothing in common with earlier work stands alone."""
    steps = sorted(spec.implementation_sequence, key=lambda s: s.order)
    components = [(c.name.lower(), (c.path or "").lower()) for c in spec.components]

    def touched(step: Step) -> set[str]:
        text = f"{step.title} {step.details}".lower()
        return {name for name, path in components if name in text or (path and path in text)}

    features: list[Feature] = []
    touches: dict[str, set[str]] = {}
    for step in steps:
        fid = f"{step.order:02d}-{slugify(step.title)}"[:40].rstrip("-")
        mine = touched(step)
        touches[fid] = mine
        text = f"{step.title} {step.details}".lower()
        if features and any(w in text for w in INTEGRATION_WORDS):
            deps = [f.id for f in features]
        else:
            deps = [f.id for f in features if touches[f.id] & mine]
        if features and not deps and not mine:
            deps = [features[-1].id]  # nothing says it is independent, so it follows the previous step
        features.append(Feature(fid, step.title, [Task(step.title, step.details)], depends_on=deps, summary=step.details[:200]))
    return Plan(features)


PLAN_PROMPT = """You are the scrum master. Turn the agreed specification into a work plan for these developers: {roster}.

Group the implementation work into FEATURES. Each feature gets its own branch and ONE owner; its tasks are done in order by that owner.
Make features as independent as the design allows, so several developers can work at once. Declare `depends_on` only when a feature needs
another feature's code to exist first (a shared module, a schema, an API it calls). Wiring/integration belongs in a late feature that
depends on the features it wires together.

Respond only with JSON, no prose, no markdown fences:
{{"features":[{{"id":"short-kebab-id","title":"...","summary":"one sentence","owner":"<developer name or null>","depends_on":["other-id"],
"tasks":[{{"title":"...","details":"what to build and how to verify it"}}]}}]}}

SPECIFICATION
{spec}
{discussion}"""

DISCUSS_PROMPT = """The team is planning how to build this project, in parallel, each of you in your own clone on your own branch. Before the scrum master writes the plan, talk it through.

From your own skill's point of view: which pieces can be built independently, which must wait for another piece (and why), where two people would end up editing the same file, what must be agreed first (an interface, a schema, a file layout), and who should own what. Say what you would take. Be specific and brief; react to what others said.

SPECIFICATION
{spec}
"""
