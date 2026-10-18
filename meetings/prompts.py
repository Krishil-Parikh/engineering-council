"""Persona instructions and stage prompts. Pure string builders: no I/O, no model calls."""

from __future__ import annotations

import json
from pathlib import Path

from meetings.models import (
    AgentProposal,
    BlindThoughts,
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
    "developer": "11_developer.md",
    "scrum": "12_scrum_master.md",
    "review": "05_adversarial_review.md",
    "arbiter": "06_lead_arbiter.md",
    "curator": "07_question_curator.md",
    "documents": "08_document_generator.md",
    "verifier": "09_specification_verifier.md",
    "patch": "10_targeted_patch.md",
    "mermaid": "13_mermaid_skill.md",
}


def _read(name: str) -> str:
    return (_DIR / name).read_text(encoding="utf-8").strip()


def system_for(*roles: str) -> str:
    """Shared rules first, then each requested role prompt (e.g. developer plus the review rules)."""
    return "\n\n---\n\n".join([_read("00_shared_rules.md"), *(_read(_ROLE_FILES[r]) for r in roles)])


# What each skill makes a developer notice. Used once a developer has picked (or been given) a skill.
SKILL_LENSES: dict[str, dict[str, str]] = {
    "FRONTEND": {
        "title": "Frontend",
        "sees": "Every user-facing surface: screens or terminal views, navigation, state handling, loading/empty/error/success "
        "states, accessibility, responsiveness, input validation, perceived latency and how the interface talks to the backend.",
        "asks": "What does the user see at every moment, including when it is slow, empty or broken? Which state lives on the client? "
        "What is the shortest path to first value? What would confuse a first-time user?",
    },
    "BACKEND": {
        "title": "Backend",
        "sees": "Service boundaries, APIs and contracts, business logic, auth, concurrency, idempotency, queues and background jobs, "
        "error handling and integration with third-party systems.",
        "asks": "What are the core operations and who owns each? What is the contract and how does it version? What happens on retry, "
        "timeout or partial failure? Where is the trust boundary?",
    },
    "AIML": {
        "title": "AI/ML",
        "sees": "Where a model genuinely helps or only adds risk: model choice, prompts, retrieval, training or fine-tuning data, "
        "evaluation, hallucination and bias, latency and cost per call, fallbacks when the model is wrong or down.",
        "asks": "Is a model needed here or would rules do? How do we measure quality? What is the ground truth? What does a wrong answer cost "
        "the user, and what is the safe fallback?",
    },
    "MLOPS": {
        "title": "MLOps",
        "sees": "Everything between a notebook and production for learned components: data and feature pipelines, versioning of data, "
        "models and prompts, experiment tracking, deployment and rollback of models, drift and quality monitoring, reproducibility.",
        "asks": "How do we reproduce this result in six months? How do we ship, canary and roll back a model? How do we notice drift or "
        "silent quality loss? Who retrains and when?",
    },
    "DEVOPS": {
        "title": "DevOps",
        "sees": "Environments, CI/CD, infrastructure as code, containers, secrets, observability (logs, metrics, traces, alerts), "
        "scaling, availability, backups, cost and security posture of the running system.",
        "asks": "How does a change get to production safely and back out again? How do we know it is broken before the user does? What are "
        "the secrets, the blast radius, the bill?",
    },
    "DATABASE": {
        "title": "Database",
        "sees": "Data model, storage engines, schemas and migrations, indexing and query shapes, consistency and transactions, "
        "retention, privacy and deletion, backups and the source of truth for each entity.",
        "asks": "What are the entities and who owns each? What queries must be fast? What must be consistent and what can be eventual? "
        "How do we migrate, back up and delete data?",
    },
}


def skill_label(skill: str) -> str:
    return SKILL_LENSES.get(skill, {}).get("title", skill.title())


def who(agent: str, roster: dict[str, str]) -> str:
    """'DEV_3 (Backend)' for display inside prompts."""
    return f"{agent} ({skill_label(roster[agent])})" if roster.get(agent) else agent


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (none)"


