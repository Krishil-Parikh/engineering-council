"""Readable plain-text renderings of meeting contributions, for the TUI feed and the minutes."""

from __future__ import annotations

from meetings.models import AgentProposal, AgentReview, Dispute, RebuttalItem


def _lines(title: str, items: list[str]) -> str:
    if not items:
        return ""
    return f"{title}\n" + "\n".join(f"  - {i}" for i in items) + "\n\n"


def format_proposal(p: AgentProposal) -> str:
    out = f"THESIS\n{p.thesis}\n\nCOMPONENTS\n"
    out += "\n".join(f"  - {c.name}: {c.approach}\n      why: {c.rationale}" for c in p.components) + "\n\n"
    out += _lines("TRADE-OFFS", [f"{t.choice} (gains: {t.gain}; costs: {t.cost})" for t in p.trade_offs])
    out += _lines("RISKS", p.risks) + _lines("ASSUMPTIONS", p.assumptions) + _lines("EVIDENCE", p.evidence)
    out += _lines("ALTERNATIVES CONSIDERED", p.alternatives_considered)
    out += _lines("QUESTIONS FOR THE HUMAN", [q.question for q in p.product_questions])
    return out.strip()


def format_dispute(d: Dispute) -> str:
    out = (
        f"{d.dispute_id}  {d.severity}  [{d.category}]\n{d.source_agent} -> {d.target_agent}\n\n"
        f"CLAIM\n{d.claim}\n\nHOW IT FAILS\n{d.failure_mechanism}\n\nCOUNTERPROPOSAL\n{d.counterproposal}\n"
    )
    if d.conditions:
        out += "\nMATTERS WHEN\n" + "\n".join(f"  - {c}" for c in d.conditions) + "\n"
    return out.strip()


def format_review(r: AgentReview) -> str:
    out = f"{r.summary}\n\n" if r.summary else ""
    if r.no_material_objection and not r.disputes:
        out += "NO MATERIAL OBJECTION\n\n"
    out += _lines("WANTS ADOPTED FROM OTHERS", r.endorsements)
    out += "\n\n".join(format_dispute(d.model_copy(update={"source_agent": r.agent_id})) for d in r.disputes)
    return out.strip()


def format_rebuttal(r: RebuttalItem) -> str:
    return f"{r.stance} {r.dispute_id}\n{r.response}\nRevised position: {r.revised_position or '(none)'}"


def format_reconsideration(r) -> str:
    lines = [f"Impact of the answers: {r.answer_impact or '(none stated)'}"]
    for c in r.position_changes:
        lines.append(f"CHANGED {c.topic}: {c.change} (because {c.reason})")
    for u in r.unchanged:
        lines.append(f"HELD {u}")
    for n in r.new_conflicts:
        lines.append(f"CONFLICT with {n.with_agent}: {n.issue} (my position: {n.my_position})")
    for a in r.advice_to_arbiter:
        lines.append(f"ADVICE {a}")
    return "\n".join(lines)


def format_blind(b) -> str:
    out = f"UNDERSTANDING\n{b.understanding}\n\n" + _lines("IDEAS", b.ideas) + _lines("WORRIES", b.worries)
    out += _lines("WOULD ASK THE USER", b.open_questions) + _lines("SKILLS THE PROBLEM NEEDS (most important first)", b.skills_needed)
    out += _lines("SKILL PREFERENCE (most wanted first)", b.skill_preferences)
    return out.strip()


def format_scrum(n) -> str:
    out = f"{n.message_to_team}\n\n" if n.message_to_team else ""
    out += f"SUMMARY\n{n.summary}\n\n" + _lines("SETTLED", n.agreements) + _lines("STILL OPEN", n.open_threads)
    out += _lines("FOCUS NEXT", n.focus_next) + _lines("QUESTIONS FOR THE HUMAN", [q.question for q in n.product_questions])
    return out.strip()
