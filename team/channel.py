"""How developers talk to each other while they work: one asks, another answers.

`Channel` is the interface the engine uses (conflict talks, design reviews, the scrum master's questions). `LocalChannel` is the in-process
implementation: the question becomes a message in a short-lived, tool-less consultation session on the recipient's own harness, so the
recipient answers in character with their skill and with a fresh view that does not disturb the feature they are working on. The A2A
implementation (`council_a2a`) plugs in behind the same interface, which is how the same conversations will travel over gRPC."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

from team.persona import consult_agent


class Channel(Protocol):
    async def ask(self, sender: str, recipient: str, text: str, topic: str = "") -> str: ...

    async def broadcast(self, sender: str, recipients: list[str], text: str, topic: str = "") -> dict[str, str]: ...

    async def converse(self, topic: str, participants: list[str], opener: str, starter: str = "system", rounds: int = 1) -> list: ...


@dataclass
class Message:
    sender: str
    recipient: str
    topic: str
    text: str
    reply: str = ""


@dataclass
class LocalChannel:
    """`harness_for(dev)` returns that developer's Harness; `skill_of` maps a developer to their skill."""

    harness_for: Callable[[str], Any]
    skill_of: Callable[[str], str]
    timeout: float = 600.0
    log: list[Message] = field(default_factory=list)
    on_message: Optional[Callable[[Message], None]] = None
    _registered: set[str] = field(default_factory=set)

    async def ask(self, sender: str, recipient: str, text: str, topic: str = "") -> str:
        harness = self.harness_for(recipient)
        agent = consult_agent(recipient, self.skill_of(recipient))
        if agent.id not in self._registered:
            harness.agents.transform(lambda editor, a=agent: editor.update(a.id, lambda cur, a=a: _apply(cur, a)))
            self._registered.add(agent.id)
        message = Message(sender, recipient, topic, text)
        self.log.append(message)
        prompt = f"{sender} writes to you" + (f" about {topic}" if topic else "") + f":\n\n{text}"
        result = await asyncio.wait_for(harness.prompt(prompt, agent=agent.id), self.timeout)
        message.reply = result.text if result.outcome == "succeeded" else f"(no answer: {result.error or result.outcome})"
        if self.on_message:
            self.on_message(message)
        return message.reply

    async def broadcast(self, sender: str, recipients: list[str], text: str, topic: str = "") -> dict[str, str]:
        answers = await asyncio.gather(*(self.ask(sender, r, text, topic) for r in recipients), return_exceptions=True)
        return {r: (a if isinstance(a, str) else f"(no answer: {type(a).__name__})") for r, a in zip(recipients, answers)}


    async def converse(self, topic: str, participants: list[str], opener: str, starter: str = "system", rounds: int = 1) -> list:
        """A group conversation: everyone in turn sees the whole transcript so far. Returns [Turn(speaker, text)], the opener first."""
        from council_a2a import Turn

        transcript = [Turn(starter, opener)]
        for round_no in range(1, rounds + 1):
            for speaker in participants:
                shown = "\n\n".join(f"{t.speaker}: {t.text}" for t in transcript)
                prompt = (
                    f"Group conversation about: {topic}\nParticipants: {', '.join(participants)}\n\n{shown}\n\n"
                    f"It is your turn, {speaker} (round {round_no} of {rounds}). Add to the discussion; do not repeat what was said."
                )
                transcript.append(Turn(speaker, await self.ask(starter, speaker, prompt, topic)))
        return transcript


def _apply(cur, src) -> None:
    cur.name, cur.mode, cur.hidden, cur.system, cur.description = src.name, src.mode, src.hidden, src.system, src.description
    cur.permissions = list(src.permissions)