def context_block(inp: MeetingInput, repo_text: str) -> str:
    return (
        f"PROJECT NAME: \"{inp.project_name}\"\n\n"
        f"PROBLEM STATEMENT (from the user):\n<problem_statement>\n{inp.problem}\n</problem_statement>\n\n"
        f"USER CONSTRAINTS:\n{_bullets(inp.constraints)}\n\n"
        f"REPOSITORY CONTEXT:\n{repo_text}"
    )


# --------------------------------------------------------------------------- stage 2: blind thinking


def blind_prompt(agent_id: str, ctx: str) -> str:
    return f"""You are {agent_id}, a developer who has just joined a pod meeting. You have NOT chosen a specialism yet.
Read the problem as a thoughtful generalist engineer and think out loud on paper, alone. Nobody else's thoughts are visible to you.

{ctx}

Produce:
- understanding: in your own words, what is this project really, who is it for and what is the hard part? (3-6 sentences)
- ideas: the approaches, features or tricks that come to mind first. Be creative; include at least one unconventional idea.
- worries: what could go wrong or what looks underspecified.
- open_questions: what you would ask the user if you could.
- skill_preferences: rank ALL SIX of {', '.join(SKILL_LENSES)} by how much you would like to take that specialism for THIS problem, \
most wanted first. Choose by where you could add the most value, not by habit.

Set agent_id to "{agent_id}"."""


# --------------------------------------------------------------------------- stage 3: skill-lens proposal


def proposal_prompt(agent_id: str, skill: str, blind: BlindThoughts | None, ctx: str) -> str:
    lens = SKILL_LENSES[skill]
    earlier = (
        f"YOUR EARLIER BLIND THOUGHTS (build on them, correct them):\n{blind.model_dump_json(indent=1)}\n\n" if blind else ""
    )
    return f"""You are {agent_id} and you have taken the {lens['title']} specialism for this project.
Through your skill you see: {lens['sees']}
Questions you always ask: {lens['asks']}

{earlier}You are still preparing ALONE, before the pod talks. Re-read the problem through your skill and write the \
proposal you will bring to the table. Cover your own area in depth, but state clearly what you need from the other areas.

{ctx}

Produce your proposal:
- thesis: 2-4 sentences. Your core argument for how this should be built and why, from your skill's point of view.
- components: the major pieces in YOUR area. For each: name, approach (what it does and how), rationale (why this and not the \
obvious alternative), assumptions, risks. Be specific enough that a colleague can disagree.
- trade_offs: each significant choice with what it gains and what it costs.
- risks and assumptions: the ones that actually matter, tagged "Unknown:" where you are guessing.
- evidence: the facts (user requirements, repository observations, well-known engineering practice) behind your material claims.
- alternatives_considered: options you rejected, with the reason.
- layout_sketch: the folder structure you would propose, as a plain-text tree of AT MOST 20 lines: top-level folders and only the few files that matter, never one line per file or per screen. Flat and simple.
Every list in your answer holds at most 8 items; never enumerate names one after another.
- product_questions: ONLY questions whose answer changes product scope, user experience, budget or deadline, which an engineer \
cannot decide alone. Each needs why_it_matters, 2-4 concrete options and a recommended_default. Maximum 3.

Set agent_id to "{agent_id}"."""


# --------------------------------------------------------------------------- stage 4: the conversation

PHASE_GOALS = {
    "open": "EARLY IN THE MEETING. Read the others' proposals and react like a person in the room: credit what is strong, push on "
    "what is weak or missing, connect your area to theirs, and offer an idea that combines two people's thinking.",
    "middle": "MID-CONVERSATION. Respond to what was just said, especially anything addressed to you. Go deeper on the open threads, "
    "answer objections against you, concede when convinced and rebut with a mechanism when not. Bring in something nobody has said. "
    "Also say whether you are happy with the proposed folder structure and the architecture's components and dependencies, and what you would change.",
    "close": "THE CONVERSATION IS CONVERGING. Settle things: answer remaining objections against you, state your final position on open "
    "threads and what you need from others. Only raise a new dispute if it is critical.",
}


