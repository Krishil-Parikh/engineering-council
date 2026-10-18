"""The pod conversation: blind thinking, skill picking, skill-lens proposals, then rounds of real talk led by a scrum master."""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from meetings import prompts
from meetings.config import Settings
from meetings.errors import MeetingError
from meetings.formatting import format_blind, format_dispute, format_proposal, format_rebuttal, format_scrum
from meetings.gemini_client import LLM, AuthError, ModelError
from meetings.models import (
    AGENT_IDS,
    SCRUM_MASTER,
    SKILLS,
    AgentProposal,
    AgentRebuttal,
    AgentReview,
    AgentTurn,
    BlindThoughts,
    Dispute,
    HumanQuestion,
    RoundRecord,
    Roster,
    ScrumNote,
)
from meetings.questions import similar
from meetings.storage import MeetingStore

SEVERITY_ORDER = {"CRITICAL": 0, "MAJOR": 1, "NITPICK": 2}
_ALIASES = {
    "AI": "AIML", "ML": "AIML", "AI/ML": "AIML", "AI ML": "AIML", "AI_ML": "AIML", "MACHINE LEARNING": "AIML",
    "ML OPS": "MLOPS", "ML_OPS": "MLOPS", "ML-OPS": "MLOPS", "DEV OPS": "DEVOPS", "DEV_OPS": "DEVOPS", "DEV-OPS": "DEVOPS",
    "DB": "DATABASE", "DATA": "DATABASE", "FRONT END": "FRONTEND", "FRONT-END": "FRONTEND", "UI": "FRONTEND",
    "BACK END": "BACKEND", "BACK-END": "BACKEND", "SERVER": "BACKEND", "INFRA": "DEVOPS", "INFRASTRUCTURE": "DEVOPS",
}


def _fatal(exc: BaseException) -> bool:
    return isinstance(exc, (AuthError, ModelError))


def _interrupt(exc: BaseException) -> bool:
    return isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError))


def normalize_skill(value: str) -> str | None:
    v = " ".join(str(value).upper().replace(".", " ").split())
    v = _ALIASES.get(v, v)
    return v if v in SKILLS else None


# --------------------------------------------------------------------------- skill picking


def assign_skills(blinds: dict[str, BlindThoughts], agents: list[str]) -> dict[str, str]:
    """Each developer takes the highest-ranked skill nobody has taken yet. Developers who stated no preference take what is left."""
    taken: set[str] = set()
    roster: dict[str, str] = {}
    for agent in agents:
        ranked = [s for s in (normalize_skill(x) for x in (blinds[agent].skill_preferences if agent in blinds else [])) if s]
        pick = next((s for s in ranked if s not in taken), None)
        if pick is None:
            pick = next((s for s in SKILLS if s not in taken), None)
        if pick is None:  # more developers than skills: share the first skill
            pick = SKILLS[len(roster) % len(SKILLS)]
        taken.add(pick)
        roster[agent] = pick
    return roster


# --------------------------------------------------------------------------- phase 1: blind thinking


async def run_blind(llm: LLM, settings: Settings, ctx: str, store: MeetingStore, rep: Any) -> dict[str, BlindThoughts]:
    """Best effort: a developer who fails to think blind still joins the meeting."""
    sem = asyncio.Semaphore(settings.max_concurrency)

    async def one(agent: str) -> BlindThoughts:
        saved = store.load(f"blind/{agent}.json", BlindThoughts)
        if saved:
            return saved
        async with sem:
            res = await llm.generate(prompts.blind_prompt(agent, ctx), BlindThoughts, stage=f"blind:{agent}", system=prompts.system_for("developer"))
        res = res.model_copy(update={"agent_id": agent})
        store.save(f"blind/{agent}.json", res)
        return res

    results = await asyncio.gather(*(one(a) for a in AGENT_IDS), return_exceptions=True)
    out: dict[str, BlindThoughts] = {}
    for agent, res in zip(AGENT_IDS, results):
        if _fatal(res):
            raise MeetingError(str(res))
        if isinstance(res, BaseException):
            if _interrupt(res):
                raise res
            msg = f"{agent} could not think blind ({res}); they join without a first take."
            store.warn(msg)
            rep.warn(msg)
            continue
        out[agent] = res
        rep.publish("blind", agent, res.understanding, format_blind(res))
    return out


