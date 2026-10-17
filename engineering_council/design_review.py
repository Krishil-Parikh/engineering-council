"""Design review: the pod looks at the drafted directory structure and architecture diagram, objects, talks it through and signs off."""

from __future__ import annotations

import asyncio

from engineering_council import prompts, synthesis
from engineering_council.config import Settings
from engineering_council.errors import MeetingError
from engineering_council.gemini_client import LLM, AuthError, LLMError, ModelError
from engineering_council.models import DesignReview, DesignVote, Spec, TechnicalSpec
from engineering_council.storage import MeetingStore


def describe_change(old: Spec, new: Spec) -> str:
    """A short factual summary of how a revision changed the layout and component list."""
    old_lines = {ln.strip() for ln in old.directory_tree.splitlines() if ln.strip()}
    new_lines = {ln.strip() for ln in new.directory_tree.splitlines() if ln.strip()}
    old_c, new_c = {c.name for c in old.components}, {c.name for c in new.components}
    parts = []
    if old_lines != new_lines:
        parts.append(f"directory tree: {len(new_lines - old_lines)} entries added, {len(old_lines - new_lines)} removed")
    if old_c != new_c:
        parts.append(f"components: +{sorted(new_c - old_c) or '[]'} -{sorted(old_c - new_c) or '[]'}")
    if old.architecture_diagram.strip() != new.architecture_diagram.strip() and not parts:
        parts.append("architecture diagram redrawn")
    return "; ".join(parts) or "wording only"


def requests_from(votes: list[DesignVote]) -> list[str]:
    out = []
    for v in votes:
        out += [f"{v.agent_id} (directory): {c}" for c in v.directory_changes if c.strip()]
        out += [f"{v.agent_id} (architecture): {c}" for c in v.architecture_changes if c.strip()]
    return out


async def _round(llm: LLM, settings: Settings, rnd: int, spec: Spec, roster: dict[str, str], review_so_far: DesignReview, store: MeetingStore, rep) -> list[DesignVote]:
    sem = asyncio.Semaphore(settings.max_concurrency)
    agents = list(roster)

    async def one(agent: str) -> DesignVote:
        saved = store.load(f"design_review/round{rnd}-{agent}.json", DesignVote)
        if saved:
            return saved
        async with sem:
            vote = await llm.generate(
                prompts.design_vote_prompt(agent, roster[agent], spec, roster, review_so_far.rounds, review_so_far.revisions),
                DesignVote, stage=f"design{rnd}:{agent}", system=prompts.system_for("developer", "mermaid"),
            )
        others = set(roster) - {agent}
        vote = vote.model_copy(update={
            "agent_id": agent,
            "directory_ok": vote.directory_ok and not vote.directory_changes,
            "architecture_ok": vote.architecture_ok and not vote.architecture_changes,
            "discussion": [u for u in vote.discussion if u.to in others | {"ALL"}],
        })
        store.save(f"design_review/round{rnd}-{agent}.json", vote)
        return vote

    results = await asyncio.gather(*(one(a) for a in agents), return_exceptions=True)
    votes: list[DesignVote] = []
    for agent, res in zip(agents, results):
        if isinstance(res, (AuthError, ModelError)):
            raise MeetingError(str(res))
        if isinstance(res, BaseException):
            if isinstance(res, (KeyboardInterrupt, asyncio.CancelledError)):
                raise res
            msg = f"{agent} did not vote on the design: {res}"
            store.warn(msg)
            rep.warn(msg)
            continue
        votes.append(res)
        who = prompts.who(agent, roster)
        for c in res.directory_changes:
            rep.publish("talk", agent, f"[directory] {c}", f"{who} on the directory structure [REQUEST]\n{c}")
        for c in res.architecture_changes:
            rep.publish("talk", agent, f"[architecture] {c}", f"{who} on the architecture [REQUEST]\n{c}")
        for u in res.discussion:
            rep.publish("talk", agent, f"to {u.to} [{u.kind}] {u.text}", f"{who} to {u.to} [{u.kind}]\n{u.text}")
        if res.directory_ok and res.architecture_ok:
            rep.publish("talk", agent, "happy with the design", f"{who} on the design [APPROVE]\nI am OK with the directory structure and the architecture.")
    return votes


async def run_design_review(
    llm: LLM, settings: Settings, ctx: str, spec: Spec, roster: dict[str, str], store: MeetingStore, rep
) -> tuple[Spec, DesignReview]:
    saved = store.load("design_review.json", DesignReview)
    if saved:
        return spec, saved
    review = DesignReview()
    for rnd in range(1, settings.design_review_rounds + 1):
        votes = await _round(llm, settings, rnd, spec, roster, review, store, rep)
        review.rounds.append(votes)
        asks = requests_from(votes)
        if not asks:
            rep.note(f"Round {rnd}: everyone who voted is happy with the directory structure and architecture.")
            review.revisions.append("")
            review.agreed = True
            break
        rep.note(f"Round {rnd}: {len(asks)} change request(s) on the design.")
        if rnd == settings.design_review_rounds:
            review.revisions.append("")
            review.agreed = False
            msg = "Design review ended with open requests: " + "; ".join(asks[:6])
            store.warn(msg)
            rep.warn(msg)
            break
        try:
            tech, errs = await synthesis._generate_checked(
                llm, prompts.design_revision_prompt(ctx, synthesis.technical_of(spec), synthesis.product_of(spec), asks), TechnicalSpec,
                lambda t: synthesis.validate_technical(t, {r.id for r in spec.requirements}), f"design{rnd}:revise",
                prompts.system_for("arbiter", "mermaid"),
            )
        except (AuthError, ModelError) as exc:
            raise MeetingError(str(exc)) from exc
        except LLMError as exc:
            msg = f"Could not apply the design requests: {exc}"
            store.warn(msg)
            rep.warn(msg)
            review.revisions.append("")
            review.agreed = False
            break
        if errs:
            tech = synthesis.sanitize_technical(tech, {r.id for r in spec.requirements})
        new = synthesis.assemble(synthesis.product_of(spec), tech, spec.project_name, spec.decisions)
        change = describe_change(spec, new)
        review.revisions.append(change)
        rep.note(f"The design was revised ({change}).")
        spec = new
        store.save("specification.json", spec)
        review.agreed = True
    store.save("design_review.json", review)
    return spec, review