def phase_of(turns_taken: int, n_agents: int, max_turns: int) -> str:
    if turns_taken < n_agents:
        return "open"
    return "close" if turns_taken >= int(max_turns * 0.7) else "middle"


def transcript_text(rounds, roster: dict[str, str], limit: int = 24000) -> str:
    """Render everything said so far as a readable chat log, newest content preserved if it must be trimmed."""
    lines: list[str] = []
    for rec in rounds:
        lines.append(f"=== SCRUM CHECK-IN {rec.round} ===")
        lines.append(f"SCRUM_MASTER: {rec.note.message_to_team or rec.note.summary}")
        if rec.note.open_threads:
            lines.append("  open threads: " + "; ".join(rec.note.open_threads))
        for t in rec.turns:
            for u in t.utterances:
                lines.append(f"{who(t.agent_id, roster)} -> {u.to} [{u.kind}]: {u.text}")
            for d in rec.disputes:
                if d.source_agent == t.agent_id:
                    lines.append(
                        f"{who(t.agent_id, roster)} RAISES {d.dispute_id} [{d.severity}] against {d.target_agent}: {d.claim} | "
                        f"mechanism: {d.failure_mechanism} | counter: {d.counterproposal}"
                    )
            for r in t.responses:
                lines.append(f"{who(t.agent_id, roster)} {r.stance} {r.dispute_id}: {r.response}")
    text = "\n".join(lines)
    return text if len(text) <= limit else "...(earlier conversation trimmed)...\n" + text[-limit:]


def scrum_prompt(
    seg: int, ctx: str, proposals: dict[str, AgentProposal], roster: dict[str, str], rounds, open_disputes: list[Dispute],
    spoken: dict[str, int], max_turns: int, min_each: int, wrap_up: bool,
) -> str:
    theses = "\n".join(f"- {who(a, roster)}: {p.thesis}" for a, p in proposals.items())
    disp = "\n".join(
        f"- {d.dispute_id} [{d.severity}] {d.source_agent} -> {d.target_agent}: {d.claim}" for d in open_disputes
    ) or "- (none open)"
    counts = ", ".join(f"{a}: {n}" for a, n in spoken.items())
    if wrap_up:
        task = """The conversation is over. Write the wrap-up for the human gate:
- summary: where the pod ended up, honestly, including disagreements that remain.
- agreements: what the pod settled.
- open_threads: what is still contested or unknown.
- product_questions: the questions ONLY the human can answer (product scope, outcomes, budget, deadline, policy), gathered from the \
whole conversation and merged. Each needs why_it_matters, 2-4 distinct options and a recommended_default that is one of the options. \
Prefer 3 or fewer; never more than 5. Technical choices are not questions for the human.
- message_to_team: one short closing line."""
    elif seg == 1:
        task = """The meeting is starting. Read the proposals and:
- summary: the shape of the room: where the proposals align and where they pull apart.
- agreements: what already looks shared.
- open_threads: the 3-5 threads most worth the pod's time, each naming who should engage. One thread must be the project's folder \
structure and the shape of the architecture: compare the layout sketches in the proposals and ask who is happy with what.
- focus_next: what each thread needs resolved.
- next_speakers: developer ids you want to hear first.
- ready_to_wrap: false.
- message_to_team: your spoken opening, 3-6 sentences, addressing developers by id. Warm, direct, and pointed. Then let them talk."""
    else:
        task = f"""You are checking in on a live conversation (turns spoken so far: {counts}; the hard cap is {max_turns} turns). Read it and:
- summary: what moved, who changed their mind, what is still stuck.
- agreements: newly settled points.
- open_threads: remaining threads, each naming who should engage; add any area nobody has covered.
- focus_next: what the conversation must resolve before it can end.
- next_speakers: developer ids you want to hear from next (people who have been quiet, or whose answer is owed).
- ready_to_wrap: true ONLY when the real disagreements are settled or clearly irreducible, no CRITICAL objection is unanswered (minor \
ones may go to the decision stage), the pod has talked about the project's FOLDER STRUCTURE and the SHAPE OF THE ARCHITECTURE (main \
components and who depends on whom), nobody has a fresh angle, and every developer has spoken at least {min_each} times. Otherwise \
false, and say what is missing in focus_next. Do not end early just because the conversation is long, and do not drag it out once \
it has converged.
- message_to_team: 2-4 spoken sentences steering the next stretch, addressing developers by id."""
    return f"""You are the scrum master leading this pod.

{ctx}

THE POD (each member's thesis):
{theses}

CONVERSATION SO FAR:
{transcript_text(rounds, roster) or '(nothing yet)'}

DISPUTES STILL OPEN:
{disp}

{task}"""


