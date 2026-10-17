"""Persona instructions and stage prompts. Pure string builders: no I/O, no model calls."""

from __future__ import annotations

import json
from pathlib import Path

from engineering_council.models import (
    AgentProposal,
    AgentReconsideration,
    AgentRebuttal,
    AgentReview,
    Answer,
    Decision,
    Dispute,
    MeetingInput,
    ProductSpec,
    QuestionCuration,
    SpecDraft,
    HumanQuestion,
)

_DIR = Path(__file__).parent / "system_prompts"
_ROLE_FILES = {
    "SYSTEMS_ARCHITECT": "01_systems_architect.md",
    "PRODUCT_UX": "02_product_ux_architect.md",
    "PRAGMATIC_MVP": "03_pragmatic_mvp_architect.md",
    "RED_TEAM_QA": "04_red_team_qa_security.md",
    "review": "05_adversarial_review.md",
    "arbiter": "06_lead_arbiter.md",
    "curator": "07_question_curator.md",
    "documents": "08_document_generator.md",
    "verifier": "09_specification_verifier.md",
    "patch": "10_targeted_patch.md",
}


def _read(name: str) -> str:
    return (_DIR / name).read_text(encoding="utf-8").strip()


def system_for(*roles: str) -> str:
    """Shared rules first, then each requested role prompt (e.g. a persona plus the review prompt)."""
    return "\n\n---\n\n".join([_read("00_shared_rules.md"), *(_read(_ROLE_FILES[r]) for r in roles)])


PERSONAS: dict[str, dict[str, str]] = {
    "SYSTEMS_ARCHITECT": {
        "title": "Systems Architect",
        "mandate": "Domain boundaries, data integrity, interfaces, persistence, concurrency, and how the pieces "
        "depend on each other.",
        "questions": "What are the core entities and who owns each? What is the source of truth? Which interfaces "
        "must be stable? What happens under concurrent access, partial failure or restart? Where does the "
        "dependency direction point, and is there any cycle?",
        "bias": "Over-engineering: adding layers and abstractions before a second use-case exists.",
    },
    "PRODUCT_UX": {
        "title": "Product and UX Lead",
        "mandate": "User journeys, workflows, usability, how developers or users consume the system, and the "
        "feedback they get at every state (loading, empty, error, success).",
        "questions": "Who is the user and what are they trying to get done? What is the shortest path to first "
        "value? What does a confused or impatient user see? What is the error message and the next action? "
        "What scope decision should only the human make?",
        "bias": "Feature creep: designing for imaginary users instead of the stated one.",
    },
    "PRAGMATIC_MVP": {
        "title": "Pragmatic MVP Engineer",
        "mandate": "The smallest design that proves the idea: implementation effort, dependency minimisation, "
        "and what to deliberately leave out.",
        "questions": "What is the least we can build that still meets every MUST requirement? Which dependency can "
        "we delete? What can be a function instead of a service? What would we regret skipping, and what "
        "would we regret building?",
        "bias": "Under-building: cutting something that later forces a rewrite or removes the product's point.",
    },
    "RED_TEAM_QA": {
        "title": "Red Team and QA Engineer",
        "mandate": "Edge cases, security, reliability, testability and failure modes. Run a pre-mortem: assume the "
        "project failed in six months and explain why.",
        "questions": "What input breaks this? What can an attacker or a careless user do? What fails silently? "
        "How would we know it is broken? How do we test it without paying for or depending on a live service?",
        "bias": "Paranoia: blocking progress on risks that are unlikely or cheap to accept.",
    },
}


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (none)"


def context_block(inp: MeetingInput, repo_text: str) -> str:
    return (
        f"PROJECT NAME: \"{inp.project_name}\"\n\n"
        f"PROBLEM STATEMENT (from the user):\n<problem_statement>\n{inp.problem}\n</problem_statement>\n\n"
        f"USER CONSTRAINTS:\n{_bullets(inp.constraints)}\n\n"
        f"REPOSITORY CONTEXT:\n{repo_text}"
    )


# --------------------------------------------------------------------------- stage 2


