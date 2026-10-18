"""A set of A2A agents that can talk to each other: direct questions, fan-out to several agents, and group conversations.

The protocol is point to point (each agent is its own server). A *network* adds the thin layer a team needs on top of it: it starts the
agents, remembers where they are, gives callers `ask` / `broadcast` / `converse`, and writes every exchange to an audit log."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from council_a2a.agent import A2AAgent, Handler
from council_a2a.client import A2AClient, A2AError


@dataclass
class Turn:
    speaker: str
    text: str


@dataclass
class AuditLog:
    """One JSON line per exchange: who asked whom, about what, what came back, how long it took."""

    path: Optional[Path] = None
    entries: list[dict] = field(default_factory=list)

    def record(self, **entry) -> None:
        entry = {"ts": round(time.time(), 3), **entry}
        self.entries.append(entry)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


class A2ANetwork:
    def __init__(self, token: Optional[str] = None, audit_path: Optional[Path] = None, host: str = "127.0.0.1", timeout: float = 900.0) -> None:
        self.token, self.host, self.timeout = token, host, timeout
        self.agents: dict[str, A2AAgent] = {}
        self.audit = AuditLog(Path(audit_path) if audit_path else None)
        self._clients: dict[tuple[str, str], A2AClient] = {}

    # ------------------------------------------------------------------ membership

    async def add(self, name: str, handler: Handler, description: str = "", skill: str = "") -> A2AAgent:
        if name in self.agents:
            raise ValueError(f"agent already on the network: {name}")
        agent = A2AAgent(name, handler, description, skill, token=self.token, host=self.host)
        await agent.start()
        self.agents[name] = agent
        return agent

    def directory(self) -> dict[str, dict[str, str]]:
        """Who is on the network: name -> address, skill and description (what their Agent Cards say)."""
        return {n: {"address": a.address, "skill": a.skill, "description": a.description} for n, a in self.agents.items()}

    def _client(self, sender: str, recipient: str) -> A2AClient:
        if recipient not in self.agents:
            raise A2AError(f"no agent named {recipient!r} on the network")
        key = (sender, recipient)
        if key not in self._clients:
            self._clients[key] = A2AClient(sender, self.agents[recipient].address, self.token, self.timeout)
        return self._clients[key]

    # ------------------------------------------------------------------ talking

    async def ask(self, sender: str, recipient: str, text: str, topic: str = "", context_id: Optional[str] = None, group: Optional[list[str]] = None) -> str:
        started = time.monotonic()
        context_id = context_id or str(uuid.uuid4())
        try:
            reply = await self._client(sender, recipient).ask(text, topic, context_id, group)
        except A2AError as exc:
            self.audit.record(sender=sender, recipient=recipient, topic=topic, context_id=context_id, text=text, error=str(exc))
            raise
        self.audit.record(sender=sender, recipient=recipient, topic=topic, context_id=context_id, text=text, reply=reply, ms=round((time.monotonic() - started) * 1000))
        return reply

    async def broadcast(self, sender: str, recipients: list[str], text: str, topic: str = "") -> dict[str, str]:
        """The same message to several agents at once; an agent that cannot answer is reported rather than failing the rest."""
        context_id = str(uuid.uuid4())
        answers = await asyncio.gather(*(self.ask(sender, r, text, topic, context_id) for r in recipients), return_exceptions=True)
        return {r: (a if isinstance(a, str) else f"(no answer: {a})") for r, a in zip(recipients, answers)}

    async def converse(
        self, topic: str, participants: list[str], opener: str, starter: str = "system", rounds: int = 2,
        done: Optional[Callable[[list[Turn]], bool]] = None,
    ) -> list[Turn]:
        """A group conversation: everyone sees the whole transcript so far and speaks in turn, for `rounds` rounds or until `done(transcript)`.
        The agents share one conversation id, so the thread can be followed in the audit log."""
        context_id = str(uuid.uuid4())
        transcript = [Turn(starter, opener)]
        for round_no in range(1, rounds + 1):
            for speaker in participants:
                shown = "\n\n".join(f"{t.speaker}: {t.text}" for t in transcript)
                prompt = f"Group conversation about: {topic}\nParticipants: {', '.join(participants)}\n\n{shown}\n\nIt is your turn, {speaker} (round {round_no} of {rounds}). Add to the discussion; do not repeat what was said."
                try:
                    reply = await self.ask(starter, speaker, prompt, topic, context_id, participants)
                except A2AError as exc:
                    reply = f"(no answer: {exc})"
                transcript.append(Turn(speaker, reply))
                if done is not None and done(transcript):
                    return transcript
        return transcript

    # ------------------------------------------------------------------ lifecycle

    async def close(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
        for agent in self.agents.values():
            await agent.stop()
        self.agents.clear()

    async def __aenter__(self) -> "A2ANetwork":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()