def turn_prompt(
    agent_id: str, skill: str, phase: str, turns_taken: int, ctx: str, own: AgentProposal,
    proposals: dict[str, AgentProposal], roster: dict[str, str], rounds, current_note, spoken_now,
    against_me: list[Dispute], max_disputes: int,
) -> str:
    if turns_taken == 0:  # first time speaking: read everyone's full proposal; later the theses and component names are enough
        others = "\n\n".join(f"=== {who(a, roster)} ===\n{p.model_dump_json()}" for a, p in proposals.items() if a != agent_id)
    else:
        others = "\n".join(
            f"- {who(a, roster)}: {p.thesis} Components: {', '.join(c.name for c in p.components)}"
            for a, p in proposals.items() if a != agent_id
        )
    now = "\n".join(
        f"{who(t.agent_id, roster)} -> {u.to} [{u.kind}]: {u.text}" for t in spoken_now for u in t.utterances
    ) or "(nothing yet since the scrum master spoke)"
    owed = "\n".join(
        f"- {d.dispute_id} [{d.severity}/{d.category}] from {d.source_agent}: \"{d.claim}\"\n"
        f"  mechanism: {d.failure_mechanism}\n  their counterproposal: {d.counterproposal}"
        for d in against_me
    ) or "- (none)"
    colleagues = ", ".join(a for a in proposals if a != agent_id)
    return f"""You are {who(agent_id, roster)} in a live pod conversation. There are no rounds: people talk when they have something \
to say, reply to whoever just spoke, and stay quiet when they have nothing to add.

{ctx}

YOUR OWN PROPOSAL:
{own.model_dump_json()}

THE OTHERS ({'full proposals' if turns_taken == 0 else 'summaries'}):
{others}

THE CONVERSATION SO FAR:
{transcript_text(rounds, roster) or '(this is the start of the meeting)'}

THE SCRUM MASTER LAST STEERED THE ROOM WITH:
{current_note.message_to_team or current_note.summary}
  open threads: {'; '.join(current_note.open_threads) or 'none named'}
  focus: {'; '.join(current_note.focus_next) or 'none named'}

WHAT HAS BEEN SAID SINCE (most recent last):
{now}

DISPUTES AGAINST YOU THAT YOU STILL OWE AN ANSWER TO:
{owed}

{PHASE_GOALS[phase]}

It is your turn to speak. Produce:
- pass_turn: true ONLY if you honestly have nothing to add right now and owe no answer; then leave everything else empty. Do not \
pass when someone addressed you or an objection against you is waiting.
- utterances: 1-4 spoken points in your own voice. Each has to (a colleague id from {colleagues}, SCRUM_MASTER, or ALL), kind (BUILD_ON, \
CHALLENGE, REBUT, INNOVATE, AGREE, CONCEDE or QUESTION) and text (2-5 sentences, addressing the person by id and referring to what they \
actually said). Answer whoever spoke just before you if it concerns you. Do not repeat what has already been said.
- responses: one entry per dispute listed above as owed (dispute_id, stance ACCEPT/PARTIAL/REJECT, response, revised_position).
- disputes: typed objections for MATERIAL problems only, at most {max_disputes} (target_agent one of {colleagues}; claim; severity \
CRITICAL/MAJOR/NITPICK; category one of REQUIREMENT_GAP, INTEGRATION_MISMATCH, SECURITY, RELIABILITY, OVER_ENGINEERING, \
UNDER_SPECIFIED, UNTESTABLE, UNSUPPORTED_CLAIM, DATA_INTEGRITY, UX_FAILURE, OTHER; failure_mechanism; counterproposal). Do not repeat a \
dispute already in the conversation. Leave empty if there is nothing material.
- endorsements: ideas from others you want adopted, with why.
- product_questions: only if the discussion exposed a product/scope decision the human must make. Maximum 2.

Set agent_id to "{agent_id}"."""


