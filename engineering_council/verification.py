"""Deterministic cross-document consistency checks. Python, not a model, decides pass or fail."""

from __future__ import annotations

import re
from pathlib import Path

from engineering_council.models import ID_IN_TEXT, Check, Spec, VerificationReport, normalize_id
from engineering_council.storage import DOC_NAMES
from engineering_council.synthesis import find_cycles, path_in_tree

_NEGATIONS = {"no", "not", "without", "never", "non", "avoid", "exclude", "excluding"}
_FILLER = {"the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "with", "any", "full", "support", "mvp", "first", "version"}


def read_documents(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in DOC_NAMES:
        try:
            out[name] = (root / name).read_text(encoding="utf-8")
        except OSError:
            out[name] = ""
    return out


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _FILLER}


def _dupes(ids: list[str]) -> list[str]:
    return sorted({i for i in ids if ids.count(i) > 1})


def verify(spec: Spec, formal_dispute_ids: list[str], all_dispute_ids: list[str], docs: dict[str, str]) -> VerificationReport:
    checks: list[Check] = []

    def add(name: str, problems: list[str]) -> None:
        checks.append(Check(name=name, passed=not problems, details=problems))

    # 1. documents exist and are non-empty
    add("Required documents exist and are non-empty", [f"{n} is missing or empty" for n in DOC_NAMES if not docs.get(n, "").strip()])

    req_ids = [r.id for r in spec.requirements]
    ac_ids = [a.id for a in spec.acceptance_criteria]
    dec_ids = [d.decision_id for d in spec.decisions]

    # 2. identifiers are unique
    add("Identifiers are unique", [f"duplicate id {i}" for i in _dupes(req_ids) + _dupes(ac_ids) + _dupes(dec_ids)])

    # 3. acceptance criteria point at real requirements and are complete
    probs = [f"{a.id} references unknown requirement {a.requirement_id}" for a in spec.acceptance_criteria if a.requirement_id not in req_ids]
    probs += [f"{a.id} has an empty Given/When/Then" for a in spec.acceptance_criteria if not (a.given.strip() and a.when.strip() and a.then.strip())]
    add("Acceptance criteria reference existing requirements", probs)

    # 4. every in-scope functional requirement is covered
    covered = {a.requirement_id for a in spec.acceptance_criteria}
    add(
        "Every in-scope functional requirement has acceptance criteria",
        [f"{r.id} ({r.title}) has no acceptance criteria" for r in spec.requirements if r.kind == "FUNCTIONAL" and r.in_scope and r.id not in covered],
    )

    # 5. cross references between requirements, decisions, components, contracts
    probs = [f"{r.id} cites unknown decision {d}" for r in spec.requirements for d in r.decision_ids if d not in dec_ids]
    probs += [f"{d.decision_id} cites unknown requirement {x}" for d in spec.decisions for x in d.requirement_ids if x not in req_ids]
    probs += [f"component {c.name} cites unknown requirement {x}" for c in spec.components for x in c.requirement_ids if x not in req_ids]
    probs += [f"contract {k.name} cites unknown requirement {x}" for k in spec.contracts for x in k.requirement_ids if x not in req_ids]
    add("Cross-references resolve to existing ids", probs)

    # 6. disputes
    settled = {x for d in spec.decisions for x in d.dispute_ids}
    probs = [f"{x} has no decision (not resolved and not marked UNRESOLVED)" for x in formal_dispute_ids if x not in settled]
    probs += [
        f"{d.decision_id} is UNRESOLVED but missing from open questions"
        for d in spec.decisions
        if d.status == "UNRESOLVED" and not any(d.decision_id in q for q in spec.open_questions)
    ]
    add("All CRITICAL/MAJOR disputes are resolved or explicitly unresolved", probs)

    # 7. ids mentioned in prose exist
    known = set(req_ids) | set(ac_ids) | set(dec_ids) | set(all_dispute_ids)
    probs = []
    for name, text in docs.items():
        bad = sorted({normalize_id(m) for m in ID_IN_TEXT.findall(text)} - known)
        probs += [f"{name} mentions {b}, which does not exist" for b in bad]
    add("Ids mentioned in documents exist", probs)

    # 8. technology and architecture agree across documents
    tech_doc, design_doc = docs.get("Technical_Approach.md", ""), docs.get("Design.md", "")
    prd_doc = docs.get("PRD.md", "")
    probs = [f"tech choice {t.choice!r} is absent from Technical_Approach.md" for t in spec.tech_choices if t.choice.lower() not in tech_doc.lower()]
    rejected = {r.option.strip().lower() for d in spec.decisions if d.status == "DECIDED" for r in d.rejected_alternatives}
    probs += [f"tech choice {t.choice!r} is also a rejected alternative in a DECIDED decision" for t in spec.tech_choices if t.choice.strip().lower() in rejected]
    probs += [f"component {c.name} is missing from Design.md" for c in spec.components if c.name.lower() not in design_doc.lower()]
    probs += [f"component {c.name} is missing from Technical_Approach.md" for c in spec.components if c.name.lower() not in tech_doc.lower()]
    add("Technology and architecture agree across documents", probs)

    # 9. recurring paths, entities and contracts
    tree = spec.directory_tree
    probs = [f"component path {c.path!r} is not in the directory tree" for c in spec.components if c.path and not path_in_tree(c.path, tree)]
    probs += [f"contract signature {k.signature!r} missing from Design.md" for k in spec.contracts if k.signature.strip() not in design_doc]
    probs += [f"data entity {e.name} missing from Design.md" for e in spec.data_entities if e.name.lower() not in design_doc.lower()]
    probs += find_cycles({c.name: c.depends_on for c in spec.components})
    add("API paths, entities and module paths are consistent", probs)

    # 10. non-goals must not be planned features
    probs = []
    for ng in spec.non_goals:
        a = _tokens(ng) - _NEGATIONS
        if len(a) < 2:
            continue
        for r in spec.requirements:
            if not r.in_scope or _tokens(r.title) & _NEGATIONS:
                continue
            if len(a & _tokens(r.title)) / len(a) >= 0.75:
                probs.append(f"non-goal {ng!r} resembles in-scope requirement {r.id} ({r.title})")
    add("Non-goals are not described as planned features", probs)

    # 11. PRD actually lists every in-scope requirement
    add("PRD lists every in-scope requirement", [f"{r.id} missing from PRD.md" for r in spec.requirements if r.in_scope and r.id not in prd_doc])

    return VerificationReport(checks=checks)


def render_report(report: VerificationReport, notes: list[str]) -> str:
    verdict = "PASSED" if report.passed else "FAILED"
    s = f"# Verification Report\n\n**Result:** {verdict}" + ("  \n**Repair pass:** applied" if report.repaired else "") + "\n\n"
    s += "These checks are deterministic and run in Python; a language model did not decide any outcome.\n\n"
    s += "| Check | Result |\n|---|---|\n" + "".join(f"| {c.name} | {'PASS' if c.passed else 'FAIL'} |\n" for c in report.checks)
    for c in report.failures:
        s += f"\n## Failed: {c.name}\n\n" + "\n".join(f"- {d}" for d in c.details) + "\n"
    if notes:
        s += "\n## Notes from earlier stages\n\n" + "\n".join(f"- {n}" for n in notes) + "\n"
    return s
