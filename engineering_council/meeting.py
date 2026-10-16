"""Meeting orchestration: explicit stages, each persisted before the next begins."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from engineering_council import documents, prompts, questions, repository, synthesis, verification
from engineering_council.config import Settings
from engineering_council.gemini_client import LLM, AuthError, LLMError, ModelError
from engineering_council.models import (
    AGENT_IDS,
    Answer,
    AgentProposal,
    AgentRebuttal,
    AgentReview,
    Decision,
    DecisionSet,
    Dispute,
    MeetingInput,
    QuestionCuration,
    RepoSnapshot,
    Revision,
    Spec,
    SpecDraft,
    VerificationReport,
)
from engineering_council.storage import MeetingStore, now_iso, write_text

TOTAL_STAGES = 8


class MeetingError(Exception):
    """An expected, user-presentable meeting failure. Completed artifacts are preserved on disk."""


class DisputeLedger(BaseModel):
    formal: list[Dispute]
    nitpicks: list[Dispute]
    warnings: list[str] = []


class QuestionLedger(BaseModel):
    curation: QuestionCuration
    answers: list[Answer]


class Reporter:
    """Terminal output. Concise by default; the 'meeting feed' lines make the discussion visible."""

    def __init__(self, verbose: bool = False, out: Callable[[str], None] = print) -> None:
        self.verbose, self.out = verbose, out

    def stage(self, n: int, label: str) -> None:
        self.out(f"\n[{n}/{TOTAL_STAGES}] {label}")

    def say(self, who: str, text: str) -> None:
        self.out(f"      {who}: {_clip(text, 220)}")

    def note(self, text: str) -> None:
        self.out(f"      {text}")

    def warn(self, text: str) -> None:
        self.out(f"      ! {text}")

    def debug(self, text: str) -> None:
        if self.verbose:
            self.out(f"      · {text}")


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

    # 2 ---- independent proposals -----------------------------------------------------------
    rep.stage(2, "Generating independent proposals (four members prepare alone)...")
    store.begin("proposals")
    proposals, missing = await _proposals(llm, settings, ctx, store, rep)
    store.complete("proposals")

    # 3 ---- adversarial review --------------------------------------------------------------
    rep.stage(3, "Reviewing proposals...")
    store.begin("review")
    reviews = await _reviews(llm, settings, ctx, proposals, store, rep)
    ledger = store.load("disputes.json", DisputeLedger)
    if ledger is None:
        formal, nitpicks, warns = synthesis.collect_disputes(reviews, settings)
        ledger = DisputeLedger(formal=formal, nitpicks=nitpicks, warnings=warns)
        store.save("disputes.json", ledger)
        for w in warns:
            store.warn(w)
    for d in ledger.formal:
        rep.say(d.source_agent, f"{d.severity} objection to {d.target_agent} ({d.dispute_id}): {d.claim}")
    if not ledger.formal:
        rep.note("No CRITICAL or MAJOR objections were raised.")
    if ledger.nitpicks:
        rep.debug(f"{len(ledger.nitpicks)} nitpick(s) retained in the record, not blocking.")
    store.complete("review")

    # 4 ---- rebuttals -----------------------------------------------------------------------
    rep.stage(4, "Hearing rebuttals...")
    store.begin("rebuttal")
    rebuttals = await _rebuttals(llm, settings, proposals, ledger.formal, store, rep)
    store.complete("rebuttal")

    # 5 ---- human question gate -------------------------------------------------------------
    rep.stage(5, "Preparing product questions...")
    store.begin("questions")
    qledger = store.load("questions.json", QuestionLedger)
    if qledger is None:
        candidates = [(a, q) for a, p in proposals.items() for q in p.product_questions]
        candidates += [(a, q) for a, r in reviews.items() for q in r.product_questions]
        curation, note = await questions.curate(llm, candidates, settings, ctx)
        if note:
            store.warn(note)
            rep.warn(note)
        if curation.questions:
            rep.note(f"{len(curation.questions)} question(s) need your decision.")
        else:
            rep.note("No material questions; continuing without pausing.")
        answers = questions.ask(curation.questions, interactive=interactive, input_fn=input_fn, output_fn=rep.out)
        qledger = QuestionLedger(curation=curation, answers=answers)
        store.save("questions.json", qledger)
    store.complete("questions")

    # 6 ---- decisions -----------------------------------------------------------------------
    rep.stage(6, "Resolving decisions...")
    store.begin("decisions")
    dset = store.load("decisions.json", DecisionSet)
    if dset is None:
        decisions, warns = await synthesis.decide(
            llm, ctx, proposals, reviews, ledger.formal, ledger.nitpicks, rebuttals,
            qledger.answers, qledger.curation.resolved_internally,
        )
        for w in warns:
            store.warn(w)
            rep.warn(w)
        dset = DecisionSet(decisions=decisions)
        store.save("decisions.json", dset)
    for d in dset.decisions:
        rep.say(d.decision_id, f"[{d.status}] {d.statement} -> {d.chosen_option}")
    store.complete("decisions")

    # 7 ---- specification + documents -------------------------------------------------------
    rep.stage(7, "Generating specifications...")
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
    write_documents(store, spec)
    store.save_text(
        "minutes.md",
        documents.render_minutes(
            inp, snap, proposals, missing, reviews, ledger.formal, ledger.nitpicks, rebuttals,
            qledger.curation, qledger.answers, spec.decisions, list(store.state.warnings),
        ),
    )
    store.complete("specification")

    # 8 ---- verify (+ one bounded repair) ---------------------------------------------------
    rep.stage(8, "Verifying cross-document consistency...")
    store.begin("verify")
    spec, report = await verify_and_repair(store, spec, ledger, llm, settings, rep)
    store.complete("verify")
    store.finish("completed")
    rep.stage(8, "Meeting complete." if report.passed else "Meeting finished with verification failures.")
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


async def _proposals(llm: LLM, settings: Settings, ctx: str, store: MeetingStore, rep: Reporter):
    sem = asyncio.Semaphore(settings.max_concurrency)

    async def one(agent: str) -> AgentProposal:
        saved = store.load(f"proposals/{agent}.json", AgentProposal)
        if saved:
            return saved
        async with sem:
            prop = await llm.generate(
                prompts.proposal_prompt(agent, ctx), AgentProposal,
                stage=f"proposal:{agent}", system=prompts.system_for(agent),
            )
        prop = prop.model_copy(update={"agent_id": agent})
        store.save(f"proposals/{agent}.json", prop)  # saved the moment it finishes, even if siblings fail
        return prop

    results = await asyncio.gather(*(one(a) for a in AGENT_IDS), return_exceptions=True)
    proposals: dict[str, AgentProposal] = {}
    missing: list[str] = []
    for agent, res in zip(AGENT_IDS, results):
        if isinstance(res, (AuthError, ModelError)):
            raise MeetingError(str(res))
        if isinstance(res, BaseException):
            if isinstance(res, (KeyboardInterrupt, asyncio.CancelledError)):
                raise res
            missing.append(agent)
            msg = f"{agent} did not contribute a proposal: {res}"
            store.warn(msg)
            rep.warn(msg)
        else:
            proposals[agent] = res
            rep.say(agent, res.thesis)
    if len(proposals) < settings.min_quorum:
        raise MeetingError(
            f"Only {len(proposals)} of {len(AGENT_IDS)} proposals succeeded (quorum is {settings.min_quorum}). "
            f"Completed proposals are saved in {store.root / 'proposals'}; fix the cause and `resume`."
        )
    if missing:
        store.warn(f"Council ran without: {', '.join(missing)}.")
    return proposals, missing


async def _reviews(llm: LLM, settings: Settings, ctx: str, proposals: dict[str, AgentProposal], store: MeetingStore, rep: Reporter):
    sem = asyncio.Semaphore(settings.max_concurrency)

    async def one(agent: str) -> AgentReview:
        saved = store.load(f"reviews/{agent}.json", AgentReview)
        if saved:
            return saved
        others = {a: p for a, p in proposals.items() if a != agent}
        prompt = prompts.review_prompt(agent, ctx, proposals[agent], others).replace("{max_disputes}", str(settings.max_disputes_per_reviewer))
        async with sem:
            rev = await llm.generate(prompt, AgentReview, stage=f"review:{agent}", system=prompts.system_for(agent, "review"))
        rev = rev.model_copy(update={"agent_id": agent})
        store.save(f"reviews/{agent}.json", rev)
        return rev

    results = await asyncio.gather(*(one(a) for a in proposals), return_exceptions=True)
    reviews: dict[str, AgentReview] = {}
    for agent, res in zip(proposals, results):
        if isinstance(res, (AuthError, ModelError)):
            raise MeetingError(str(res))
        if isinstance(res, BaseException):
            if isinstance(res, (KeyboardInterrupt, asyncio.CancelledError)):
                raise res
            msg = f"{agent} did not complete a review: {res}"
            store.warn(msg)
            rep.warn(msg)
        else:
            reviews[agent] = res
            if res.summary:
                rep.say(agent, res.summary)
    if not reviews:
        raise MeetingError("No reviews completed; refusing to synthesize without any adversarial review.")
    return reviews


async def _rebuttals(llm: LLM, settings: Settings, proposals: dict[str, AgentProposal], formal: list[Dispute], store: MeetingStore, rep: Reporter):
    sem = asyncio.Semaphore(settings.max_concurrency)
    targets = {a: [d for d in formal if d.target_agent == a] for a in proposals}
    targets = {a: ds for a, ds in targets.items() if ds}

    async def one(agent: str) -> AgentRebuttal:
        saved = store.load(f"rebuttals/{agent}.json", AgentRebuttal)
        if saved:
            return saved
        async with sem:
            reb = await llm.generate(
                prompts.rebuttal_prompt(agent, proposals[agent], targets[agent]), AgentRebuttal,
                stage=f"rebuttal:{agent}", system=prompts.system_for(agent),
            )
        valid = {d.dispute_id for d in targets[agent]}
        reb = reb.model_copy(update={"agent_id": agent, "responses": [r for r in reb.responses if r.dispute_id in valid]})
        store.save(f"rebuttals/{agent}.json", reb)
        return reb

    if not targets:
        rep.note("Nothing to rebut.")
        return {}
    results = await asyncio.gather(*(one(a) for a in targets), return_exceptions=True)
    out: dict[str, AgentRebuttal] = {}
    for agent, res in zip(targets, results):
        if isinstance(res, (AuthError, ModelError)):
            raise MeetingError(str(res))
        if isinstance(res, BaseException):
            if isinstance(res, (KeyboardInterrupt, asyncio.CancelledError)):
                raise res
            msg = f"{agent} did not answer the objections against them: {res}"
            store.warn(msg)
            rep.warn(msg)
            continue
        out[agent] = res
        for r in res.responses:
            rep.say(agent, f"{r.stance} {r.dispute_id}: {r.response}")
        answered = {r.dispute_id for r in res.responses}
        for d in targets[agent]:
            if d.dispute_id not in answered:
                store.warn(f"{agent} left {d.dispute_id} unanswered.")
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
                    stage="repair", system=prompts.system_for("patch"),
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
            stage="revision", system=prompts.system_for("patch"),
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
