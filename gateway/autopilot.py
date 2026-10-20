"""The autopilot Business SME: an option for when nobody is at the screen.

It answers the PRODUCT QUESTIONS the pod asks during a meeting, in the voice of the person who owns the brief, and it says so in the record (`source: autopilot`). It never
approves anything: the first documents, and every decision that needs approval, wait for the human whatever the mode. Switching back to the human is one click and takes
effect at once: a question still waiting is no longer answered for them."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel

from gateway.logs import one_line

if TYPE_CHECKING:
    from gateway.runner import WorkspaceRun

log = logging.getLogger("gateway.autopilot")

SYSTEM = (
    "You are the Business SME of this project: the person who owns the brief and answers the team's product questions. You are decisive and brief. "
    "You hold to the brief and its constraints. When the question is about scope the brief does not ask for, choose the smaller scope. "
    "You prefer the recommended default unless it contradicts the brief. You never approve documents or designs: you only answer questions."
)


class SmeAnswer(BaseModel):
    answer: str
    reasoning: str = ""


def prompt_for(run: "WorkspaceRun", text: str, context: str, options: list[str], recommended: Optional[str]) -> str:
    constraints = "\n".join(f"- {c}" for c in getattr(run, "constraints", []) or []) or "(none)"
    decided = "\n".join(f"- {t}" for t in getattr(run, "autopilot_log", [])[-12:]) or "(nothing yet)"
    choices = "\n".join(f"- {o}{'  (recommended default)' if o == recommended else ''}" for o in options) or "(free answer)"
    return (
        f"PROJECT: {run.project_name}\n\nTHE BRIEF (yours):\n<brief>\n{getattr(run, 'brief', '')}\n</brief>\n\nCONSTRAINTS:\n{constraints}\n\n"
        f"WHAT YOU ALREADY ANSWERED THIS MEETING:\n{decided}\n\nTHE TEAM ASKS:\n{text}\n\nWHY IT MATTERS:\n{context}\n\nOPTIONS:\n{choices}\n\n"
        "Answer the question. If it has options, `answer` is exactly one of them (or a short custom answer if none fits). `reasoning` is one sentence a reader can check."
    )


def pick(answer: str, options: list[str]) -> str:
    """The option the answer names (exactly as written in the options), else the answer as given."""
    plain = answer.strip()
    for option in options:
        if plain.lower() == option.strip().lower():
            return option
    return plain


async def answer_later(run: "WorkspaceRun", qid: str, text: str, context: str, options: list[str], recommended: Optional[str]) -> None:
    await asyncio.sleep(max(0.0, float(getattr(run.settings, "autopilot_delay", 3.0))))  # a moment in which the human can still take over
    if qid not in run.questions.pending or not run.standup.autopilot:
        return
    chosen: Optional[str] = None
    try:
        settings = run.deps.meeting_settings()
        llm = run.deps.meeting_llm(settings)
        result = await asyncio.wait_for(llm.generate(prompt_for(run, text, context, options, recommended), SmeAnswer, stage="sme:SME", system=SYSTEM), timeout=120)
        chosen = pick(result.answer, options) if result.answer.strip() else None
        if chosen:
            log.info("autopilot SME answered [%s]: %s  (%s)", qid, one_line(chosen, 100), one_line(result.reasoning, 120))
    except Exception as exc:  # noqa: BLE001 - the recommended default is a fair answer when the model is not available
        log.warning("autopilot SME could not ask the model (%s); using the recommended default", one_line(str(exc), 120))
    chosen = chosen or recommended
    if not chosen:
        log.warning("autopilot SME has nothing to answer [%s] (no default); it waits for you", qid)
        return
    if qid not in run.questions.pending or not run.standup.autopilot:  # the human took over while the model was thinking
        return
    run.standup.autopilot_answers.add(qid)
    run.autopilot_log = (getattr(run, "autopilot_log", []) + [f"{one_line(text, 100)} -> {one_line(chosen, 100)}"])[-40:]
    run.questions.answer(chosen, qid)


def on_question(run: "WorkspaceRun", qid: str, kind: str, text: str, context: str, options: list[str], recommended: Optional[str]) -> None:
    """Called whenever the human is asked something. Only a product question is ever handed to the autopilot."""
    if kind == "meeting" and run.standup.autopilot:
        run.spawn(answer_later(run, qid, text, context, options, recommended))
