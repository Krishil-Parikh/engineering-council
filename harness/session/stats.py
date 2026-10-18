"""What a session (or all of them) used: messages, tokens, cost, which tools ran and how often they failed, which models answered (opencode: the
`stats` command). Everything is worked out from the stored messages and the session totals, so it is the same after a restart."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from harness.schema import message as M
from harness.session.store import SessionInfo, SessionStore


@dataclass
class ModelUse:
    messages: int = 0
    cost: float = 0.0
    input_tokens: float = 0
    output_tokens: float = 0


@dataclass
class ToolUse:
    calls: int = 0
    failures: int = 0


@dataclass
class Stats:
    sessions: int = 0
    child_sessions: int = 0
    user_messages: int = 0
    assistant_messages: int = 0
    steps_failed: int = 0
    cost: float = 0.0
    tokens: M.TokenUsage = field(default_factory=M.TokenUsage)
    tools: dict[str, ToolUse] = field(default_factory=dict)
    models: dict[str, ModelUse] = field(default_factory=dict)
    first: int = 0  # time of the oldest session (ms)
    last: int = 0

    @property
    def messages(self) -> int:
        return self.user_messages + self.assistant_messages

    @property
    def cost_per_session(self) -> float:
        return self.cost / self.sessions if self.sessions else 0.0

    @property
    def tokens_per_session(self) -> float:
        total = self.tokens.input + self.tokens.output + self.tokens.reasoning
        return total / self.sessions if self.sessions else 0.0


def _add_session(stats: Stats, store: SessionStore, info: SessionInfo) -> None:
    stats.sessions += 1
    stats.child_sessions += 1 if info.parent_id else 0
    stats.cost += info.cost
    for name in ("input", "output", "reasoning", "cache_read", "cache_write"):
        setattr(stats.tokens, name, getattr(stats.tokens, name) + getattr(info.tokens, name))
    stats.first = min(stats.first or info.time_created, info.time_created)
    stats.last = max(stats.last, info.time_updated)
    for _, m in store.messages(info.id):
        if isinstance(m, M.User):
            stats.user_messages += 1
        elif isinstance(m, M.Assistant):
            stats.assistant_messages += 1
            if m.error is not None:
                stats.steps_failed += 1
            key = f"{m.model.provider_id}/{m.model.id}"
            use = stats.models.setdefault(key, ModelUse())
            use.messages += 1
            use.cost += m.cost or 0.0
            if m.tokens is not None:
                use.input_tokens += m.tokens.input
                use.output_tokens += m.tokens.output
            for part in m.content:
                if isinstance(part, M.AssistantTool):
                    t = stats.tools.setdefault(part.name, ToolUse())
                    t.calls += 1
                    t.failures += 1 if part.state.status == "error" else 0


def collect(store: SessionStore, session_id: Optional[str] = None, directory: Optional[str] = None, days: Optional[int] = None, include_children: bool = True) -> Stats:
    """Statistics for one session (and its subagent sessions), or for every session, optionally of one directory and of the last `days` days."""
    stats = Stats()
    if session_id is not None:
        root = store.get(session_id)
        if root is None:
            return stats
        queue = [root]
        while queue:
            info = queue.pop(0)
            _add_session(stats, store, info)
            if include_children:
                queue.extend(store.children(info.id))
        return stats
    cutoff = int((time.time() - days * 86400) * 1000) if days else 0
    for info in store.list(directory):
        if info.time_updated < cutoff or (info.parent_id and not include_children):
            continue
        _add_session(stats, store, info)
    return stats


def render(stats: Stats, top_tools: int = 10) -> str:
    """The numbers as a readable block of text."""
    if not stats.sessions:
        return "No sessions."
    t = stats.tokens
    lines = [
        f"Sessions   {stats.sessions} ({stats.child_sessions} subagent)",
        f"Messages   {stats.messages} ({stats.user_messages} yours, {stats.assistant_messages} steps; {stats.steps_failed} failed)",
        f"Cost       ${stats.cost:.4f}  (${stats.cost_per_session:.4f} per session)",
        f"Tokens     {int(t.input):,} in · {int(t.output):,} out · {int(t.reasoning):,} reasoning · {int(t.cache_read):,} cache read · {int(t.cache_write):,} cache write",
    ]
    if stats.models:
        lines.append("Models")
        lines += [f"  {name}: {u.messages} steps, {int(u.input_tokens):,} in / {int(u.output_tokens):,} out, ${u.cost:.4f}" for name, u in sorted(stats.models.items(), key=lambda kv: -kv[1].messages)]
    if stats.tools:
        lines.append("Tools")
        for name, u in sorted(stats.tools.items(), key=lambda kv: -kv[1].calls)[:top_tools]:
            lines.append(f"  {name}: {u.calls} call(s)" + (f", {u.failures} failed" if u.failures else ""))
    return "\n".join(lines)
