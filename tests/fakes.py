"""A scripted stand-in for the Gemini client plus a small, fully consistent example specification."""

from __future__ import annotations

from collections import Counter
from typing import Callable

from engineering_council.gemini_client import LLMError
from engineering_council.models import (
    AGENT_IDS,
    AcceptanceCriterion,
    AgentProposal,
    AgentRebuttal,
    AgentReview,
    ArchComponent,
    ComponentProposal,
    ConfigVar,
    Contract,
    DataEntity,
    Decision,
    DecisionSet,
    Dispute,
    ErrorState,
    Flow,
    HumanQuestion,
    Journey,
    Persona,
    ProductSpec,
    RebuttalItem,
    RejectedAlternative,
    Requirement,
    Revision,
    SpecDraft,
    Step,
    TechChoice,
    TechnicalSpec,
    QuestionCuration,
)

TREE = "todo-cli/\n├── todo/\n│   ├── cli.py\n│   └── storage.py\n└── tests/"


def product_spec() -> ProductSpec:
    return ProductSpec(
        summary="A tiny command line task list.",
        problem="People lose track of small tasks.",
        personas=[Persona(name="Solo developer", description="Works in a terminal.", goals=["Capture tasks fast"])],
        goals=["Add and list tasks in one command each"],
        non_goals=["Cloud synchronisation across devices"],
        scope_in=["Add tasks", "List tasks"],
        scope_out=["Sharing tasks"],
        journeys=[Journey(name="Add a task", persona="Solo developer", steps=["Run add", "See confirmation"])],
        requirements=[
            Requirement(id="FR-001", title="Add a task", description="Users can add a task by title.", kind="FUNCTIONAL", decision_ids=["DEC-001"]),
            Requirement(id="FR-002", title="List tasks", description="Users can list stored tasks.", kind="FUNCTIONAL", decision_ids=["DEC-001"]),
            Requirement(id="NFR-001", title="Local storage", description="Data stays on the local disk.", kind="NON_FUNCTIONAL", decision_ids=["DEC-001"]),
        ],
        acceptance_criteria=[
            AcceptanceCriterion(id="AC-001", requirement_id="FR-001", given="an empty list", when="the user adds 'milk'", then="the list contains 'milk'"),
            AcceptanceCriterion(id="AC-002", requirement_id="FR-002", given="two stored tasks", when="the user lists tasks", then="both are printed"),
            AcceptanceCriterion(id="AC-003", requirement_id="NFR-001", given="no network", when="the user adds a task", then="it still succeeds"),
        ],
        risks=["Corrupted storage file"],
        assumptions=["Single user"],
        dependencies=["Python 3.11"],
        open_questions=[],
        success_metrics=["Adding a task takes one command"],
        mvp_boundary="Add and list only; no sync.",
    )


def technical_spec() -> TechnicalSpec:
    return TechnicalSpec(
        tech_choices=[TechChoice(concern="Language", choice="Python 3.11", rationale="Available everywhere"), TechChoice(concern="Storage", choice="JSON file", rationale="Simplest durable store")],
        components=[
            ArchComponent(name="CLI", path="todo/cli.py", responsibility="Parse arguments", depends_on=["Storage"], requirement_ids=["FR-001", "FR-002"]),
            ArchComponent(name="Storage", path="todo/storage.py", responsibility="Read and write tasks", requirement_ids=["NFR-001"]),
        ],
        runtime_flows=[Flow(name="Add", steps=["Parse", "Append", "Save atomically"])],
        data_entities=[DataEntity(name="Task", description="One to-do item", fields=["title: str - required"])],
        contracts=[Contract(name="add_task", kind="FUNCTION", signature="def add_task(title: str) -> Task", requirement_ids=["FR-001"])],
        directory_tree=TREE,
        error_states=[ErrorState(code="E_EMPTY", condition="Empty title", handling="Reject with message")],
        validation_rules=["Title must be 1-200 characters"],
        config_vars=[ConfigVar(name="TODO_FILE", description="Storage path", default="~/.todo.json")],
        security=["Never execute stored text"],
        failure_handling=["Write to a temp file then rename"],
        observability=["Log to stderr"],
        testing=["pytest with a temp directory"],
        verification_commands=["pytest"],
        implementation_sequence=[Step(order=1, title="Storage", details="Implement storage"), Step(order=2, title="CLI", details="Implement CLI", depends_on=[1])],
    )