# --------------------------------------------------------------------------- phase 2: skill-lens proposals


async def run_proposals(
    llm: LLM, settings: Settings, ctx: str, roster: dict[str, str], blinds: dict[str, BlindThoughts], store: MeetingStore, rep: Any
) -> tuple[dict[str, AgentProposal], list[str]]:
    sem = asyncio.Semaphore(settings.max_concurrency)

    async def one(agent: str) -> AgentProposal:
        saved = store.load(f"proposals/{agent}.json", AgentProposal)
        if saved:
            return saved
        async with sem:
            prop = await llm.generate(
                prompts.proposal_prompt(agent, roster[agent], blinds.get(agent), ctx), AgentProposal,
                stage=f"proposal:{agent}", system=prompts.system_for("developer"),
            )
        prop = prop.model_copy(update={"agent_id": agent})
        store.save(f"proposals/{agent}.json", prop)  # saved the moment it finishes, even if siblings fail
        return prop

    results = await asyncio.gather(*(one(a) for a in AGENT_IDS), return_exceptions=True)
    outcome = dict(zip(AGENT_IDS, results))
    failed = [a for a, r in outcome.items() if isinstance(r, BaseException) and not _fatal(r) and not _interrupt(r)]
    if failed and len(failed) < len(AGENT_IDS):
        rep.note(f"Giving {', '.join(failed)} one more try...")  # one bounded second chance for transient overloads
        again = await asyncio.gather(*(one(a) for a in failed), return_exceptions=True)
        outcome.update(zip(failed, again))
    proposals: dict[str, AgentProposal] = {}
    missing: list[str] = []
    for agent in AGENT_IDS:
        res = outcome[agent]
        if _fatal(res):
            raise MeetingError(str(res))
        if isinstance(res, BaseException):
            if _interrupt(res):
                raise res
            missing.append(agent)
            msg = f"{agent} ({prompts.skill_label(roster[agent])}) did not contribute a proposal: {res}"
            store.warn(msg)
            rep.warn(msg)
        else:
            proposals[agent] = res
            rep.publish("proposal", agent, res.thesis, format_proposal(res))
    if len(proposals) < settings.min_quorum:
        raise MeetingError(
            f"Only {len(proposals)} of {len(AGENT_IDS)} proposals succeeded (quorum is {settings.min_quorum}). "
            f"Completed proposals are saved in {store.root / 'proposals'}; fix the cause and `resume`."
        )
    if missing:
        store.warn(f"The pod ran without: {', '.join(missing)}.")
    return proposals, missing


# --------------------------------------------------------------------------- disputes raised in conversation


class DisputeBook:
    """Numbers objections as they are raised (DSP-001...) so later speakers can answer them by id."""

    def __init__(self, settings: Settings, participants: list[str]) -> None:
        self.settings, self.participants = settings, set(participants)
        self.items: list[Dispute] = []
        self.warnings: list[str] = []
        self._per_source: Counter[str] = Counter()

    def restore(self, disputes: list[Dispute]) -> None:
        for d in disputes:
            self.items.append(d)
            self._per_source[d.source_agent] += 1

    def add(self, source: str, raised: list[Dispute]) -> list[Dispute]:
        added: list[Dispute] = []
        for d in sorted(raised, key=lambda x: SEVERITY_ORDER[x.severity])[: self.settings.max_disputes_per_turn]:
            target = d.target_agent.strip().upper()
            if target == source:
                continue
            if target not in self.participants:
                target = "COUNCIL"
            if any(i.target_agent == target and similar(i.claim, d.claim) for i in self.items):
                continue  # the same objection is already on the table
            if self._per_source[source] >= self.settings.max_disputes_per_reviewer:
                self.warnings.append(f"{source} hit the limit of {self.settings.max_disputes_per_reviewer} objections; extra ones were dropped.")
                break
            numbered = d.model_copy(update={"source_agent": source, "target_agent": target, "dispute_id": f"DSP-{len(self.items) + 1:03d}"})
            self.items.append(numbered)
            self._per_source[source] += 1
            added.append(numbered)
        return added

    @property
    def formal(self) -> list[Dispute]:
        return [d for d in self.items if d.severity in ("CRITICAL", "MAJOR")]

    @property
    def nitpicks(self) -> list[Dispute]:
        return [d for d in self.items if d.severity == "NITPICK"]


