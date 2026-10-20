"""The memory tools every developer has: `recall` (what do we already know?) and `remember` (the team should know this)."""

from __future__ import annotations

import asyncio
from typing import Literal, Optional

from pydantic import BaseModel, Field

from harness.tool.info import ToolContext, ToolInfo, ToolResult
from memory.team import PROJECT, TeamMemory


class Link(BaseModel):
    relation: str = Field(description="How they are related, e.g. imports, uses, depends_on, fixes, replaces, about, part_of")
    kind: str = Field(description="What the other thing is: file, module, feature, decision, note, api")
    name: str = Field(description="Its name (a file path, a function, a feature id, ...)")


class RememberInput(BaseModel):
    scope: Literal["project", "me"] = Field(description="'project': the whole team will see it (a convention, an API you created, a trap, how something works). 'me': only you (what works for you, mistakes you made)")
    kind: str = Field(description="note, convention, api, pitfall, how-to, or another short label")
    name: str = Field(description="A short name that others will search for, e.g. 'TimerRegistry limits' or 'run tests with pytest -q'")
    text: str = Field(description="What to remember, in one or two sentences")
    links: list[Link] = Field(default_factory=list, description="Things it is about or depends on, so it is found through them")
    importance: int = Field(default=6, description="1 (minor) to 10 (the team must not forget this)")


class RecallInput(BaseModel):
    query: str = Field(description="What you want to know about: a file, a feature, a problem, an API")


def memory_tools(memory: TeamMemory, dev: str) -> list[ToolInfo]:
    async def remember(inp: RememberInput, ctx: ToolContext) -> ToolResult:
        message = await asyncio.to_thread(memory.remember, dev, PROJECT if inp.scope == "project" else "me", inp.kind.strip() or "note", inp.name, inp.text,
                                          [(l.relation, l.kind, l.name) for l in inp.links], max(1, min(10, inp.importance)))
        return ToolResult(content=message, output={"scope": inp.scope, "name": inp.name})

    async def recall(inp: RecallInput, ctx: ToolContext) -> ToolResult:
        found = await memory.recall(dev, inp.query)
        return ToolResult(content=found or "Nothing in the team's memory or your own matches that yet.", output={"found": bool(found)})

    return [
        ToolInfo("recall", "Look in the project memory (everything the team has built, decided and learned, with how it connects) and your own memory. "
                           "Use it before you start new work and when you are unsure how something fits, so you build on what teammates did instead of repeating or contradicting it.", RecallInput, recall),
        ToolInfo("remember", "Write something down that is worth keeping: a convention, an API you created, how something works, a trap you hit. "
                             "scope='project' shares it with the whole team (do this for anything a teammate would need); scope='me' keeps it for yourself. Keep it short and link it to what it is about.", RememberInput, remember),
    ]
