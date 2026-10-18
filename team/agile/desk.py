"""The human's desk: where the person supervising the team approves things, interrupts, and gives direction.

  approvals   Anything major waits here for a yes or no: the first set of documents, an architecture or scope decision, a change to the PRD.
              The team that asked keeps working on whatever is not blocked by the answer.
  interrupt   Freezes all coding (between steps), shows where things stand, and lets the human speak. What they say becomes a directive that
              the playbook acts on before coding resumes.
  notes       Guidance that does not need the team to stop: delivered at the next standup.

The desk is a plain object with async methods; the TUI (and later the web front end) calls them. It never talks to the developers itself:
the playbook does that, over A2A."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional

from team.agile.gate import WorkGate
from team.agile.model import Approval, Directive
from team.agile.store import AgileStore

Handler = Callable[[Directive], Awaitable[None]]


class HumanDesk:
    def __init__(self, gate: WorkGate, store: AgileStore, on_event: Optional[Callable[[str, dict], None]] = None, mode: str = "ask", quiesce_timeout: float = 120.0) -> None:
        """`mode`: 'ask' waits for the human; 'approve' answers yes to everything (unattended runs and tests)."""
        self.gate, self.store, self.mode, self.quiesce_timeout = gate, store, mode, quiesce_timeout
        self.on_event = on_event or (lambda kind, data: None)
        self.handler: Optional[Handler] = None  # set by the playbook: acts on a directive
        self._answers: dict[str, asyncio.Future] = {}
        self._notes: list[str] = []
        self._released = asyncio.Event()
        self._released.set()
        self.interrupted = False

    # ------------------------------------------------------------------ approvals

    async def approval(self, title: str, detail: str, kind: str = "decision", dev: Optional[str] = None) -> Approval:
        """Asks for a decision and waits for it. A developer waiting here counts as resting, so a ceremony does not wait on the answer."""
        state = self.store.state
        item = Approval(id=state.next_id("APP", state.approvals), title=title, detail=detail, kind=kind, sprint=state.sprint)
        state.approvals.append(item)
        self.store.save()
        if self.mode == "approve":
            item.status, item.answer = "approved", "approved automatically (unattended run)"
            self.store.save()
            self.on_event("approval-answered", {"id": item.id, "approved": True, "title": title, "auto": True})
            return item
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._answers[item.id] = future
        self.on_event("approval-requested", {"id": item.id, "title": title, "detail": detail, "kind": kind})
        if dev is not None:
            async with self.gate.waiting(dev, "waiting"):
                await future
        else:
            await future
        return item

    def pending(self) -> list[Approval]:
        return [a for a in self.store.state.approvals if a.status == "pending"]

    def answer(self, approval_id: str, approved: bool, text: str = "") -> Approval:
        item = next((a for a in self.store.state.approvals if a.id == approval_id), None)
        if item is None or item.status != "pending":
            raise KeyError(f"no pending approval {approval_id}")
        item.status, item.answer = ("approved" if approved else "rejected"), text
        self.store.save()
        self.on_event("approval-answered", {"id": item.id, "approved": approved, "title": item.title, "text": text})
        future = self._answers.pop(item.id, None)
        if future is not None and not future.done():
            future.set_result(item)
        return item

    # ------------------------------------------------------------------ interrupting

    async def interrupt(self) -> dict[str, Any]:
        """Stops all coding at the next step boundary. Returns the late developers (still inside a long step), if any."""
        self.interrupted = True
        self._released.clear()
        late = await self.gate.hold("human", self.quiesce_timeout)
        self.on_event("interrupted", {"late": late})
        return {"late": late}

    async def say(self, text: str, kind: Optional[str] = None) -> Directive:
        """What the human tells the team. The playbook classifies and acts on it (the gate stays frozen until `release`)."""
        state = self.store.state
        directive = Directive(id=state.next_id("DIR", state.directives), text=text.strip(), kind=kind or "", sprint=state.sprint, day=self.gate.day)
        state.directives.append(directive)
        self.store.save()
        self.on_event("directive", {"id": directive.id, "text": directive.text})
        if self.handler is not None:
            try:
                await self.handler(directive)
            except Exception as exc:  # noqa: BLE001 - the human is told; the team is not left half-changed
                directive.effect = f"could not be applied: {type(exc).__name__}: {exc}"
                directive.handled = True
                self.on_event("directive-failed", {"id": directive.id, "error": directive.effect})
        else:
            directive.handled = True
            directive.effect = "recorded"
        self.store.save()
        self.on_event("directive-handled", {"id": directive.id, "kind": directive.kind, "effect": directive.effect})
        return directive

    async def release(self) -> None:
        """Lets coding go on."""
        self.interrupted = False
        await self.gate.thaw("human")
        self._released.set()
        self.on_event("resumed", {})

    async def hold_point(self) -> None:
        """A ceremony calls this between its steps: while the human has the floor, the ceremony waits."""
        await self._released.wait()

    # ------------------------------------------------------------------ notes

    def note(self, text: str) -> None:
        """Guidance for the next standup; the team does not stop for it."""
        self._notes.append(text.strip())
        self.on_event("note", {"text": text})

    def take_notes(self) -> list[str]:
        notes, self._notes = self._notes, []
        return notes

    def status(self) -> dict[str, Any]:
        s = self.store.state
        cur = s.current()
        return {
            "phase": s.phase, "sprint": s.sprint, "day": self.gate.day, "goal": cur.goal if cur else "", "frozen_by": sorted(self.gate.holders),
            "resting": self.gate.resting(), "workers": sorted(self.gate.workers), "open_impediments": [i.text for i in s.open_impediments()],
            "pending_approvals": [{"id": a.id, "title": a.title} for a in self.pending()], "at": time.time(),
        }