def answered_ids(rounds: list[RoundRecord]) -> set[str]:
    return {r.dispute_id for rec in rounds for t in rec.turns for r in t.responses}


def owed_by(agent: str, book: DisputeBook, rounds: list[RoundRecord]) -> list[Dispute]:
    done = answered_ids(rounds)
    return [d for d in book.formal if d.target_agent == agent and d.dispute_id not in done]


# --------------------------------------------------------------------------- phase 3: the conversation


def _blank_note(why: str) -> ScrumNote:
    return ScrumNote(summary=why, message_to_team="Let's keep going. Respond to each other directly and name who you are answering.")


async def _scrum(llm: LLM, prompt: str, stage: str, store: MeetingStore, rep: Any, fallback: str) -> ScrumNote:
    try:
        return await llm.generate(prompt, ScrumNote, stage=stage, system=prompts.system_for("scrum"))
    except BaseException as exc:  # noqa: BLE001 - the room can continue without the facilitator's note
        if _fatal(exc):
            raise MeetingError(str(exc)) from exc
        if _interrupt(exc):
            raise
        msg = f"The scrum master's note failed ({exc}); continuing without it."
        store.warn(msg)
        rep.warn(msg)
        return _blank_note(fallback)


def _clean_turn(turn: AgentTurn, agent: str, allowed_targets: set[str], owed: list[Dispute]) -> AgentTurn:
    valid_to = allowed_targets | {"ALL", SCRUM_MASTER}
    utterances = []
    for u in turn.utterances:
        to = u.to.strip().upper()
        utterances.append(u.model_copy(update={"to": to if to in valid_to and to != agent else "ALL"}))
    owed_ids = {d.dispute_id for d in owed}
    seen: set[str] = set()
    responses = []
    for r in turn.responses:
        if r.dispute_id in owed_ids and r.dispute_id not in seen:
            seen.add(r.dispute_id)
            responses.append(r)
    return turn.model_copy(update={"agent_id": agent, "utterances": utterances, "responses": responses})


def _publish_turn(rep: Any, roster: dict[str, str], turn: AgentTurn, new: list[Dispute]) -> None:
    who = turn.agent_id
    for u in turn.utterances:
        rep.publish("talk", who, f"to {u.to} [{u.kind}] {u.text}", f"{prompts.who(who, roster)} to {u.to} [{u.kind}]\n{u.text}")
    for d in new:
        rep.publish("dispute", who, f"{d.severity} objection to {d.target_agent} ({d.dispute_id}): {d.claim}", format_dispute(d))
    for r in turn.responses:
        rep.publish("rebuttal", who, f"{r.stance} {r.dispute_id}: {r.response}", format_rebuttal(r))


def pick_speaker(
    agents: list[str], spoken: Counter, last_speaker: str | None, recent: list[AgentTurn], owed_now: dict[str, int],
    passed: set[str], note: ScrumNote, min_each: int,
) -> str | None:
    """Who talks next, the way a room decides: whoever was just addressed, whoever owes an answer, whoever has been quiet."""
    score: dict[str, float] = {}
    for agent in agents:
        if agent == last_speaker:
            continue
        s = 0.0
        addressed = [u for t in recent[-3:] for u in t.utterances if u.to == agent]
        if addressed:
            s += 4.0 + 0.5 * len(addressed)
        if owed_now.get(agent):
            s += 3.0
        if agent in {n.strip().upper() for n in note.next_speakers}:
            s += 2.0
        if spoken[agent] < min_each:
            s += 2.5
        s += 2.5 / (1 + spoken[agent])  # people who have said less get the floor
        s -= 1.5 * sum(1 for t in recent[-4:] if t.agent_id == agent)  # no two people talk only to each other
        mean = sum(spoken[x] for x in agents) / max(1, len(agents))
        if spoken[agent] > mean + 2:
            s -= 2.0  # already well ahead of the room
        if agent in passed and not addressed and not owed_now.get(agent):
            continue  # they said they had nothing to add and nobody has called on them since
        score[agent] = s
    return max(score, key=lambda a: (score[a], -spoken[a])) if score else None


