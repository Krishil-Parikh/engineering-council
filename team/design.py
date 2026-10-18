"""Design-change meetings: a developer who needs to change the architecture, a contract or the data model asks the team first.

Everyone else on the team gets the proposal, replies with a vote (approve, reject or amend) and a comment, and the majority decides; the
scrum master breaks a tie. An approved change is written down as an architecture decision record (`docs/adr/NNNN-<slug>.md`) in the
requesting developer's sandbox, so it travels with their branch and lands in the integration branch with their work. The developer then
updates docs/Design.md to match and carries on."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from harness.tool.builtin.deps import ToolDeps
from harness.tool.info import ToolContext, ToolError, ToolInfo, ToolResult
from team.channel import Channel
from team.repo import slugify

VOTE_PROMPT = """{proposer} proposes a design change and the team decides it together.

TITLE: {title}
WHY: {reason}
PROPOSED CHANGE:
{change}

Consider your own area first, then the whole system: what breaks, what gets simpler, what it costs, whether the contracts in docs/Design.md stay consistent.
Reply with ONLY a JSON object: {{"vote": "approve" | "reject" | "amend", "comment": "one or two sentences", "amendment": "what to change in the proposal, if you vote amend"}}"""


@dataclass
class Vote:
    voter: str
    vote: str
    comment: str = ""
    amendment: str = ""


@dataclass
class Decision:
    title: str
    proposer: str
    approved: bool
    votes: list[Vote] = field(default_factory=list)
    amendments: list[str] = field(default_factory=list)
    adr: Optional[str] = None  # path relative to the proposer's sandbox, when approved

    def summary(self) -> str:
        lines = [f"Design change '{self.title}': {'APPROVED' if self.approved else 'REJECTED'}"]
        lines += [f"- {v.voter}: {v.vote}. {v.comment}".rstrip() for v in self.votes]
        if self.amendments:
            lines += ["Amendments to apply:"] + [f"- {a}" for a in self.amendments]
        if self.approved and self.adr:
            lines.append(f"The decision is recorded in {self.adr}. Update docs/Design.md to match, then continue.")
        if not self.approved:
            lines.append("Do not make this change. Find a way to meet the task within the existing design, or finish and report what blocks you.")
        return "\n".join(lines)


def parse_vote(voter: str, reply: str) -> Vote:
    match = re.search(r"\{.*\}", reply, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            vote = str(data.get("vote", "")).lower().strip()
            if vote in ("approve", "reject", "amend"):
                return Vote(voter, vote, str(data.get("comment", "")), str(data.get("amendment", "")))
        except ValueError:
            pass
    lowered = reply.lower()
    for word in ("reject", "amend", "approve"):
        if word in lowered:
            return Vote(voter, word, reply.strip()[:200])
    return Vote(voter, "abstain", reply.strip()[:200])


def decide(votes: list[Vote], tiebreak: Optional[Vote] = None) -> bool:
    """A strict majority of the voters who cast a vote approves; `amend` counts as a conditional yes (the amendments get applied)."""
    cast = [v for v in votes if v.vote != "abstain"]
    yes = sum(1 for v in cast if v.vote in ("approve", "amend"))
    no = sum(1 for v in cast if v.vote == "reject")
    if yes != no:
        return yes > no
    return tiebreak is not None and tiebreak.vote in ("approve", "amend")


def next_adr_number(adr_dir: Path) -> int:
    numbers = [int(m.group(1)) for p in adr_dir.glob("*.md") if (m := re.match(r"(\d+)-", p.name))] if adr_dir.is_dir() else []
    return max(numbers, default=0) + 1


def write_adr(sandbox: Path, decision: Decision, reason: str, change: str) -> str:
    adr_dir = sandbox / "docs" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    name = f"{next_adr_number(adr_dir):04d}-{slugify(decision.title)}.md"
    votes = "\n".join(f"- {v.voter}: {v.vote}. {v.comment}" for v in decision.votes) or "- (none)"
    amendments = ("\n## Amendments\n\n" + "\n".join(f"- {a}" for a in decision.amendments) + "\n") if decision.amendments else ""
    body = (
        f"# {decision.title}\n\n**Status:** accepted  \n**Proposed by:** {decision.proposer}\n\n## Context\n\n{reason.strip()}\n\n"
        f"## Decision\n\n{change.strip()}\n{amendments}\n## Votes\n\n{votes}\n"
    )
    (adr_dir / name).write_bytes(body.encode("utf-8"))
    return f"docs/adr/{name}"


class DesignBoard:
    """Runs the meetings. `team` is every developer; `scrum_master` breaks ties; `sandbox_of` locates a developer's clone."""

    def __init__(self, channel: Channel, team: list[str], sandbox_of, scrum_master: str, skill_of=lambda dev: "") -> None:
        self.channel, self.team, self.sandbox_of, self.scrum_master = channel, team, sandbox_of, scrum_master
        self.decisions: list[Decision] = []
        self._lock = asyncio.Lock()  # one meeting at a time: the design is one document

    async def meet(self, proposer: str, title: str, reason: str, change: str) -> Decision:
        async with self._lock:
            others = [d for d in self.team if d != proposer]
            prompt = VOTE_PROMPT.format(proposer=proposer, title=title, reason=reason, change=change)
            replies = await self.channel.broadcast(proposer, others, prompt, topic=f"design change: {title}") if others else {}
            votes = [parse_vote(d, r) for d, r in replies.items()]
            tiebreak = None
            if others and sum(1 for v in votes if v.vote in ("approve", "amend")) == sum(1 for v in votes if v.vote == "reject"):
                tie = votes[:]
                prompt2 = prompt + "\n\nThe team is split. As scrum master, cast the deciding vote.\n" + "\n".join(f"- {v.voter}: {v.vote}. {v.comment}" for v in tie)
                if self.scrum_master in others:
                    tiebreak = parse_vote(self.scrum_master, await self.channel.ask(proposer, self.scrum_master, prompt2, topic=f"tie-break: {title}"))
            approved = decide(votes, tiebreak) if others else True
            decision = Decision(title, proposer, approved, votes, [v.amendment for v in votes if v.vote == "amend" and v.amendment])
            if approved:
                decision.adr = write_adr(Path(self.sandbox_of(proposer)), decision, reason, change)
            self.decisions.append(decision)
            return decision


class DesignChangeInput(BaseModel):
    title: str = Field(description="Short name of the change")
    reason: str = Field(description="Why the current design cannot meet the task")
    change: str = Field(description="Exactly what should change: which contract, component boundary or data model, and how")


def design_change_tool(deps: ToolDeps, board: DesignBoard, proposer: str) -> ToolInfo:
    async def execute(inp: DesignChangeInput, ctx: ToolContext) -> ToolResult:
        try:
            decision = await board.meet(proposer, inp.title, inp.reason, inp.change)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"The design meeting could not be held: {exc}") from None
        return ToolResult(content=decision.summary(), output={"approved": decision.approved, "adr": decision.adr}, metadata={"approved": decision.approved})

    return ToolInfo(
        "design_change",
        "Ask the whole team to approve a change to the architecture, a contract in docs/Design.md, a component boundary or the data model. "
        "Use it BEFORE making such a change; never change the design on your own. The other developers vote and you get the decision back.",
        DesignChangeInput, execute,
    )
