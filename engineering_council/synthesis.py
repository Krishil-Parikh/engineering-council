"""Disputes -> decisions -> canonical specification. Python owns IDs, coverage and cross-reference integrity."""

from __future__ import annotations

from typing import Callable, TypeVar

from pydantic import BaseModel

from engineering_council import prompts
from engineering_council.config import Settings
from engineering_council.gemini_client import LLM
from engineering_council.models import (
    AGENT_IDS,
    Answer,
    AgentProposal,
    AgentRebuttal,
    AgentReview,
    Decision,
    DecisionSet,
    Dispute,
    ProductSpec,
    Spec,
    SpecDraft,
    TechnicalSpec,
)

T = TypeVar("T", bound=BaseModel)
SEVERITY_ORDER = {"CRITICAL": 0, "MAJOR": 1, "NITPICK": 2}


# --------------------------------------------------------------------------- disputes


def collect_disputes(
    reviews: dict[str, AgentReview], settings: Settings
) -> tuple[list[Dispute], list[Dispute], list[str]]:
    """Assign stable DSP ids in Python. Returns (formal CRITICAL/MAJOR, retained NITPICK, warnings)."""
    participants = set(reviews)
    warnings: list[str] = []
    all_disputes: list[Dispute] = []
    for agent in [a for a in AGENT_IDS if a in reviews]:
        review = reviews[agent]
        mine = sorted(review.disputes, key=lambda d: SEVERITY_ORDER[d.severity])
        if len(mine) > settings.max_disputes_per_reviewer:
            warnings.append(f"{agent} raised {len(mine)} disputes; kept the {settings.max_disputes_per_reviewer} most severe.")
            mine = mine[: settings.max_disputes_per_reviewer]
        if review.no_material_objection and mine:
            warnings.append(f"{agent} claimed NO_MATERIAL_OBJECTION but listed disputes; the disputes were kept.")
        for d in mine:
            target = d.target_agent.strip().upper()
            all_disputes.append(
                d.model_copy(update={"source_agent": agent, "target_agent": target if target in participants else "COUNCIL"})
            )
    numbered = [d.model_copy(update={"dispute_id": f"DSP-{i:03d}"}) for i, d in enumerate(all_disputes, 1)]
    formal = [d for d in numbered if d.severity in ("CRITICAL", "MAJOR")]
    nitpicks = [d for d in numbered if d.severity == "NITPICK"]
    return formal, nitpicks, warnings


# --------------------------------------------------------------------------- decisions


async def decide(
    llm: LLM,
    ctx: str,
    proposals: dict[str, AgentProposal],
    reviews: dict[str, AgentReview],
    formal: list[Dispute],
    nitpicks: list[Dispute],
    rebuttals: dict[str, AgentRebuttal],
    answers: list[Answer],
    internal_notes: list[str],
) -> tuple[list[Decision], list[str]]:
    missing = [a for a in AGENT_IDS if a not in proposals]
    result = await llm.generate(
        prompts.decision_prompt(ctx, proposals, reviews, formal, rebuttals, answers, internal_notes, missing, nitpicks),
        DecisionSet,
        stage="decisions",
        system=prompts.system_for("arbiter"),
    )
    return ensure_dispute_coverage(result.decisions, {d.dispute_id for d in formal})


def ensure_dispute_coverage(decisions: list[Decision], formal_ids: set[str]) -> tuple[list[Decision], list[str]]:
    """Every formal dispute must be settled by a decision or be visibly UNRESOLVED. Never silently dropped."""
    warnings: list[str] = []
    cleaned: list[Decision] = []
    for d in decisions:
        valid = [x for x in d.dispute_ids if x in formal_ids]
        if len(valid) != len(d.dispute_ids):
            warnings.append(f"{d.decision_id} cited unknown dispute ids; they were removed.")
        cleaned.append(d.model_copy(update={"dispute_ids": valid, "requirement_ids": []}))
    covered = {x for d in cleaned for x in d.dispute_ids}
    next_n = max((int(d.decision_id.split("-")[1]) for d in cleaned), default=0) + 1
    for dsp in sorted(formal_ids - covered):
        did = f"DEC-{next_n:03d}"
        next_n += 1
        cleaned.append(
            Decision(
                decision_id=did,
                statement=f"Dispute {dsp} was raised in review but the arbiter did not address it.",
                chosen_option="No decision recorded",
                rationale="Added automatically so the dispute stays visible instead of being silently dropped.",
                dispute_ids=[dsp],
                remaining_uncertainty=[f"{dsp} needs an explicit decision before implementation."],
                status="UNRESOLVED",
            )
        )
        warnings.append(f"Arbiter skipped {dsp}; recorded {did} as UNRESOLVED.")
    return cleaned, warnings