def draft_spec() -> SpecDraft:
    return SpecDraft(**product_spec().model_dump(), **technical_spec().model_dump())


def decision_set(cover_dispute: bool = True) -> DecisionSet:
    return DecisionSet(decisions=[
        Decision(
            decision_id="DEC-001", statement="Where to persist tasks", chosen_option="JSON file",
            rationale="Simplest durable option", alternatives_considered=["JSON file", "SQLite"],
            rejected_alternatives=[RejectedAlternative(option="SQLite", reason="Unneeded for one user")],
            dispute_ids=["DSP-001"] if cover_dispute else [], status="DECIDED",
        )
    ])


def proposal(agent: str, with_question: bool = False) -> AgentProposal:
    qs = [HumanQuestion(question="Should tasks sync across devices?", why_it_matters="Changes scope", options=["Yes", "No"], recommended_default="No")] if with_question else []
    return AgentProposal(
        agent_id=agent, thesis=f"{agent} thinks a single-process app is enough.",
        components=[ComponentProposal(name="Core", approach="One module", rationale="Small")],
        risks=["Corruption"], assumptions=["Single user"], product_questions=qs,
    )


def review(agent: str) -> AgentReview:
    if agent == "RED_TEAM_QA":
        return AgentReview(agent_id=agent, summary="Atomic writes are missing.", disputes=[
            Dispute(target_agent="PRAGMATIC_MVP", claim="Plain file writes", severity="MAJOR", category="DATA_INTEGRITY",
                    failure_mechanism="A crash mid-write truncates the file", counterproposal="Write temp then rename"),
            Dispute(target_agent="PRODUCT_UX", claim="Colour output", severity="NITPICK", category="OTHER",
                    failure_mechanism="Hard to read in some terminals", counterproposal="Allow disabling"),
        ])
    return AgentReview(agent_id=agent, no_material_objection=True, summary="No material objection.")


class FakeLLM:
    """Dispatches on the requested schema. Counts calls per stage and can fail chosen stages."""

    def __init__(self, fail_stages: tuple[str, ...] = (), cover_dispute: bool = True, bad_spec_once: bool = False) -> None:
        self.usage: list[dict] = []
        self.calls: Counter[str] = Counter()
        self.fail_stages = fail_stages
        self.cover_dispute = cover_dispute
        self.bad_spec_once = bad_spec_once
        self.overrides: dict[type, Callable] = {}

    async def generate(self, prompt, schema, *, stage, system=""):
        self.calls[stage] += 1
        if any(stage.startswith(f) for f in self.fail_stages):
            raise LLMError(f"{stage}: injected failure")
        if schema in self.overrides:
            return self.overrides[schema](prompt, stage)
        agent = stage.split(":", 1)[1] if ":" in stage else ""
        if schema is AgentProposal:
            return proposal(agent, with_question=agent == "PRODUCT_UX")
        if schema is AgentReview:
            return review(agent)
        if schema is AgentRebuttal:
            return AgentRebuttal(agent_id=agent, responses=[RebuttalItem(dispute_id="DSP-001", stance="ACCEPT", response="Fair point.", revised_position="Use atomic rename")])
        if schema is QuestionCuration:
            return QuestionCuration(questions=[HumanQuestion(question="Should tasks sync across devices?", why_it_matters="Changes scope", options=["Yes", "No"], recommended_default="No")] * 9, resolved_internally=["Storage format: JSON"])
        if schema is DecisionSet:
            return decision_set(self.cover_dispute)
        if schema is ProductSpec:
            spec = product_spec()
            if self.bad_spec_once and self.calls[stage] == 1:
                spec.acceptance_criteria.append(AcceptanceCriterion(id="AC-009", requirement_id="FR-777", given="g", when="w", then="t"))
            return spec
        if schema is TechnicalSpec:
            return technical_spec()
        if schema is SpecDraft:
            return draft_spec()
        if schema is Revision:
            d = draft_spec()
            d.requirements[0] = d.requirements[0].model_copy(update={"description": "Users can add a task by title, with an optional due date."})
            return Revision(impacted_requirements=["FR-001"], impacted_sections=["PRD requirements"], summary="Added optional due date.", revised_spec=d)
        raise AssertionError(f"unexpected schema {schema}")


__all__ = ["FakeLLM", "AGENT_IDS", "draft_spec", "product_spec", "technical_spec", "decision_set"]