def proposal_prompt(agent_id: str, ctx: str) -> str:
    p = PERSONAS[agent_id]
    return f"""You are the {p['title']} ({agent_id}).
Your mandate: {p['mandate']}
Questions you always ask: {p['questions']}
Your own known bias, which you must actively resist: {p['bias']}

You are preparing ALONE, before the meeting. You have not seen anyone else's proposal. Write your opening \
position as you would bring it to the table.

{ctx}

Produce your proposal:
- thesis: 2-4 sentences. Your core argument for how this should be built and why.
- components: the major components you would build. For each: name, approach (what it does and how), rationale \
(why this and not the obvious alternative), assumptions, risks. Be specific enough that a colleague could \
disagree with it.
- trade_offs: each significant choice with what it gains and what it costs.
- risks and assumptions: the ones that actually matter, tagged "Unknown:" where you are guessing.
- evidence: the facts (user requirements, repository observations, well-known engineering practice) that \
support your material claims. Say which kind each is.
- product_questions: ONLY questions whose answer would change product scope, user experience, budget or \
deadline, which an engineer cannot decide alone. Each needs why_it_matters, 2-4 concrete options and a \
recommended_default. Technical choices are yours to make; do not ask the human about them. Maximum 3.

Set agent_id to "{agent_id}"."""


# --------------------------------------------------------------------------- stage 3


def review_prompt(agent_id: str, ctx: str, own: AgentProposal, others: dict[str, AgentProposal]) -> str:
    p = PERSONAS[agent_id]
    shown = "\n\n".join(f"=== PROPOSAL FROM {aid} ===\n{prop.model_dump_json(indent=1)}" for aid, prop in others.items())
    return f"""You are the {p['title']} ({agent_id}). The independent proposals are now on the table. \
Your own proposal was:
{own.model_dump_json(indent=1)}

{ctx}

The other proposals:
{shown}

Review them the way a sharp colleague would in the room:
1. endorsements: ideas from OTHER proposals that are better than yours or that you want adopted (say which and why).
2. disputes: material objections only. For each: target_agent (one of {', '.join(others)}), claim (quote or \
paraphrase the exact claim), severity, category (exactly one of REQUIREMENT_GAP, INTEGRATION_MISMATCH, SECURITY, \
RELIABILITY, OVER_ENGINEERING, UNDER_SPECIFIED, UNTESTABLE, UNSUPPORTED_CLAIM, DATA_INTEGRITY, UX_FAILURE, \
OTHER), failure_mechanism (the concrete sequence by which this goes wrong, or the requirement it misses), \
counterproposal (what to do instead), conditions (when the objection matters; empty if always).
   Severity guide: CRITICAL = the project fails or is unsafe if unaddressed; MAJOR = materially worse result or \
significant rework; NITPICK = taste or minor. At most {{max_disputes}} disputes; spend them on what matters.
3. product_questions: only if reading the others revealed a product/scope decision the human must make.
4. If you find no material problem, set no_material_objection=true and leave disputes empty. Do not invent \
objections. Disagreeing with your own earlier position is allowed when another proposal changed your mind.

summary: 2-3 sentences on where the council agrees and where it is split.
Set agent_id to "{agent_id}"."""


def rebuttal_prompt(agent_id: str, own: AgentProposal, disputes: list[Dispute]) -> str:
    p = PERSONAS[agent_id]
    listed = "\n".join(
        f"- {d.dispute_id} from {d.source_agent} [{d.severity}/{d.category}] on \"{d.claim}\"\n"
        f"  failure mechanism: {d.failure_mechanism}\n  counterproposal: {d.counterproposal}\n"
        f"  conditions: {d.conditions or 'always'}"
        for d in disputes
    )
    return f"""You are the {p['title']} ({agent_id}). Colleagues raised objections against your proposal:

YOUR PROPOSAL:
{own.model_dump_json(indent=1)}

OBJECTIONS AGAINST YOU:
{listed}

Respond to EVERY dispute_id exactly once, as an honest professional would:
- ACCEPT: they are right; say what you now change (revised_position).
- PARTIAL: part of it holds; say which part, and what the middle ground is (revised_position).
- REJECT: explain, with a concrete reason, why the objection does not apply or the counterproposal is worse.
Do not defend for the sake of it, and do not concede to be agreeable. response should be 2-4 sentences.
Set agent_id to "{agent_id}"."""