# --------------------------------------------------------------------------- specification


def validate_product(spec: ProductSpec, decisions: list[Decision]) -> list[str]:
    errors: list[str] = []
    dec_ids = {d.decision_id for d in decisions}
    req_ids = [r.id for r in spec.requirements]
    errors += [f"duplicate requirement id {i}" for i in sorted({i for i in req_ids if req_ids.count(i) > 1})]
    ac_ids = [a.id for a in spec.acceptance_criteria]
    errors += [f"duplicate acceptance criterion id {i}" for i in sorted({i for i in ac_ids if ac_ids.count(i) > 1})]
    for r in spec.requirements:
        errors += [f"{r.id} cites unknown decision {x}" for x in r.decision_ids if x not in dec_ids]
    for a in spec.acceptance_criteria:
        if a.requirement_id not in req_ids:
            errors.append(f"{a.id} references unknown requirement {a.requirement_id}")
    return errors


def validate_technical(tech: TechnicalSpec, req_ids: set[str]) -> list[str]:
    errors: list[str] = []
    names = {c.name for c in tech.components}
    for c in tech.components:
        errors += [f"component {c.name} cites unknown requirement {x}" for x in c.requirement_ids if x not in req_ids]
        errors += [f"component {c.name} depends on unknown component {x}" for x in c.depends_on if x not in names]
        if c.path and not path_in_tree(c.path, tech.directory_tree):
            errors.append(f"component {c.name} path {c.path!r} does not appear in directory_tree")
    for k in tech.contracts:
        errors += [f"contract {k.name} cites unknown requirement {x}" for x in k.requirement_ids if x not in req_ids]
    errors += find_cycles({c.name: c.depends_on for c in tech.components})
    orders = [s.order for s in tech.implementation_sequence]
    for s in tech.implementation_sequence:
        errors += [f"step {s.order} depends on step {x}, which is not an earlier step" for x in s.depends_on if x not in orders or x >= s.order]
    return errors


def path_in_tree(path: str, tree: str) -> bool:
    """A hierarchical tree lists names per line, so check that every path segment appears in it."""
    segments = [seg for seg in path.replace("\\", "/").strip("/").split("/") if seg and seg != "."]
    return all(seg in tree for seg in segments)


def find_cycles(graph: dict[str, list[str]]) -> list[str]:
    state: dict[str, int] = {}
    found: list[str] = []

    def visit(node: str, path: list[str]) -> None:
        state[node] = 1
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                found.append("dependency cycle: " + " -> ".join([*path, node, nxt]))
            elif nxt in graph and state.get(nxt) is None:
                visit(nxt, [*path, node])
        state[node] = 2

    for n in graph:
        if state.get(n) is None:
            visit(n, [])
    return found


async def _generate_checked(
    llm: LLM, prompt: str, schema: type[T], check: Callable[[T], list[str]], stage: str, system: str
) -> tuple[T, list[str]]:
    """Generate, cross-check IDs, and retry once with the errors as feedback. Returns (object, leftover_errors)."""
    obj = await llm.generate(prompt, schema, stage=stage, system=system)
    errors = check(obj)
    if errors:
        feedback = "\n\nYour previous answer had these cross-reference errors. Fix them and return the full object:\n- " + "\n- ".join(errors[:20])
        obj = await llm.generate(prompt + feedback, schema, stage=stage + "_retry", system=system)
        errors = check(obj)
    return obj, errors


