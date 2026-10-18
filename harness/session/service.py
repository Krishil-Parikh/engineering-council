"""Sessions as the tools and the team engine use them: create, prompt, run, interrupt (opencode: packages/core/src/session.ts).

One run per session at a time. `prompt` only records the user's message; `resume` runs the session until it is idle (joining the run
already in flight, if any); `synthetic` records a system-originated message (a background command or subagent finishing) and, unless told
not to, wakes the session so the model sees it. `interrupt` cancels the run in flight."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from harness.schema import message as M
from harness.session.runner.runner import DrainResult, SessionRunner
from harness.session.store import SessionInfo, SessionStore


class SessionNotFoundError(Exception):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session not found: {session_id}")
        self.session_id = session_id


class SessionService:
    def __init__(self, store: SessionStore, runner: SessionRunner, directory: str) -> None:
        self.store, self.runner, self.directory = store, runner, directory
        self._runs: dict[str, asyncio.Task] = {}
        self._wakes: set[asyncio.Task] = set()

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
        info = self.store.create(directory or self.directory, agent=agent, model=model.model_dump(exclude_none=True) if model else None,
                                 parent_id=parent_id, title=title)
        return info

    def switch_agent(self, session_id: str, agent: str) -> None:
        info = self.get(session_id)
        self.store.add(session_id, M.AgentSelected(agent=agent, previous=info.agent))
        self.store.update(session_id, agent=agent)

    def switch_model(self, session_id: str, model: M.ModelRef) -> None:
        info = self.get(session_id)
        previous = M.ModelRef(**info.model) if info.model else None
        self.store.add(session_id, M.ModelSelected(model=model, previous=previous))
        self.store.update(session_id, model=model.model_dump(exclude_none=True))

    def messages(self, session_id: str, order: str = "asc", limit: Optional[int] = None) -> list[M.Info]:
        items = [m for _, m in self.store.messages(session_id)]
        if order == "desc":
            items.reverse()
        return items[:limit] if limit is not None else items

    def prompt(self, session_id: str, text: str) -> M.User:
        self.get(session_id)
        msg = M.User(text=text)
        self.store.add(session_id, msg)
        return msg

    def synthetic(self, session_id: str, text: str, description: Optional[str] = None, metadata: Optional[dict[str, Any]] = None,
                  resume: bool = True) -> M.Synthetic:
        self.get(session_id)
        msg = M.Synthetic(text=text, description=description, metadata=metadata)
        self.store.add(session_id, msg)
        if resume:
            self.wake(session_id)
        return msg

    # ------------------------------------------------------------------ running

    def running(self, session_id: str) -> bool:
        task = self._runs.get(session_id)
        return task is not None and not task.done()

    def _start(self, session_id: str) -> asyncio.Task:
        task = self._runs.get(session_id)
        if task is not None and not task.done():
            return task
        task = asyncio.ensure_future(self.runner.drain(session_id))
        self._runs[session_id] = task
        task.add_done_callback(lambda t, sid=session_id: self._runs.pop(sid, None) if self._runs.get(sid) is t else None)
        return task

    async def resume(self, session_id: str) -> DrainResult:
        """Runs the session to idle, or joins the run already in flight. Raises CancelledError if the run was interrupted."""
        self.get(session_id)
        return await asyncio.shield(self._start(session_id))

    def wake(self, session_id: str) -> None:
        """Starts the session if idle; a running session reads the new message on its next step."""
        if self.running(session_id):
            return
        task = asyncio.ensure_future(self._wake(session_id))
        self._wakes.add(task)
        task.add_done_callback(self._wakes.discard)

    async def _wake(self, session_id: str) -> None:
        try:
            await self.resume(session_id)
        except asyncio.CancelledError:
            pass

    async def interrupt(self, session_id: str) -> None:
        task = self._runs.get(session_id)
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 - the run records its own outcome
            pass

    async def close(self) -> None:
        for sid in list(self._runs):
            await self.interrupt(sid)
        for task in list(self._wakes):
            task.cancel()