async def run_conversation(
    llm: LLM, settings: Settings, ctx: str, proposals: dict[str, AgentProposal], roster: dict[str, str],
    store: MeetingStore, rep: Any,
) -> tuple[list[RoundRecord], ScrumNote, DisputeBook]:
    """A live conversation, not rounds. The scrum master checks in every few turns and decides when the room has converged."""
    agents = [a for a in AGENT_IDS if a in proposals]
    book = DisputeBook(settings, agents)
    rounds: list[RoundRecord] = []
    spoken: Counter[str] = Counter()
    fails: Counter[str] = Counter()
    dead: set[str] = set()  # developers who keep failing are dropped from the conversation instead of looping forever
    seg = 0
    while True:  # restore saved check-in segments (resume)
        saved = store.load(f"conversation/segment-{seg + 1}.json", RoundRecord)
        if not saved:
            break
        seg += 1
        rounds.append(saved)
        book.restore(saved.disputes)
        for t in saved.turns:
            spoken[t.agent_id] += 0 if t.pass_turn else 1
    if seg:
        rep.note(f"{seg} part(s) of the conversation restored from the saved meeting ({sum(spoken.values())} turns).")
    wrap = store.load("conversation/wrapup.json", ScrumNote)
    total_turns = sum(len(r.turns) for r in rounds)
    min_each, max_turns = settings.conversation_min_turns_each, settings.conversation_max_turns

    while wrap is None:
        seg += 1
        open_now = [d for d in book.formal if d.dispute_id not in answered_ids(rounds)]
        note = await _scrum(
            llm, prompts.scrum_prompt(seg, ctx, proposals, roster, rounds, open_now, {a: spoken[a] for a in agents}, max_turns, min_each, False),
            f"scrum:check{seg}", store, rep, "The scrum master is checking in.",
        )
        rep.publish("scrum", SCRUM_MASTER, note.message_to_team or note.summary, format_scrum(note))
        # Only a still-open CRITICAL objection from someone still in the room blocks wrapping; minor ones go to the decision stage.
        owed_total = sum(1 for a in agents if a not in dead for d in owed_by(a, book, rounds) if d.severity == "CRITICAL")
        quiet = [a for a in agents if a not in dead and spoken[a] < min_each]
        if seg > 1 and note.ready_to_wrap and not owed_total and not quiet:
            break
        if total_turns >= max_turns:
            rep.note(f"Reached the safety cap of {max_turns} turns; wrapping up.")
            break
        turns: list[AgentTurn] = []
        raised: list[Dispute] = []
        passed: set[str] = set()
        last: str | None = rounds[-1].turns[-1].agent_id if rounds and rounds[-1].turns else None
        while len(turns) < settings.scrum_every and total_turns < max_turns:
            owed_map = {a: len(owed_by(a, book, rounds + [RoundRecord(round=seg, note=note, turns=turns)])) for a in agents}
            agent = pick_speaker([a for a in agents if a not in dead], spoken, last, turns, owed_map, passed, note, min_each)
            if agent is None:
                break  # everyone left has nothing to add
            owed = owed_by(agent, book, rounds + [RoundRecord(round=seg, note=note, turns=turns)])
            try:
                turn = await llm.generate(
                    prompts.turn_prompt(
                        agent, roster[agent], prompts.phase_of(total_turns, len(agents), max_turns), spoken[agent], ctx,
                        proposals[agent], proposals, roster, rounds, note, turns, owed, settings.max_disputes_per_turn,
                    ),
                    AgentTurn, stage=f"talk{seg}:{agent}", system=prompts.system_for("developer", "review"),
                )
            except BaseException as exc:  # noqa: BLE001
                if _fatal(exc):
                    raise MeetingError(str(exc)) from exc
                if _interrupt(exc):
                    raise
                msg = f"{agent} could not speak: {exc}"
                store.warn(msg)
                rep.warn(msg)
                fails[agent] += 1
                if fails[agent] >= 2:
                    dead.add(agent)
                passed.add(agent)
                last = agent
                continue
            total_turns += 1
            last = agent
            turn = _clean_turn(turn, agent, set(agents) - {agent}, owed)
            if turn.pass_turn and not turn.utterances and not turn.responses and not owed:
                passed.add(agent)
                turns.append(turn)
                rep.note(f"{agent} stays quiet: nothing to add right now.")
                continue
            passed.discard(agent)
            spoken[agent] += 1
            new = book.add(agent, turn.disputes)
            turn = turn.model_copy(update={"disputes": new})
            turns.append(turn)
            raised.extend(new)
            _publish_turn(rep, roster, turn, new)
        record = RoundRecord(round=seg, note=note, turns=turns, disputes=raised)
        store.save(f"conversation/segment-{seg}.json", record)
        rounds.append(record)
        if not any(not t.pass_turn for t in turns):
            if not turns and total_turns == 0:
                raise MeetingError("Nobody could speak in the conversation; completed work is saved. Fix the cause and `resume`.")
            rep.note("Nobody has anything more to add; the conversation has run its course.")
            break

    if wrap is None:
        open_now = [d for d in book.formal if d.dispute_id not in answered_ids(rounds)]
        wrap = await _scrum(
            llm, prompts.scrum_prompt(seg + 1, ctx, proposals, roster, rounds, open_now, {a: spoken[a] for a in agents}, max_turns, min_each, True),
            "scrum:wrapup", store, rep, "The pod finished talking.",
        )
        store.save("conversation/wrapup.json", wrap)
    rep.publish("scrum", SCRUM_MASTER, wrap.summary, format_scrum(wrap))
    for w in dict.fromkeys(book.warnings):
        store.warn(w)
    left = [d.dispute_id for d in book.formal if d.dispute_id not in answered_ids(rounds)]
    if left:
        msg = f"{len(left)} objection(s) were never answered by their target: {', '.join(left)}."
        store.warn(msg)
        rep.warn(msg)
    return rounds, wrap, book


