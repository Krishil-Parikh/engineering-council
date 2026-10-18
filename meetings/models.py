"""Pydantic schemas for every stage. Model output is untrusted until it validates against these."""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Six generic developers. The pod decides which skills the problem needs and each developer is staffed to one of them (see
# conversation.assign_skills); skills are not exclusive, so a needed skill can have several developers. A scrum master leads.
AGENT_IDS = ("DEV_1", "DEV_2", "DEV_3", "DEV_4", "DEV_5", "DEV_6")
SCRUM_MASTER = "SCRUM_MASTER"
SKILLS = ("FRONTEND", "BACKEND", "AIML", "MLOPS", "DEVOPS", "DATABASE")

Severity = Literal["CRITICAL", "MAJOR", "NITPICK"]
DecisionStatus = Literal["DECIDED", "PROVISIONAL", "UNRESOLVED"]
Stance = Literal["ACCEPT", "PARTIAL", "REJECT"]
Priority = Literal["MUST", "SHOULD", "COULD"]

# Stable ID formats used across all artifacts.
ID_PATTERNS = {
    "FR": re.compile(r"^FR-\d{3}$"),
    "NFR": re.compile(r"^NFR-\d{3}$"),
    "DEC": re.compile(r"^DEC-\d{3}$"),
    "AC": re.compile(r"^AC-\d{3}$"),
    "DSP": re.compile(r"^DSP-\d{3}$"),
}
ID_IN_TEXT = re.compile(r"\b(?:NFR|FR|DEC|AC|DSP)-\d{1,4}\b")


def normalize_id(value: str) -> str:
    """'fr-1' -> 'FR-001'. Leaves anything unrecognised alone so validation can reject it."""
    m = re.fullmatch(r"\s*([A-Za-z]{2,3})[-_ ]?(\d{1,4})\s*", value or "")
    if not m:
        return (value or "").strip()
    return f"{m.group(1).upper()}-{int(m.group(2)):03d}"


def _norm_list(values: list[str]) -> list[str]:
    return [normalize_id(v) for v in values]


# --------------------------------------------------------------------------- inputs


class MeetingInput(BaseModel):
    project_name: str
    problem: str
    constraints: list[str] = Field(default_factory=list)
    repo_path: Optional[str] = None
    github_url: Optional[str] = None
    output_dir: str = "output"


class RepoFile(BaseModel):
    path: str
    excerpt: str
    truncated: bool = False


class RepoSnapshot(BaseModel):
    mode: Literal["greenfield", "existing"] = "greenfield"
    source: str = ""
    tree: list[str] = Field(default_factory=list)
    languages: dict[str, int] = Field(default_factory=dict)
    technologies: list[str] = Field(default_factory=list)
    files: list[RepoFile] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- proposals


class HumanQuestion(BaseModel):
    question: str
    why_it_matters: str
    options: list[str] = Field(default_factory=list)
    recommended_default: str
    triggering_conflict: str = ""


class ComponentProposal(BaseModel):
    name: str
    approach: str
    rationale: str
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class TradeOff(BaseModel):
    choice: str
    gain: str
    cost: str


class AgentProposal(BaseModel):
    agent_id: str = ""
    thesis: str
    components: list[ComponentProposal]
    trade_offs: list[TradeOff] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    alternatives_considered: list[str] = Field(default_factory=list)
    product_questions: list[HumanQuestion] = Field(default_factory=list)
    layout_sketch: str = ""  # the project folder layout this developer would propose, as a short tree


# --------------------------------------------------------------------------- review


class Dispute(BaseModel):
    dispute_id: str = ""  # assigned in Python (DSP-001...), never trusted from the model
    source_agent: str = ""
    target_agent: str
    claim: str
    severity: Severity
    category: str
    failure_mechanism: str
    counterproposal: str
    conditions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class AgentReview(BaseModel):
    agent_id: str = ""
    no_material_objection: bool = False
    summary: str = ""
    endorsements: list[str] = Field(default_factory=list)  # ideas worth adopting from others
    disputes: list[Dispute] = Field(default_factory=list)
    product_questions: list[HumanQuestion] = Field(default_factory=list)


class RebuttalItem(BaseModel):
    dispute_id: str
    stance: Stance
    response: str
    revised_position: str = ""


class AgentRebuttal(BaseModel):
    agent_id: str = ""
    responses: list[RebuttalItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- the conversation


class BlindThoughts(BaseModel):
    """A developer's first, skill-free reaction to the problem. Written alone, before any specialism is chosen."""

    agent_id: str = ""
    understanding: str  # what the problem really is, in the developer's own words
    ideas: list[str] = Field(default_factory=list)
    worries: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    skills_needed: list[str] = Field(default_factory=list)  # the SKILLS this problem really needs, most important first
    skill_preferences: list[str] = Field(default_factory=list)  # of those, which this developer would most like to take, most wanted first


class Utterance(BaseModel):
    to: str = "ALL"  # a developer id, SCRUM_MASTER or ALL
    kind: Literal["BUILD_ON", "CHALLENGE", "REBUT", "INNOVATE", "AGREE", "CONCEDE", "QUESTION"]
    text: str


class AgentTurn(BaseModel):
    """One developer speaking once: said to colleagues, plus typed objections and answers to objections against them."""

    agent_id: str = ""
    utterances: list[Utterance] = Field(default_factory=list)
    disputes: list[Dispute] = Field(default_factory=list)
    responses: list[RebuttalItem] = Field(default_factory=list)  # answers to dispute ids raised against this developer
    endorsements: list[str] = Field(default_factory=list)
    product_questions: list[HumanQuestion] = Field(default_factory=list)
    pass_turn: bool = False  # nothing to add right now: like a person who simply stays quiet


class ScrumNote(BaseModel):
    """The scrum master steering the room: where we are, what is settled, what to dig into next."""

    summary: str
    agreements: list[str] = Field(default_factory=list)
    open_threads: list[str] = Field(default_factory=list)
    focus_next: list[str] = Field(default_factory=list)
    message_to_team: str = ""
    product_questions: list[HumanQuestion] = Field(default_factory=list)
    next_speakers: list[str] = Field(default_factory=list)  # developers the scrum master wants to hear next
    ready_to_wrap: bool = False  # the room has converged; time to take questions to the human


class RoundRecord(BaseModel):
    round: int
    note: ScrumNote
    turns: list[AgentTurn] = Field(default_factory=list)
    disputes: list[Dispute] = Field(default_factory=list)  # disputes first raised this round, with ids assigned


class Roster(BaseModel):
    skills: dict[str, str] = Field(default_factory=dict)  # DEV_1 -> BACKEND


class PositionChange(BaseModel):
    topic: str
    change: str  # what the member now proposes differently
    reason: str


class NewConflict(BaseModel):
    with_agent: str
    issue: str
    my_position: str


class AgentReconsideration(BaseModel):
    """A member's updated view after the human's answers and the rebuttals: the council's re-discussion round."""

    agent_id: str = ""
    answer_impact: str = ""  # how the human's answers change (or do not change) this member's view
    position_changes: list[PositionChange] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)  # positions held, with the reason
    new_conflicts: list[NewConflict] = Field(default_factory=list)  # disagreements that the answers created or exposed
    advice_to_arbiter: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- questions


class QuestionCuration(BaseModel):
    questions: list[HumanQuestion] = Field(default_factory=list)
    resolved_internally: list[str] = Field(default_factory=list)  # technical items not worth the human's time


class Answer(BaseModel):
    question: str
    answer: str
    source: Literal["option", "custom", "default", "non_interactive_default"]


# --------------------------------------------------------------------------- decisions


class RejectedAlternative(BaseModel):
    option: str
    reason: str


class Decision(BaseModel):
    decision_id: str
    statement: str
    chosen_option: str
    rationale: str
    alternatives_considered: list[str] = Field(default_factory=list)
    rejected_alternatives: list[RejectedAlternative] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    dispute_ids: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)  # back-filled from the spec in Python
    remaining_uncertainty: list[str] = Field(default_factory=list)
    status: DecisionStatus

    @field_validator("decision_id")
    @classmethod
    def _dec_id(cls, v: str) -> str:
        v = normalize_id(v)
        if not ID_PATTERNS["DEC"].match(v):
            raise ValueError(f"decision_id must look like DEC-001, got {v!r}")
        return v

    @field_validator("dispute_ids")
    @classmethod
    def _dsp_ids(cls, v: list[str]) -> list[str]:
        return _norm_list(v)