# --------------------------------------------------------------------------- stage 5


def curation_prompt(candidates: list[tuple[str, HumanQuestion]], max_q: int, ctx: str) -> str:
    listed = "\n".join(
        f"{i + 1}. [{src}] {q.question}\n   why: {q.why_it_matters}\n   options: {q.options}\n   default: {q.recommended_default}"
        for i, (src, q) in enumerate(candidates)
    )
    return f"""You are the scrum master preparing the human decision gate. The council produced these candidate questions:

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
    skill: str,
    own: AgentProposal,
    others: dict[str, AgentProposal],
    roster: dict[str, str],
    rounds,
    disputes: list[Dispute],
    answers: list[Answer],
    internal_notes: list[str],
) -> str:
    peers = "\n".join(f"- {who(a, roster)}: {q.thesis}" for a, q in others.items() if a != agent_id) or "- (none)"
    disp = "\n".join(f"- {d.dispute_id} [{d.severity}] {d.source_agent} -> {d.target_agent}: {d.claim}" for d in disputes) or "- (none)"
    ans = "\n".join(f"- Q: {a.question}\n  A: {a.answer} ({a.source})" for a in answers) or "- (no questions were asked)"
    return f"""You are {who(agent_id, roster)}. The human has now answered the pod's questions, so the pod reconvenes to \
rethink before the scrum master decides.

YOUR OWN PROPOSAL:
{own.model_dump_json(indent=1)}

THE OTHERS' THESES:
{peers}

THE CONVERSATION YOU HAD:
{transcript_text(rounds, roster, 16000) or '(no conversation)'}

OBJECTIONS RAISED DURING THE CONVERSATION:
{disp}

THE HUMAN'S ANSWERS (authoritative):
{ans}

ASSUMPTIONS ALREADY MADE ON THE HUMAN'S BEHALF:
{_bullets(internal_notes)}

Rethink honestly, through your {skill_label(skill)} skill and as a whole-system engineer:
- answer_impact: 2-4 sentences on what each answer changes for your recommendations. If an answer invalidates something you \
proposed (scope, scale, audience), say exactly what.
- position_changes: every concrete thing you now propose differently, with the reason. Include concessions to colleagues.
- unchanged: positions you still hold despite the answers, each with a reason.
- new_conflicts: disagreements with a specific colleague that the answers created or exposed (with_agent must be one of the other \
developer ids). Do not invent conflict; leave empty if there is none.
- advice_to_arbiter: up to 4 short, specific recommendations for the scrum master's final decisions.
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
    rounds=None,
    roster: "dict[str, str] | None" = None,
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
    return f"""You are the scrum master and pod lead. The developers have talked it through, the human has answered and the pod has rethought. Synthesize the pod's work into binding decisions.{missing}

{ctx}

PROPOSALS:
{props}

THE POD'S CONVERSATION (who said what, who conceded, who held):
{transcript_text(rounds or [], roster or {}, 20000) or "(none)"}

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
- context_diagram: a Mermaid `flowchart LR` (no code fences) showing the personas/actors, the system as ONE box and any external \
systems or services it depends on. Follow the Mermaid skill rules.
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
- directory_tree: a plain-text tree of the canonical layout (├── └── │, folders end with "/"), including tests, config and docs.
- architecture_diagram: a Mermaid `flowchart TD` (no code fences) with exactly one node per component, labelled with the component \
name as written in components, arrows from the component that uses to the one it depends on. Follow the Mermaid skill rules.
- runtime_flows[].diagram: a Mermaid `sequenceDiagram` (or flowchart) for each flow, using the component names as participants.
- data_model_diagram: a Mermaid `erDiagram` when (and only when) data_entities is non-empty; otherwise an empty string.
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


# --------------------------------------------------------------------------- design review


def _design_view(spec) -> str:
    comps = "\n".join(
        f"- {c.name} @ {c.path}: {c.responsibility} (depends on: {', '.join(c.depends_on) or 'nothing'})" for c in spec.components
    )
    return f"""DIRECTORY STRUCTURE:
{spec.directory_tree.strip()}

