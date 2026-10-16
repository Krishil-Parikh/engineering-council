"""Human question gate: dedupe, curate, hard-cap in Python, then ask one question at a time."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Callable

from engineering_council import prompts
from engineering_council.config import Settings
from engineering_council.gemini_client import LLM, LLMError
from engineering_council.models import Answer, HumanQuestion, QuestionCuration

_STOP = {"the", "a", "an", "to", "of", "for", "and", "or", "is", "be", "should", "must", "does", "do", "will", "we", "it", "in", "on", "support"}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP}


def similar(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    jaccard = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    ratio = SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()
    return jaccard >= 0.7 or ratio >= 0.92


def sanitize(q: HumanQuestion) -> HumanQuestion | None:
    """Make a question answerable: >=2 distinct options and a default that is one of them."""
    options: list[str] = []
    for o in q.options:
        o = o.strip()
        if o and o.lower() not in {x.lower() for x in options}:
            options.append(o)
    default = q.recommended_default.strip()
    if not q.question.strip():
        return None
    if default and default.lower() not in {x.lower() for x in options}:
        options.append(default)
    if not default and options:
        default = options[0]
    if len(options) < 2:
        return None
    # snap the default onto the exact option text
    default = next(x for x in options if x.lower() == default.lower())
    return q.model_copy(update={"options": options[:5], "recommended_default": default})


def dedupe(questions: list[HumanQuestion]) -> list[tuple[HumanQuestion, int]]:
    """Merge near-duplicates. Returns (question, how_many_agents_raised_it), most-raised first."""
    groups: list[list[HumanQuestion]] = []
    for q in questions:
        for g in groups:
            if similar(g[0].question, q.question):
                g.append(q)
                break
        else:
            groups.append([q])
    ranked = [(g[0], len(g)) for g in groups]
    return sorted(ranked, key=lambda t: -t[1])  # sorted() is stable: ties keep original order


def finalize(questions: list[HumanQuestion], limit: int) -> list[HumanQuestion]:
    """Deterministic cap. The model cannot be trusted to obey the limit."""
    clean = [s for q in questions if (s := sanitize(q))]
    return [q for q, _ in dedupe(clean)][:limit]


async def curate(
    llm: LLM, candidates: list[tuple[str, HumanQuestion]], settings: Settings, ctx: str
) -> tuple[QuestionCuration, str]:
    """Return (curation, note). Falls back to deterministic selection if the model call fails."""
    if not candidates:
        return QuestionCuration(), ""
    pre = dedupe([q for _, q in candidates])
    try:
        result = await llm.generate(
            prompts.curation_prompt(candidates, settings.max_questions, ctx),
            QuestionCuration,
            stage="question_curation",
            system=prompts.system_for("curator"),
        )
        note = ""
    except LLMError as exc:
        result = QuestionCuration(questions=[q for q, _ in pre])
        note = f"Question curation call failed ({exc}); used deterministic dedupe instead."
    result.questions = finalize(result.questions, settings.max_questions)
    return result, note


def ask(
    questions: list[HumanQuestion],
    interactive: bool = True,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> list[Answer]:
    answers: list[Answer] = []
    total = len(questions)
    for i, q in enumerate(questions, 1):
        if not interactive:
            answers.append(Answer(question=q.question, answer=q.recommended_default, source="non_interactive_default"))
            continue
        output_fn(f"\nQuestion {i}/{total}: {q.question}")
        output_fn(f"  Why it matters: {q.why_it_matters}")
        for n, opt in enumerate(q.options, 1):
            tag = "  (recommended)" if opt == q.recommended_default else ""
            output_fn(f"  [{n}] {opt}{tag}")
        custom = len(q.options) + 1
        output_fn(f"  [{custom}] Custom answer   [Enter] Accept default: {q.recommended_default}")
        answers.append(_prompt_one(q, custom, input_fn, output_fn))
    return answers


def _prompt_one(q: HumanQuestion, custom: int, input_fn: Callable[[str], str], output_fn: Callable[[str], None]) -> Answer:
    for _ in range(3):
        try:
            raw = input_fn("  Choose: ").strip()
        except EOFError:
            break
        if raw == "":
            break
        if raw.isdigit() and 1 <= int(raw) <= len(q.options):
            return Answer(question=q.question, answer=q.options[int(raw) - 1], source="option")
        if raw.isdigit() and int(raw) == custom:
            try:
                text = input_fn("  Your answer: ").strip()
            except EOFError:
                break
            if text:
                return Answer(question=q.question, answer=text, source="custom")
            break
        output_fn(f"  Please enter 1-{custom} or press Enter for the default.")
    return Answer(question=q.question, answer=q.recommended_default, source="default")