def sanitize_product(spec: ProductSpec, decisions: list[Decision]) -> ProductSpec:
    """Last resort: drop dangling references rather than keep invented ids."""
    dec_ids = {d.decision_id for d in decisions}
    seen: set[str] = set()
    reqs = []
    for r in spec.requirements:
        if r.id in seen:
            continue
        seen.add(r.id)
        reqs.append(r.model_copy(update={"decision_ids": [x for x in r.decision_ids if x in dec_ids]}))
    seen_ac: set[str] = set()
    acs = []
    for a in spec.acceptance_criteria:
        if a.id in seen_ac or a.requirement_id not in seen:
            continue
        seen_ac.add(a.id)
        acs.append(a)
    return spec.model_copy(update={"requirements": reqs, "acceptance_criteria": acs})


def sanitize_technical(tech: TechnicalSpec, req_ids: set[str]) -> TechnicalSpec:
    names = {c.name for c in tech.components}
    comps = [
        c.model_copy(update={"requirement_ids": [x for x in c.requirement_ids if x in req_ids], "depends_on": [x for x in c.depends_on if x in names and x != c.name]})
        for c in tech.components
    ]
    contracts = [k.model_copy(update={"requirement_ids": [x for x in k.requirement_ids if x in req_ids]}) for k in tech.contracts]
    orders = {s.order for s in tech.implementation_sequence}
    steps = [s.model_copy(update={"depends_on": [x for x in s.depends_on if x in orders and x < s.order]}) for s in tech.implementation_sequence]
    return tech.model_copy(update={"components": comps, "contracts": contracts, "implementation_sequence": steps})


async def build_spec(
    llm: LLM, ctx: str, project_name: str, decisions: list[Decision], answers: list[Answer], warnings: list[str]
) -> tuple[Spec, list[str]]:
    notes: list[str] = []
    system = prompts.system_for("arbiter")
    product, errs = await _generate_checked(
        llm, prompts.product_spec_prompt(ctx, decisions, answers, warnings), ProductSpec,
        lambda p: validate_product(p, decisions), "spec_product", system,
    )
    if errs:
        notes.append("Product spec kept cross-reference errors after one retry; dangling references were removed: " + "; ".join(errs[:5]))
        product = sanitize_product(product, decisions)
    req_ids = {r.id for r in product.requirements}
    tech, errs = await _generate_checked(
        llm, prompts.technical_spec_prompt(ctx, decisions, product), TechnicalSpec,
        lambda t: validate_technical(t, req_ids), "spec_technical", system,
    )
    if errs:
        notes.append("Technical spec kept cross-reference errors after one retry; dangling references were removed: " + "; ".join(errs[:5]))
        tech = sanitize_technical(tech, req_ids)
    spec = assemble(product, tech, project_name, decisions)
    return spec, notes


def assemble(product: ProductSpec, tech: TechnicalSpec, project_name: str, decisions: list[Decision]) -> Spec:
    spec = Spec(**product.model_dump(), **tech.model_dump(), project_name=project_name, decisions=[])
    return finalize_spec(spec, decisions)


def finalize_spec(spec: SpecDraft | Spec, decisions: list[Decision]) -> Spec:
    """Python-owned fixes: back-fill requirement ids onto decisions, surface UNRESOLVED ones as open questions."""
    reqs_by_dec: dict[str, list[str]] = {}
    for r in spec.requirements:
        for d in r.decision_ids:
            reqs_by_dec.setdefault(d, []).append(r.id)
    final_decisions = [d.model_copy(update={"requirement_ids": reqs_by_dec.get(d.decision_id, [])}) for d in decisions]
    open_q = list(spec.open_questions)
    for d in final_decisions:
        if d.status == "UNRESOLVED" and not any(d.decision_id in q for q in open_q):
            open_q.append(f"{d.decision_id}: {d.statement} (UNRESOLVED)")
    data = spec.model_dump()
    data.update(
        decisions=[d.model_dump() for d in final_decisions],
        open_questions=open_q,
        project_name=getattr(spec, "project_name", "") or "",
    )
    return Spec(**data)


def spec_to_draft(spec: Spec) -> SpecDraft:
    return SpecDraft(**spec.model_dump(exclude={"decisions", "project_name"}))

