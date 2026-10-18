"""Assembling what one model request is built from (opencode: packages/core/src/session/context.ts and the instruction
preparation done by the runner).

  select  fixes the session, the agent, the instruction sources and the tool snapshot
  load    adds the model and the active history for that selection

Instruction sources are ordered from most to least shared across sessions so the baseline stays a reusable prompt-cache prefix:
user-level skill guidance first, then project instructions, then the date and environment, which vary by day and directory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from harness.ai import types as T
from harness.ai.model import ResolvedModel
from harness.instruction_discovery import InstructionDiscovery
from harness.instructions import builtins
from harness.instructions import index as I
from harness.location import Location
from harness.permission import merge
from harness.schema.permission import Ruleset
from harness.session import history
from harness.session import instruction_state as InstructionState
from harness.session.compaction import AgentInfo, Loaded
from harness.session.store import SessionInfo, SessionStore
from harness.skill import SkillCatalog
from harness.skill_instructions import load as skill_instructions
from harness.util.global_paths import GlobalPaths


class AgentNotFoundError(Exception):
    def __init__(self, session_id: str, agent: str) -> None:
        super().__init__(f"Agent not found for session {session_id}: {agent}")


@dataclass
class Selection:
    session: SessionInfo
    agent: AgentInfo
    permissions: Ruleset
    instructions: I.List
    tools: list[T.ToolEntry]


class SessionContext:
    def __init__(
        self, store: SessionStore, location: Location, paths: GlobalPaths, discovery: InstructionDiscovery, skills: SkillCatalog,
        resolve_agent: Callable[[Optional[str]], Optional[tuple[AgentInfo, Ruleset]]], resolve_model: Callable[[SessionInfo], ResolvedModel],
        tools_for: Callable[[Ruleset], list[T.ToolEntry]] = lambda permissions: [],
    ) -> None:
        self.store, self.location, self.paths = store, location, paths
        self.discovery, self.skills = discovery, skills
        self.resolve_agent, self.resolve_model, self.tools_for = resolve_agent, resolve_model, tools_for

    def select(self, session_id: str) -> Selection:
        session = self.store.get(session_id)
        if session is None:
            raise RuntimeError(f"Session not found: {session_id}")
        resolved = self.resolve_agent(session.agent)
        if resolved is None:
            raise AgentNotFoundError(session.id, session.agent or "(default)")
        agent, agent_rules = resolved
        # Session permissions narrow discovery the same way they narrow the tool snapshot.
        permissions = merge(agent_rules, session.permission_rules())
        self.skills.reload()
        instructions = I.combine([
            skill_instructions(self.skills, permissions),
            self.discovery.load(),
            builtins.load(self.location, self.paths),
        ])
        return Selection(session, agent, permissions, instructions, self.tools_for(permissions))

    def prepare(self, selection: Selection) -> Optional[object]:
        """Record any instruction change since the model last saw them (the first call establishes the baseline)."""
        return InstructionState.prepare(self.store, selection.instructions, selection.session.id)

    def load(self, selection: Selection) -> Loaded:
        model = self.resolve_model(selection.session)
        loaded = history.entries_for_runner(self.store, selection.session.id, selection.instructions)
        return Loaded(
            session=selection.session, agent=selection.agent, model=model, initial=loaded.initial,
            messages=[m for _, m in loaded.entries], tools=selection.tools,
        )

    def context(self, session_id: str) -> tuple[Selection, Loaded]:
        """select + prepare + load in one call."""
        selection = self.select(session_id)
        self.prepare(selection)
        return selection, self.load(selection)