# --------------------------------------------------------------------------- views for the later stages


def reviews_from(rounds: list[RoundRecord]) -> dict[str, AgentReview]:
    """What the arbiter prompt calls reviews: each developer's endorsements across the whole conversation."""
    out: dict[str, AgentReview] = {}
    for rec in rounds:
        for t in rec.turns:
            cur = out.setdefault(t.agent_id, AgentReview(agent_id=t.agent_id))
            cur.endorsements.extend(t.endorsements)
            cur.product_questions.extend(t.product_questions)
    return out


def rebuttals_from(rounds: list[RoundRecord], book: DisputeBook) -> dict[str, AgentRebuttal]:
    target = {d.dispute_id: d.target_agent for d in book.items}
    out: dict[str, AgentRebuttal] = {}
    for rec in rounds:
        for t in rec.turns:
            for r in t.responses:
                if target.get(r.dispute_id) == t.agent_id:
                    out.setdefault(t.agent_id, AgentRebuttal(agent_id=t.agent_id)).responses.append(r)
    return out


def question_candidates(proposals: dict[str, AgentProposal], rounds: list[RoundRecord], wrap: ScrumNote) -> list[tuple[str, HumanQuestion]]:
    c = [(a, q) for a, p in proposals.items() for q in p.product_questions]
    c += [(t.agent_id, q) for rec in rounds for t in rec.turns for q in t.product_questions]
    c += [(SCRUM_MASTER, q) for rec in rounds for q in rec.note.product_questions]
    c += [(SCRUM_MASTER, q) for q in wrap.product_questions]
    return c


def load_roster(store: MeetingStore) -> dict[str, str]:
    saved = store.load("roster.json", Roster)
    return dict(saved.skills) if saved else {}