# --------------------------------------------------------------------------- stage 5


def curation_prompt(candidates: list[tuple[str, HumanQuestion]], max_q: int, ctx: str) -> str:
    listed = "\n".join(
        f"{i + 1}. [{src}] {q.question}\n   why: {q.why_it_matters}\n   options: {q.options}\n   default: {q.recommended_default}"
        for i, (src, q) in enumerate(candidates)
    )
    return f"""You are the moderator preparing the human decision gate. The council produced these candidate questions:

{listed}

{ctx}

Curate them:
- Merge duplicates and near-duplicates into one sharper question.
- KEEP only questions about product outcomes, scope, user expectations, constraints, budget, deadline or a \
consequential trade-off that the human owns.
- DROP anything an engineer should decide (frameworks, schema, libraries, file layout) and anything the user's \
statement already answers. List each dropped technical item in resolved_internally with the choice you assume.
- At most {max_q} questions, ideally 3 or fewer, most decision-changing first. Zero is fine.
- Each question needs why_it_matters, 2-4 distinct options, and a recommended_default that is exactly one of the options."""


def reconsideration_prompt(
    agent_id: str,
    own: AgentProposal,
    others: dict[str, AgentProposal],
    disputes: list[Dispute],
    rebuttals: dict[str, AgentRebuttal],
    answers: list[Answer],
    internal_notes: list[str],
) -> str:
    p = PERSONAS[agent_id]
    peers = "\n".join(f"- {a}: {q.thesis}" for a, q in others.items() if a != agent_id) or "- (none)"
    disp = "\n".join(f"- {d.dispute_id} [{d.severity}] {d.source_agent} -> {d.target_agent}: {d.claim}" for d in disputes) or "- (none)"
    rebs = "\n".join(
        f"- {r.dispute_id} ({a}): {r.stance}: {r.response} | revised: {r.revised_position or 'n/a'}"
        for a, rb in rebuttals.items() for r in rb.responses
    ) or "- (none)"
    ans = "\n".join(f"- Q: {a.question}\n  A: {a.answer} ({a.source})" for a in answers) or "- (no questions were asked)"
    return f"""You are the {p['title']} ({agent_id}). The human has now answered the council's questions. The council reconvenes to re-discuss before the arbiter decides.

YOUR OWN PROPOSAL:
{own.model_dump_json(indent=1)}

THE OTHER MEMBERS' THESES:
{peers}

OBJECTIONS RAISED:
{disp}

REBUTTALS HEARD:
{rebs}

THE HUMAN'S ANSWERS (authoritative):
{ans}

ASSUMPTIONS ALREADY MADE ON THE HUMAN'S BEHALF:
{_bullets(internal_notes)}

Reconsider honestly, as a professional would after learning the real constraints:
- answer_impact: 2-4 sentences on what each answer changes for your recommendations. If an answer invalidates something you proposed (for example scope, scale, audience), say exactly what.
- position_changes: every concrete thing you now propose differently, with the reason. Include concessions to colleagues whose rebuttals or objections were right.
- unchanged: positions you still hold despite the answers, each with a reason.
- new_conflicts: disagreements with a specific colleague that the answers created or exposed (with_agent must be one of the other member ids). Do not invent conflict; leave empty if there is none.
- advice_to_arbiter: up to 4 short, specific recommendations for the final decisions.
Never contradict the human's answers. Set agent_id to "{agent_id}"."""


# --------------------------------------------------------------------------- stage 6


