"""Sessions as the tools and the team engine use them: create, prompt, run, interrupt (opencode: packages/core/src/session.ts and execution.ts).

Running is owned by a `RunCoordinator`: one execution per session, any number of sessions at once. `resume` runs a session to idle (joining the
run already in flight); `wake` is the doorbell for new work. With an inbox, input is not appended to a busy session but waits there:

  send(..., delivery="steer")   taken at the next step boundary of the run in progress
  send(..., delivery="queue")   answered after the current work, when the session is idle
  compact()                     summarize the older history now (no model answer follows)
  synthetic()                   a notice from the system (a background command or subagent finished); steered, so a busy parent sees it at once

Without an inbox (a bare runner, as in some tests) `prompt` and `synthetic` record the message directly and a wake simply runs the session."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from harness.schema import message as M
from harness.session.inbox import InboxItem, SessionInbox
from harness.session.run_coordinator import ExecutionInterrupted, RunCoordinator
from harness.session.runner.runner import DrainResult, SessionRunner
from harness.session.store import SessionInfo, SessionStore


class SessionNotFoundError(Exception):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session not found: {session_id}")
        self.session_id = session_id


class SessionService:
    def __init__(self, store: SessionStore, runner: SessionRunner, directory: str, inbox: Optional[SessionInbox] = None) -> None:
        self.store, self.runner, self.directory = store, runner, directory
        self.inbox: Optional[SessionInbox] = inbox if inbox is not None else getattr(runner, "inbox", None)
        self._results: dict[str, DrainResult] = {}
        self.revert: Optional[Any] = None  # a SessionRevert: new input to a rewound session makes the rewind final first
        self.coordinator: RunCoordinator[str] = RunCoordinator(self._drain, started=self._started)

    async def _started(self, session_id: str) -> None:
        self._results.pop(session_id, None)  # a new busy period reports only its own work

    async def _drain(self, session_id: str, force: bool, scope: str) -> None:
        """One busy period can drain several times (input arrived mid-run). Its result adds them up and keeps the worst outcome."""
        result = await self.runner.drain(session_id, force, scope)
        before = self._results.get(session_id)
        if before is not None:
            rank = {"succeeded": 0, "interrupted": 1, "failed": 2}
            worst = result if rank.get(result.outcome, 0) >= rank.get(before.outcome, 0) else before
            result = DrainResult(worst.outcome, before.steps + result.steps, worst.error or before.error or result.error)
        self._results[session_id] = result

    # ------------------------------------------------------------------ records

    def get(self, session_id: str) -> SessionInfo:
        info = self.store.get(session_id)
        if info is None:
            raise SessionNotFoundError(session_id)
        return info

    def create(self, *, parent_id: Optional[str] = None, title: Optional[str] = None, agent: Optional[str] = None,
               model: Optional[M.ModelRef] = None, directory: Optional[str] = None) -> SessionInfo:
        if parent_id is not None:
            self.get(parent_id)
        return self.store.create(directory or self.directory, agent=agent, model=model.model_dump(exclude_none=True) if model else None,
                                 parent_id=parent_id, title=title)

    def switch_agent(self, session_id: str, agent: str) -> None:
        info = self.get(session_id)
        self.store.add(session_id, M.AgentSelected(agent=agent, previous=info.agent))
        self.store.update(session_id, agent=agent)

    def switch_model(self, session_id: str, model: M.ModelRef) -> None:
        info = self.get(session_id)
        previous = M.ModelRef(**info.model) if info.model else None
        self.store.add(session_id, M.ModelSelected(model=model, previous=previous))
        self.store.update(session_id, model=model.model_dump(exclude_none=True))

    def rename(self, session_id: str, title: str) -> None:
        self.get(session_id)
        self.store.update(session_id, title=title)

    def move(self, session_id: str, directory: str) -> str:
        """Points the session at another directory; the next step runs there. Returns the resolved directory."""
        info = self.get(session_id)
        target = os.path.realpath(os.path.join(info.directory, os.path.expanduser(directory)))
        if not os.path.isdir(target):
            raise NotADirectoryError(f"Directory does not exist: {target}")
        self.store.add(session_id, M.LocationSwitched(location=M.LocationRef(directory=target), previous=M.LocationRef(directory=info.directory)))
        self.store.update(session_id, directory=target)
        return target

    def messages(self, session_id: str, order: str = "asc", limit: Optional[int] = None) -> list[M.Info]:
        items = [m for _, m in self.store.messages(session_id)]
        if order == "desc":
            items.reverse()
        return items[:limit] if limit is not None else items

    # ------------------------------------------------------------------ input

    def _settle_revert(self, session_id: str) -> None:
        if self.revert is not None and self.revert.state(session_id) is not None:
            self.revert.commit(session_id)

    def prompt(self, session_id: str, text: str) -> M.User:
        """Records the user's message directly. For a session that may be busy use `send`, which goes through the inbox."""
        self.get(session_id)
        self._settle_revert(session_id)
        msg = M.User(text=text)
        self.store.add(session_id, msg)
        return msg

    def send(self, session_id: str, text: str, delivery: str = "queue", wake: bool = True) -> Any:
        """Accepts input for a possibly busy session. Returns the inbox item (or, without an inbox, the recorded message)."""
        self.get(session_id)
        self._settle_revert(session_id)
        if self.inbox is None:
            msg = self.prompt(session_id, text)
            if wake:
                self.wake(session_id)
            return msg
        item = self.inbox.admit(session_id, "user", {"text": text}, delivery)
        if wake:
            self.wake(session_id, "steer" if delivery == "steer" else "input")
        return item

    def synthetic(self, session_id: str, text: str, description: Optional[str] = None, metadata: Optional[dict[str, Any]] = None,
                  resume: bool = True) -> Any:
        """A notice from the system. With an inbox it is steered: a running session sees it at its next step, an idle one is woken."""
        self.get(session_id)
        if self.inbox is None:
            msg = M.Synthetic(text=text, description=description, metadata=metadata)
            self.store.add(session_id, msg)
            if resume:
                self.wake(session_id)
            return msg
        item = self.inbox.admit(session_id, "synthetic", {"text": text, "description": description, "metadata": metadata}, "steer")
        if resume:
            self.wake(session_id, "steer")
        return item

    def cancel_input(self, session_id: str, item_id: str) -> None:
        self._inbox().cancel(session_id, item_id)

    def steer(self, session_id: str, item_id: str) -> None:
        """Changes a queued item to be taken at the next step boundary (and wakes an idle session)."""
        self._inbox().steer(session_id, item_id)
        self.wake(session_id, "steer")

    def queue(self, session_id: str, item_id: str) -> None:
        self._inbox().queue(session_id, item_id)

    def pending_input(self, session_id: str) -> list[InboxItem]:
        return self._inbox().list(session_id)

    def _inbox(self) -> SessionInbox:
        if self.inbox is None:
            raise RuntimeError("this session service has no inbox")
        return self.inbox

    # ------------------------------------------------------------------ running

    def running(self, session_id: str) -> bool:
        return self.coordinator.is_active(session_id)

    def active(self) -> set[str]:
        return self.coordinator.active()

    async def resume(self, session_id: str) -> DrainResult:
        """Runs the session to idle, or joins the run already in flight. Raises CancelledError if the run was interrupted."""
        self.get(session_id)
        try:
            await self.coordinator.run(session_id)
        except ExecutionInterrupted:
            raise asyncio.CancelledError() from None
        return self._results.get(session_id, DrainResult("succeeded", 0))

    def wake(self, session_id: str, scope: str = "input") -> None:
        """The doorbell: an idle session starts if it has input it may take; a busy one drains again before it settles."""
        self.coordinator.wake(session_id, scope)

    async def compact(self, session_id: str) -> DrainResult:
        """Summarizes the older history now. Goes through the inbox so it takes its turn at a step boundary; no model answer follows it."""
        self.get(session_id)
        self._inbox().admit_compaction(session_id, "steer")
        self.wake(session_id, "steer")
        await self.coordinator.await_idle(session_id)
        return self._results.get(session_id, DrainResult("succeeded", 0))

    async def interrupt(self, session_id: str, reason: str = "user", resume: bool = False) -> bool:
        """Stops the run in flight. With `resume`, input the interrupted run was about to take (steers, a compaction) carries on in a fresh one;
        queued follow-ups stay parked."""
        interrupted = await self.coordinator.interrupt(session_id, reason, await_settlement=True)
        if resume and self.inbox is not None:
            nxt = self.inbox.next_promotable(session_id, "input")
            if nxt is not None and (nxt.delivery == "steer" or nxt.type == "compaction"):
                self.wake(session_id, "steer")
        return interrupted

    async def close(self) -> None:
        await self.coordinator.close()