class DecisionSet(BaseModel):
    decisions: list[Decision]

    @model_validator(mode="after")
    def _unique(self) -> "DecisionSet":
        ids = [d.decision_id for d in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("decision_id values must be unique")
        if not ids:
            raise ValueError("at least one decision is required")
        return self


# --------------------------------------------------------------------------- specification


class Persona(BaseModel):
    name: str
    description: str
    goals: list[str] = Field(default_factory=list)


class Journey(BaseModel):
    name: str
    persona: str
    steps: list[str]


class Requirement(BaseModel):
    id: str
    title: str
    description: str
    kind: Literal["FUNCTIONAL", "NON_FUNCTIONAL"]
    priority: Priority = "MUST"
    in_scope: bool = True
    decision_ids: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        v = normalize_id(v)
        if not (ID_PATTERNS["FR"].match(v) or ID_PATTERNS["NFR"].match(v)):
            raise ValueError(f"requirement id must look like FR-001 or NFR-001, got {v!r}")
        return v

    @field_validator("decision_ids")
    @classmethod
    def _decs(cls, v: list[str]) -> list[str]:
        return _norm_list(v)


class AcceptanceCriterion(BaseModel):
    id: str
    requirement_id: str
    given: str
    when: str
    then: str

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        v = normalize_id(v)
        if not ID_PATTERNS["AC"].match(v):
            raise ValueError(f"criterion id must look like AC-001, got {v!r}")
        return v

    @field_validator("requirement_id")
    @classmethod
    def _req(cls, v: str) -> str:
        return normalize_id(v)


class ProductSpec(BaseModel):
    summary: str
    problem: str
    personas: list[Persona]
    goals: list[str]
    non_goals: list[str]
    scope_in: list[str]
    scope_out: list[str] = Field(default_factory=list)
    journeys: list[Journey]
    requirements: list[Requirement]
    acceptance_criteria: list[AcceptanceCriterion]
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    success_metrics: list[str]
    mvp_boundary: str
    context_diagram: str = ""  # Mermaid flowchart: actors and external systems around the system


class TechChoice(BaseModel):
    concern: str
    choice: str
    rationale: str


class ArchComponent(BaseModel):
    name: str
    path: str  # module/file path as it appears in directory_tree
    responsibility: str
    depends_on: list[str] = Field(default_factory=list)  # other component names
    requirement_ids: list[str] = Field(default_factory=list)

    @field_validator("requirement_ids")
    @classmethod
    def _reqs(cls, v: list[str]) -> list[str]:
        return _norm_list(v)


class Flow(BaseModel):
    name: str
    steps: list[str]
    diagram: str = ""  # Mermaid sequenceDiagram or flowchart of the same steps


class DataEntity(BaseModel):
    name: str
    description: str
    fields: list[str]  # "name: type - note"


class Contract(BaseModel):
    name: str
    kind: Literal["HTTP", "FUNCTION", "CLI", "EVENT", "FILE"]
    signature: str  # e.g. "POST /api/items" or "def run(...) -> Result"
    request: str = ""
    response: str = ""
    errors: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)

    @field_validator("requirement_ids")
    @classmethod
    def _reqs(cls, v: list[str]) -> list[str]:
        return _norm_list(v)


