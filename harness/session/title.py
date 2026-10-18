"""Naming sessions (opencode: packages/core/src/session/title.ts).

A new conversation has no title. Once it has something to talk about, the hidden `title` agent is asked, in a separate tool-less request, for a
short title from the first user message. An existing title can also be regenerated from the original request plus the recent conversation
(bounded, so a long session costs the same as a short one).

Care taken so a title never overwrites a person's choice: the title is applied only if the session still has the title it had when generation
began, so a manual rename that lands while the model is thinking wins. A failed or empty answer changes nothing and can simply be retried.

Deviation: opencode also records the title request's token usage on the session and falls back to the primary model if a small model fails;
we use the session's own model and do not record usage."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Callable, Optional

from harness.ai import events as E
from harness.ai import types as T
from harness.schema import message as M
from harness.session.store import SessionInfo, SessionStore

MAX_LENGTH = 100
MAX_CONTEXT_LENGTH = 8_000
MAX_FIRST_MESSAGE_LENGTH = 2_000
_FALLBACK = re.compile(r"^(New session|Child session) - \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def truncate(value: str) -> str:
    return value if len(value) <= MAX_LENGTH else value[: MAX_LENGTH - 3] + "..."


def is_untitled(session: SessionInfo) -> bool:
    """No title, or a placeholder title such as 'New session - 2026-10-18T12:00:00.000Z'."""
    return not session.title or bool(_FALLBACK.match(session.title))


def first_user_message(messages: list[M.Info]) -> Optional[M.User]:
    return next((m for m in messages if isinstance(m, M.User)), None)


def regeneration_context(messages: list[M.Info], first: M.User) -> str:
    """The original request, then as much of the recent conversation as fits, newest kept."""
    original = f"Original request:\n{first.text[:MAX_FIRST_MESSAGE_LENGTH]}"
    lines: list[str] = []
    for m in messages:
        if isinstance(m, M.User) and m.id != first.id:
            lines.append(f"User: {m.text.strip()}")
        elif isinstance(m, M.Assistant):
            text = "\n".join(p.text.strip() for p in m.content if isinstance(p, M.AssistantText) and p.text.strip())
            if text:
                lines.append(f"Assistant: {text}")
    recent = "\n\n".join(lines)
    if not recent:
        return original
    prefix = f"{original}\n\nRecent conversation:\n"
    return prefix + recent[-(MAX_CONTEXT_LENGTH - len(prefix)):]


class SessionTitle:
    def __init__(self, store: SessionStore, llm: Any, agents: Any, resolve_model: Callable[[SessionInfo], Any], on_event: Optional[Callable[[str, dict], None]] = None) -> None:
        self.store, self.llm, self.agents, self.resolve_model = store, llm, agents, resolve_model
        self.on_event = on_event or (lambda kind, data: None)
        self._running: dict[str, asyncio.Task] = {}

    async def _attempt(self, agent: Any, text: str) -> Optional[str]:
        request = T.LLMRequest(
            system=[T.SystemPart(agent.system)] if agent.system else [], messages=[T.Message.user(text)], generation=T.Generation(max_tokens=200),
        )
        chunks: list[str] = []
        try:
            async for event in self.llm.stream(request):
                if isinstance(event, E.ProviderError):
                    return None
                if isinstance(event, E.TextDelta):
                    chunks.append(event.text)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a title is a nicety; any failure leaves the session as it was
            return None
        return next((line.strip() for line in "".join(chunks).split("\n") if line.strip()), None)

    async def generate(self, session_id: str) -> Optional[str]:
        """Generates or regenerates the title. Returns the new title, or None when nothing was changed."""
        session = self.store.get(session_id)
        if session is None:
            return None
        messages = [m for _, m in self.store.messages(session_id)]
        first = first_user_message(messages)
        if first is None:
            return None
        agent = self.agents.get("title")
        if agent is None:
            return None  # the title agent was removed: titles are switched off
        text = first.text if is_untitled(session) else regeneration_context(messages, first)
        title = await self._attempt(agent, text)
        if not title:
            return None
        title = truncate(title)
        current = self.store.get(session_id)
        if current is None or current.title != session.title or current.title == title:
            return None  # renamed meanwhile (a person's choice wins), or already that
        self.store.update(session_id, title=title)
        self.on_event("session.renamed", {"sessionID": session_id, "title": title})
        return title

    def start(self, session_id: str) -> None:
        """Background generation, at most one per session at a time."""
        task = self._running.get(session_id)
        if task is not None and not task.done():
            return
        task = asyncio.ensure_future(self.generate(session_id))
        self._running[session_id] = task
        task.add_done_callback(lambda t, sid=session_id: (self._running.pop(sid, None), t.cancelled() or t.exception()))

    def when_input_arrives(self, session_id: str, count: int) -> None:
        """The runner's hook: name a new root conversation once it has input."""
        session = self.store.get(session_id)
        if session is not None and not session.parent_id and is_untitled(session) and count > 0:
            self.start(session_id)

    async def close(self) -> None:
        for task in list(self._running.values()):
            task.cancel()
        for task in list(self._running.values()):
            try:
                await task
            except BaseException:  # noqa: BLE001
                pass