def decision_prompt(
    ctx: str,
    proposals: dict[str, AgentProposal],
    reviews: dict[str, AgentReview],
    disputes: list[Dispute],
    rebuttals: dict[str, AgentRebuttal],
    answers: list[Answer],
    internal_notes: list[str],
    missing_agents: list[str],
    nitpicks: list[Dispute],
    reconsiderations: "dict[str, AgentReconsideration] | None" = None,
) -> str:
    recon = "\n".join(
        f"=== {a} ===\nimpact: {r.answer_impact}\nchanged: {[f'{c.topic}: {c.change}' for c in r.position_changes]}\n"
        f"held: {r.unchanged}\nnew conflicts: {[f'with {n.with_agent}: {n.issue} (they say: {n.my_position})' for n in r.new_conflicts]}\n"
        f"advice: {r.advice_to_arbiter}"
        for a, r in (reconsiderations or {}).items()
    ) or "- (the council did not re-discuss)"
    props = "\n".join(f"=== {a} ===\n{p.model_dump_json()}" for a, p in proposals.items())
    endorse = "\n".join(f"- {a}: {r.endorsements}" for a, r in reviews.items() if r.endorsements) or "- (none)"
    rebs = "\n".join(
        f"- {r.dispute_id} answered by {a}: {r.stance}: {r.response} | revised: {r.revised_position}"
        for a, rb in rebuttals.items()
        for r in rb.responses
    ) or "- (none)"
    disp = "\n".join(
        f"- {d.dispute_id} [{d.severity}] {d.source_agent} -> {d.target_agent}: \"{d.claim}\"; "
        f"mechanism: {d.failure_mechanism}; counter: {d.counterproposal}"
        for d in disputes
    ) or "- (none)"
    nits = "\n".join(f"- {d.dispute_id} {d.claim}" for d in nitpicks) or "- (none)"
    ans = "\n".join(f"- Q: {a.question}\n  A: {a.answer} ({a.source})" for a in answers) or "- (no questions were asked)"
    missing = f"\nWARNING: these council members failed to contribute and are NOT represented: {missing_agents}\n" if missing_agents else ""
    return f"""You are the lead arbiter. Synthesize the council's work into binding decisions.{missing}

{ctx}

PROPOSALS:
{props}

ENDORSEMENTS:
{endorse}

FORMAL DISPUTES (CRITICAL and MAJOR):
{disp}

REBUTTALS:
{rebs}

NITPICKS (retained for the record, need no decision):
{nits}

ANSWERS FROM THE HUMAN (authoritative; never contradict or invent these):
{ans}

RE-DISCUSSION AFTER THE ANSWERS (each member's updated position; prefer these over their earlier proposals where they differ, and settle every new conflict explicitly):
{recon}

TECHNICAL ASSUMPTIONS ALREADY MADE ON THE HUMAN'S BEHALF:
{_bullets(internal_notes)}

Produce decisions. Rules:
- decision_id: DEC-001, DEC-002, ... unique.
- One decision per material choice (architecture, data, interfaces, scope, security, testing, dependencies).
- chosen_option, rationale (why, citing evidence or the human's answers), alternatives_considered, and \
rejected_alternatives each with the reason it lost. Rejected alternatives must be real options the council \
actually raised or obvious ones, not strawmen.
- dispute_ids: list every formal dispute the decision settles. EVERY formal dispute above must be settled by some \
decision, or you must create a decision with status UNRESOLVED that names it. Never ignore a dispute.
- status: DECIDED when the evidence and answers support it; PROVISIONAL when you chose a default that a future \
fact could change (say what in remaining_uncertainty); UNRESOLVED when the council genuinely cannot decide and \
the human or a spike must.
- Do not claim the human said anything they did not. Do not turn assumptions into facts.
- Leave requirement_ids empty."""


# --------------------------------------------------------------------------- stage 7