ARCHITECTURE DIAGRAM (Mermaid):
{spec.architecture_diagram.strip()}

COMPONENTS:
{comps}"""


def design_vote_prompt(agent_id: str, skill: str, spec, roster: dict[str, str], previous: list[list], revisions: list[str]) -> str:
    lens = SKILL_LENSES[skill]
    heard = ""
    for n, votes in enumerate(previous, 1):
        lines = []
        for v in votes:
            for c in [*v.directory_changes, *v.architecture_changes]:
                lines.append(f"  {who(v.agent_id, roster)} asked: {c}")
            for u in v.discussion:
                lines.append(f"  {who(v.agent_id, roster)} -> {u.to} [{u.kind}]: {u.text}")
        if lines:
            heard += f"ROUND {n} OF THE DESIGN DISCUSSION:\n" + "\n".join(lines) + (f"\n  => the draft was then changed: {revisions[n - 1]}" if n <= len(revisions) and revisions[n - 1] else "") + "\n\n"
    colleagues = [a for a in roster if a != agent_id]
    return f"""You are {agent_id}, the {lens['title']} developer. The pod's draft project design is on the table. Look at it through your \
skill ({lens['sees']}) and say honestly whether you are OK with it.

{_design_view(spec)}

{heard}Produce your vote:
- directory_ok: true if you are happy with the folder structure as it is. If false, directory_changes must hold concrete requests \
("move X into Y", "merge A and B", "add a place for Z", "drop folder W") and why.
- architecture_ok: true if the diagram and component list are right: nothing missing, nothing unnecessary, dependencies pointing the \
right way. If false, architecture_changes must hold concrete requests.
- discussion: replies to specific colleagues about what they asked or said (to = one of {colleagues}, kind BUILD_ON/CHALLENGE/REBUT/\
AGREE/CONCEDE/QUESTION, text 1-3 sentences). Concede when a request is right; push back when it adds complexity the project does not need.
Prefer simple and flat. Do not ask for changes for taste alone. Set agent_id to "{agent_id}"."""


def design_revision_prompt(ctx: str, tech, product, requests: list[str]) -> str:
    reqs = "\n".join(f"- {r.id}: {r.title}" for r in product.requirements)
    return f"""The pod reviewed the draft directory structure and architecture and asked for these changes:
{_bullets(requests)}

Apply the ones that are sound and keep the design simple; if you decline a request, do not apply it. Return the FULL technical \
specification with only the impacted parts changed: directory_tree, components (paths must exist in directory_tree; depends_on must \
use existing component names, no cycles), architecture_diagram (one node per component, Mermaid skill rules), flow diagrams and \
anything else the change touches. Keep every requirement id as it is.

{ctx}

REQUIREMENTS (do not change):
{reqs}

CURRENT TECHNICAL SPECIFICATION:
{tech.model_dump_json(indent=1)}"""