class ErrorState(BaseModel):
    code: str
    condition: str
    handling: str


class ConfigVar(BaseModel):
    name: str
    description: str
    default: str = ""
    required: bool = False


class Step(BaseModel):
    order: int
    title: str
    details: str
    depends_on: list[int] = Field(default_factory=list)


class TechnicalSpec(BaseModel):
    tech_choices: list[TechChoice]
    components: list[ArchComponent]
    runtime_flows: list[Flow]
    data_entities: list[DataEntity] = Field(default_factory=list)
    contracts: list[Contract] = Field(default_factory=list)
    directory_tree: str
    architecture_diagram: str = ""  # Mermaid flowchart of the components
    data_model_diagram: str = ""  # Mermaid erDiagram, only when there are data entities
    error_states: list[ErrorState]
    validation_rules: list[str] = Field(default_factory=list)
    config_vars: list[ConfigVar] = Field(default_factory=list)
    ui_notes: str = ""  # empty when the product has no UI
    security: list[str]
    failure_handling: list[str]
    observability: list[str] = Field(default_factory=list)
    testing: list[str]
    verification_commands: list[str] = Field(default_factory=list)
    implementation_sequence: list[Step]


class SpecDraft(ProductSpec, TechnicalSpec):
    """Everything the model writes. Decisions come from the arbiter, never from this call."""


class Spec(SpecDraft):
    project_name: str = ""
    decisions: list[Decision] = Field(default_factory=list)


# --------------------------------------------------------------------------- verification / state


class Check(BaseModel):
    name: str
    passed: bool
    details: list[str] = Field(default_factory=list)


class VerificationReport(BaseModel):
    checks: list[Check]
    repaired: bool = False

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]


class Revision(BaseModel):
    impacted_requirements: list[str] = Field(default_factory=list)
    impacted_decisions: list[str] = Field(default_factory=list)
    impacted_sections: list[str] = Field(default_factory=list)
    summary: str
    revised_spec: SpecDraft


class DesignVote(BaseModel):
    """One developer's opinion on the draft directory structure and architecture diagram."""

    agent_id: str = ""
    directory_ok: bool = True
    directory_changes: list[str] = Field(default_factory=list)  # concrete: "move X to Y", "drop folder Z"
    architecture_ok: bool = True
    architecture_changes: list[str] = Field(default_factory=list)
    discussion: list[Utterance] = Field(default_factory=list)  # replies to colleagues' earlier remarks


class DesignReview(BaseModel):
    rounds: list[list[DesignVote]] = Field(default_factory=list)
    revisions: list[str] = Field(default_factory=list)  # what changed after each round
    agreed: bool = True


class MeetingState(BaseModel):
    stage: str = "created"
    status: Literal["running", "completed", "failed"] = "running"
    started_at: str = ""
    updated_at: str = ""
    completed_stages: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str = ""
    model: str = ""