def product_spec_prompt(ctx: str, decisions: list[Decision], answers: list[Answer], warnings: list[str]) -> str:
    decs = "\n".join(f"{d.model_dump_json()}" for d in decisions)
    ans = "\n".join(f"- Q: {a.question} A: {a.answer}" for a in answers) or "- (none)"
    return f"""Write the PRODUCT half of the canonical specification. Every document is rendered from it, \
so it must be complete and internally consistent.

{ctx}

BINDING DECISIONS:
{decs}

HUMAN ANSWERS:
{ans}

KNOWN CAVEATS: {warnings or 'none'}

Requirements:
- summary, problem, personas (with goals), goals, non_goals, scope_in, scope_out, journeys (numbered steps, \
including an error/empty path), risks, assumptions, dependencies, open_questions, success_metrics (measurable), \
mvp_boundary (one paragraph that says exactly what is and is not in the MVP).
- requirements: stable IDs FR-001... for functional and NFR-001... for non-functional (performance, reliability, \
security, portability, maintainability, cost). Each has title, description, kind, priority, in_scope, and \
decision_ids that cite ONLY DEC ids listed above. Be specific and testable. Cover every DECIDED/PROVISIONAL \
decision with at least one requirement.
- acceptance_criteria: AC-001... each with requirement_id (an existing FR/NFR id), given, when, then. Every \
in-scope FUNCTIONAL requirement needs at least one; add negative-path criteria for important failures.
- Do not list a non-goal as a requirement. Put out-of-scope ideas in non_goals/scope_out, not in_scope.
- UNRESOLVED decisions must appear in open_questions.
- Only use IDs you define here; never reference an ID that does not exist."""


def technical_spec_prompt(ctx: str, decisions: list[Decision], product: ProductSpec) -> str:
    reqs = "\n".join(f"- {r.id} ({r.kind}, in_scope={r.in_scope}): {r.title}" for r in product.requirements)
    decs = "\n".join(
        f"- {d.decision_id} [{d.status}] {d.statement} => {d.chosen_option}" for d in decisions
    )
    return f"""Write the TECHNICAL half of the canonical specification so a developer or coding agent can implement \
from it without guessing.

{ctx}

DECISIONS:
{decs}

REQUIREMENTS ALREADY FIXED (reference these ids, do not redefine them):
{reqs}

Requirements:
- tech_choices: concern, choice, rationale. The choice text must be a short name (e.g. "PostgreSQL 16") that you \
will use verbatim everywhere else.
- components: name, path (a real file or folder path that ALSO appears in directory_tree), responsibility, \
depends_on (other component names; no cycles), requirement_ids (existing FR/NFR ids). Keep the layout flat and \
simple: no needless packages or layers.
- runtime_flows: the important flows as numbered steps, including one failure flow.
- data_entities and contracts ONLY if the product genuinely needs them. No invented SQL tables or HTTP routes for \
a project that has none. Contract.signature is the exact path/signature (e.g. "POST /api/items") and must be \
used consistently.
- directory_tree: a plain-text tree of the canonical layout.
- error_states (code, condition, handling), validation_rules, config_vars (env/config contract), ui_notes \
(empty string when there is no UI), security, failure_handling (timeouts, retries, recovery), observability, \
testing (strategy incl. how to test without live services), verification_commands (exact commands, only where \
known; otherwise mark as proposed).
- implementation_sequence: ordered steps with depends_on referencing earlier step order numbers.
- Mark anything the evidence does not support as "Proposed:" or "Unresolved:" in its text."""


def repair_prompt(spec: SpecDraft, failures: list[str]) -> str:
    return f"""The deterministic verifier found problems in the canonical specification. Fix ONLY what is needed to \
resolve them and change nothing else. Do not add features, do not delete valid requirements to make a check pass \
unless the check says a requirement is invalid.

FAILURES:
{_bullets(failures)}

CURRENT SPECIFICATION:
{spec.model_dump_json(indent=1)}

Return the full corrected specification. IDs must stay stable; reference only ids that exist."""


def revision_prompt(spec: SpecDraft, decisions: list[Decision], feedback: str) -> str:
    return f"""The user reviewed the generated documents and asked for a targeted change.

USER FEEDBACK:
<feedback>
{feedback}
</feedback>

DECISIONS (read-only context):
{json.dumps([d.model_dump(mode='json') for d in decisions], indent=1)}

CURRENT SPECIFICATION:
{spec.model_dump_json(indent=1)}

Identify what the feedback impacts (impacted_requirements, impacted_decisions, impacted_sections, summary), then \
return revised_spec: the complete specification with ONLY the impacted content changed. Keep all existing ids \
stable; new items continue the numbering; every in-scope functional requirement needs acceptance criteria."""
