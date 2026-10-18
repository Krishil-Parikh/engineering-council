"""Meeting orchestration: explicit stages, each persisted before the next begins."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from meetings import conversation, design_review, documents, prompts, questions, repository, synthesis, verification
from meetings import questions as _questions
from meetings.formatting import format_reconsideration
from meetings.config import Settings
from meetings.errors import MeetingError  # noqa: F401  (re-exported for the CLI and tests)
from meetings.gemini_client import LLM, AuthError, LLMError, LLMEvent, ModelError
from meetings.models import (
    AGENT_IDS,
    SCRUM_MASTER,
    Roster,
    Answer,
    AgentProposal,
    AgentReconsideration,
    AgentRebuttal,
    AgentReview,
    Decision,
    DecisionSet,
    Dispute,
    HumanQuestion,
    MeetingInput,
    QuestionCuration,
    RepoSnapshot,
    Revision,
    Spec,
    SpecDraft,
    VerificationReport,
)
from meetings.storage import MeetingStore, now_iso, write_text

TOTAL_STAGES = 10


class DisputeLedger(BaseModel):
    formal: list[Dispute]
    nitpicks: list[Dispute]
    warnings: list[str] = []


class QuestionLedger(BaseModel):
    curation: QuestionCuration
    answers: list[Answer]


class Reporter:
    """Plain terminal output. The TUI subclasses this and overrides every method to render richly."""

    def __init__(self, verbose: bool = False, out: Callable[[str], None] | None = None) -> None:
        self.verbose = verbose
        self.out = out or (lambda text: print(text, flush=True))

    def stage(self, n: int, label: str) -> None:
        self.out(f"\n[{n}/{TOTAL_STAGES}] {label}")

    def say(self, who: str, text: str) -> None:
        self.out(f"      {who}: {_clip(text, 220)}")

    def publish(self, kind: str, who: str, title: str, body: str) -> None:
        """A finished contribution (proposal, objection, rebuttal, decision). Plain mode shows the headline only."""
        self.say(who, title)

    def roster(self, skills: dict[str, str]) -> None:
        """Announce who took which skill."""
        for agent, skill in skills.items():
            self.out(f"      {agent} takes {prompts.skill_label(skill)}")

    def note(self, text: str) -> None:
        self.out(f"      {text}")

    def warn(self, text: str) -> None:
        self.out(f"      ! {text}")

    def debug(self, text: str) -> None:
        if self.verbose:
            self.out(f"      · {text}")

    def llm_event(self, ev: LLMEvent) -> None:
        """Live model activity. Plain mode only surfaces retries and failures (and everything with -v)."""
        if ev.kind in ("retry", "error") or (self.verbose and ev.kind in ("start", "done")):
            self.out(f"      · [{ev.stage}] {ev.kind}: {ev.info}")

    async def ask(self, questions: list[HumanQuestion], interactive: bool, input_fn: Callable[[str], str]) -> list[Answer]:
        return _questions.ask(questions, interactive=interactive, input_fn=input_fn, output_fn=self.out)


@dataclass
class MeetingResult:
    out_dir: Path
    report: VerificationReport
    warnings: list[str]
    decisions: list[Decision]


def _clip(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _save_usage(store: MeetingStore, llm: LLM) -> None:
    """Append this run's model-call stats to usage.json (token counts only; never prompts or keys)."""
    try:
        prior = json.loads(store.path("usage.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prior = []
    store.save("usage.json", prior + list(llm.usage))


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "meeting"


def meeting_dir(inp: MeetingInput) -> Path:
    return Path(inp.output_dir) / slugify(inp.project_name)


def load_saved_input(out_dir: Path) -> MeetingInput:
    store = MeetingStore(out_dir)
    saved = store.load("input.json", MeetingInput)
    if saved is None:
        raise MeetingError(f"{out_dir} has no readable input.json; cannot resume.")
    return saved


def input_markdown(inp: MeetingInput) -> str:
    cons = "\n".join(f"- {c}" for c in inp.constraints) or "- (none)"
    repo = inp.repo_path or inp.github_url or "(none: greenfield)"
    return f"# {inp.project_name}\n\n## Problem statement\n\n{inp.problem}\n\n## Constraints\n\n{cons}\n\n## Repository\n\n{repo}\n"


# --------------------------------------------------------------------------- the meeting


async def run_meeting(
    inp: MeetingInput,
    settings: Settings,
    llm: LLM,
    reporter: Reporter,
    *,
    interactive: bool = True,
    resume: bool = False,
    input_fn: Callable[[str], str] = input,
) -> MeetingResult:
    out_dir = meeting_dir(inp)
    if (out_dir / "meeting.json").exists() and not resume:
        raise MeetingError(f"{out_dir} already holds a meeting. Use `resume` to continue it or pick another project name.")
    store = MeetingStore(out_dir, settings.model)
    llm.observer = reporter.llm_event
    try:
        return await _run(inp, settings, llm, reporter, store, interactive, input_fn)
    except (KeyboardInterrupt, asyncio.CancelledError):
        store.finish("failed", "Interrupted by user")
        raise
    except Exception as exc:
        store.finish("failed", f"{type(exc).__name__}: {settings.redact(str(exc))}")
        raise
    finally:
        _save_usage(store, llm)


async def _run(
    inp: MeetingInput, settings: Settings, llm: LLM, rep: Reporter, store: MeetingStore,
    interactive: bool, input_fn: Callable[[str], str],
) -> MeetingResult:
    # 1 ---- inspect -------------------------------------------------------------------------
    rep.stage(1, "Inspecting repository..." if (inp.repo_path or inp.github_url) else "Preparing context (greenfield project)...")
    store.begin("inspect")
    store.save("input.json", inp)
    store.save_text("input.md", input_markdown(inp))
    snap = store.load("repo_snapshot.json", RepoSnapshot) or _inspect(inp, settings, rep, store)
    store.complete("inspect")
    ctx = prompts.context_block(inp, repository.snapshot_for_prompt(snap))

    # 2 ---- blind thinking, then every developer picks a skill ------------------------------------
    rep.stage(2, "Developers think about the problem blind, then each picks a skill...")
    store.begin("blind")
    blinds = await conversation.run_blind(llm, settings, ctx, store, rep)
    roster = conversation.load_roster(store)
    if not roster:
        roster = conversation.assign_skills(blinds, list(AGENT_IDS))
        store.save("roster.json", Roster(skills=roster))
    rep.roster(roster)
    store.complete("blind")

    # 3 ---- the same problem through each developer's skill, still alone -----------------------
    rep.stage(3, "Each developer re-thinks the problem through their skill...")
    store.begin("proposals")
    proposals, missing = await conversation.run_proposals(llm, settings, ctx, roster, blinds, store, rep)
    store.complete("proposals")

    # 4 ---- the pod talks: several rounds led by the scrum master --------------------------------
    rep.stage(4, "Pod conversation: everyone talks, challenges, rebuts and builds on each other...")
    store.begin("conversation")
    rounds, wrap, book = await conversation.run_conversation(llm, settings, ctx, proposals, roster, store, rep)
    ledger = DisputeLedger(formal=book.formal, nitpicks=book.nitpicks, warnings=list(dict.fromkeys(book.warnings)))
    store.save("disputes.json", ledger)
    reviews = conversation.reviews_from(rounds)
    rebuttals = conversation.rebuttals_from(rounds, book)
    if not ledger.formal:
        rep.note("No CRITICAL or MAJOR objections were raised.")
    store.complete("conversation")

    # 5 ---- human question gate -------------------------------------------------------------
    rep.stage(5, "Preparing product questions...")
    store.begin("questions")
    qledger = store.load("questions.json", QuestionLedger)
    if qledger is None:
        candidates = conversation.question_candidates(proposals, rounds, wrap)
        curation, note = await questions.curate(llm, candidates, settings, ctx)
        if note:
            store.warn(note)
            rep.warn(note)
        if curation.questions:
            rep.note(f"{len(curation.questions)} question(s) need your decision.")
        else:
            rep.note("No material questions; continuing without pausing.")
        answers = await rep.ask(curation.questions, interactive, input_fn)
        qledger = QuestionLedger(curation=curation, answers=answers)
        store.save("questions.json", qledger)
    store.complete("questions")

    # 6 ---- re-discussion after the human's answers -----------------------------------------
    rep.stage(6, "Everyone rethinks now that the answers are in...")
    store.begin("rediscussion")
    recon = await _reconsider(llm, settings, proposals, roster, rounds, ledger.formal, qledger, store, rep)
    store.complete("rediscussion")

    # 7 ---- decisions -----------------------------------------------------------------------
    rep.stage(7, "Resolving decisions...")
    store.begin("decisions")
    dset = store.load("decisions.json", DecisionSet)
    if dset is None:
        decisions, warns = await synthesis.decide(
            llm, ctx, proposals, reviews, ledger.formal, ledger.nitpicks, rebuttals,
            qledger.answers, qledger.curation.resolved_internally, recon, rounds, roster,
        )
        for w in warns:
            store.warn(w)
            rep.warn(w)
        dset = DecisionSet(decisions=decisions)
        store.save("decisions.json", dset)
    for d in dset.decisions:
        rep.publish("decision", SCRUM_MASTER, f"{d.decision_id} [{d.status}] {d.statement} -> {d.chosen_option}", documents.render_decision(d))
    store.complete("decisions")

    # 7 ---- specification + documents -------------------------------------------------------
    rep.stage(8, "Generating specifications...")
    store.begin("specification")
    spec = store.load("specification.json", Spec)
    if spec is None:
        spec, notes = await synthesis.build_spec(
            llm, ctx, inp.project_name, dset.decisions, qledger.answers, list(store.state.warnings)
        )
        for n in notes:
            store.warn(n)
            rep.warn(n)
        store.save("specification.json", spec)
    store.complete("specification")

    # 9 ---- design review: the pod signs off on the directory structure and the architecture ------
    rep.stage(9, "Design review: is everyone OK with the directory structure and the architecture?")
    store.begin("design_review")
    spec, design = await design_review.run_design_review(llm, settings, ctx, spec, roster, store, rep)
    write_documents(store, spec)
    store.save_text(
        "minutes.md",
        documents.render_minutes(
            inp, snap, proposals, missing, blinds, roster, rounds, wrap, ledger.formal, ledger.nitpicks, rebuttals,
            qledger.curation, qledger.answers, spec.decisions, list(store.state.warnings), recon, design,
        ),
    )
    store.complete("design_review")

    # 10 ---- verify (+ one bounded repair) ---------------------------------------------------
    rep.stage(10, "Verifying cross-document consistency...")
    store.begin("verify")
    spec, report = await verify_and_repair(store, spec, ledger, llm, settings, rep)
    store.complete("verify")
    store.finish("completed")
    rep.stage(10, "Meeting complete." if report.passed else "Meeting finished with verification failures.")
    return MeetingResult(store.root, report, list(store.state.warnings), spec.decisions)


# --------------------------------------------------------------------------- stages


def _inspect(inp: MeetingInput, settings: Settings, rep: Reporter, store: MeetingStore) -> RepoSnapshot:
    snap = RepoSnapshot()
    if inp.repo_path:
        try:
            snap = repository.inspect_local(inp.repo_path, settings)
        except FileNotFoundError as exc:
            raise MeetingError(str(exc)) from exc
    elif inp.github_url:
        snap, warning = repository.clone_github(inp.github_url, settings)
        if warning:
            store.warn(warning)
            rep.warn(warning)
    if snap.mode == "existing":
        rep.note(f"Existing project: {', '.join(snap.technologies) or 'no known manifests'}; {len(snap.tree)} files seen.")
        for w in snap.warnings[:5]:
            rep.debug(w)
        store.save("repo_snapshot.json", snap)
    else:
        rep.note("No repository context: greenfield project.")
    return snap


async def _reconsider(llm: LLM, settings: Settings, proposals: dict[str, AgentProposal], roster: dict[str, str], rounds, formal: list[Dispute], qledger, store: MeetingStore, rep: Reporter):
    """Every developer rethinks after the human's answers, with the whole conversation in front of them."""
    if not qledger.answers and not formal:
        rep.note("No answers or objections to rethink; moving on.")
        return {}
    sem = asyncio.Semaphore(settings.max_concurrency)

    async def one(agent: str) -> AgentReconsideration:
        saved = store.load(f"reconsiderations/{agent}.json", AgentReconsideration)
        if saved:
            return saved
        async with sem:
            res = await llm.generate(
                prompts.reconsideration_prompt(
                    agent, roster[agent], proposals[agent], proposals, roster, rounds, formal, qledger.answers,
                    qledger.curation.resolved_internally,
                ),
                AgentReconsideration, stage=f"rediscuss:{agent}", system=prompts.system_for("developer"),
            )
        others = set(proposals) - {agent}
        res = res.model_copy(update={"agent_id": agent, "new_conflicts": [n for n in res.new_conflicts if n.with_agent in others]})
        store.save(f"reconsiderations/{agent}.json", res)
        return res

    results = await asyncio.gather(*(one(a) for a in proposals), return_exceptions=True)
    out: dict[str, AgentReconsideration] = {}
    for agent, res in zip(proposals, results):
        if isinstance(res, (AuthError, ModelError)):
            raise MeetingError(str(res))
        if isinstance(res, BaseException):
            if isinstance(res, (KeyboardInterrupt, asyncio.CancelledError)):
                raise res
            msg = f"{agent} did not take part in the rethink: {res}"
            store.warn(msg)
            rep.warn(msg)
            continue
        out[agent] = res
        rep.publish("rediscuss", agent, f"rethought: {res.answer_impact}", format_reconsideration(res))
    return out


# --------------------------------------------------------------------------- documents + verification


def write_documents(store: MeetingStore, spec: Spec) -> None:
    store.save_text("PRD.md", documents.render_prd(spec))
    store.save_text("Technical_Approach.md", documents.render_technical(spec))
    store.save_text("Design.md", documents.render_design(spec))


def _run_checks(store: MeetingStore, spec: Spec, ledger: DisputeLedger) -> VerificationReport:
    formal_ids = [d.dispute_id for d in ledger.formal]
    all_ids = formal_ids + [d.dispute_id for d in ledger.nitpicks]
    return verification.verify(spec, formal_ids, all_ids, verification.read_documents(store.root))


async def verify_and_repair(
    store: MeetingStore, spec: Spec, ledger: DisputeLedger, llm: LLM, settings: Settings, rep: Reporter
) -> tuple[Spec, VerificationReport]:
    report = _run_checks(store, spec, ledger)
    repaired = False
    if not report.passed:
        rep.warn(f"{len(report.failures)} check(s) failed; running the single repair pass.")
        store.backup_documents()
        write_documents(store, spec)  # cheap deterministic re-render fixes missing/stale files first
        report = _run_checks(store, spec, ledger)
        if not report.passed:
            problems = [f"{c.name}: {d}" for c in report.failures for d in c.details]
            try:
                draft = await llm.generate(
                    prompts.repair_prompt(synthesis.spec_to_draft(spec), problems), SpecDraft,
                    stage="repair", system=prompts.system_for("patch", "mermaid"),
                )
                spec = synthesis.finalize_spec(
                    Spec(**draft.model_dump(), project_name=spec.project_name, decisions=[]), spec.decisions
                )
                store.save("specification.json", spec)
                write_documents(store, spec)
            except LLMError as exc:
                store.warn(f"Repair call failed: {exc}")
                rep.warn(f"Repair call failed: {exc}")
            report = _run_checks(store, spec, ledger)
        repaired = True
    report = report.model_copy(update={"repaired": repaired})
    store.save("verification_report.json", report)
    store.save_text("verification_report.md", verification.render_report(report, list(store.state.warnings)))
    for c in report.checks:
        rep.debug(f"{'PASS' if c.passed else 'FAIL'}  {c.name}")
    for c in report.failures:
        rep.warn(f"FAILED: {c.name}")
        for d in c.details[:5]:
            rep.note(f"  - {d}")
    if not report.passed:
        store.warn(f"Verification still failing after the repair pass: {[c.name for c in report.failures]}")
    return spec, report


# --------------------------------------------------------------------------- targeted revision


async def revise_meeting(out_dir: Path, feedback: str, settings: Settings, llm: LLM, rep: Reporter) -> MeetingResult:
    store = MeetingStore(out_dir, settings.model)
    spec = store.load("specification.json", Spec)
    ledger = store.load("disputes.json", DisputeLedger)
    if spec is None or ledger is None:
        raise MeetingError(f"{out_dir} has no completed specification to revise.")
    try:
        rep.stage(1, "Interpreting your feedback...")
        revision = await llm.generate(
            prompts.revision_prompt(synthesis.spec_to_draft(spec), spec.decisions, feedback), Revision,
            stage="revision", system=prompts.system_for("patch", "mermaid"),
        )
        rep.note(revision.summary)
        rep.note(f"Impacted requirements: {', '.join(revision.impacted_requirements) or 'none'}; sections: {', '.join(revision.impacted_sections) or 'none'}")
        backup = store.backup_documents()
        if backup:
            rep.note(f"Previous version saved to {backup}")
        new_spec = synthesis.finalize_spec(
            Spec(**revision.revised_spec.model_dump(), project_name=spec.project_name, decisions=[]), spec.decisions
        )
        store.save("specification.json", new_spec)
        write_documents(store, new_spec)
        rep.stage(2, "Verifying...")
        new_spec, report = await verify_and_repair(store, new_spec, ledger, llm, settings, rep)
        log = store.path("revision_log.md")
        prior = log.read_text(encoding="utf-8") if log.exists() else "# Revision log\n"
        write_text(log, prior + f"\n## {now_iso()}\n\n**Feedback:** {feedback}\n\n**Summary:** {revision.summary}\n\n"
                   f"**Impacted:** requirements {revision.impacted_requirements}, decisions {revision.impacted_decisions}, "
                   f"sections {revision.impacted_sections}\n\n**Verification:** {'passed' if report.passed else 'FAILED'}\n")
        return MeetingResult(out_dir, report, list(store.state.warnings), new_spec.decisions)
    finally:
        _save_usage(store, llm)

