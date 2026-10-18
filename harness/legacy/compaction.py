"""Conversation memory: keep the context under the model's window by clearing stale tool output and, when that is not enough,
replacing the oldest part of the conversation with a structured checkpoint written by the model (opencode's design)."""

from __future__ import annotations

import json
from typing import Callable

from harness.legacy.session import Session
from harness.legacy.types import ChatModel, Event, Message, ModelError, Observer

RESERVE_MIN = 16_000  # window kept free for the next reply and for the summary itself
TOOL_OUTPUT_MAX_CHARS = 1_250
PRUNE_PROTECT_TOKENS = 40_000  # the newest tool output is never pruned
CLEARED = "[Old tool output cleared to save context. Re-run the tool if you need it.]"

SUMMARY_TEMPLATE = """You MUST use this format for your response (you may omit sections that aren't applicable). Do not include the <template> tags in your response.
<template>
## Objective
- [one or two brief sentences describing what the user is trying to accomplish]

## Requirements
- [constraints, preferences, requirements and scope boundaries stated by the user, or "(none)"]

## Decisions
- [decisions already made and why, or "(none)"]

## Work State
Break the objective into smaller goals and report which are completed, which are being worked on, and which are blocked.
### Completed
- [goals that have been completed; otherwise "(none)"]

### Active
- [goals currently being worked on; otherwise "(none)"]

### Blocked
- [anything blocking progress, and why; otherwise "(none)"]

## Next Move
1. [ordered list of next actions, or "(none)"]

## Relevant Files
List the files and directories another agent would need to open to continue. At most 15, most important first. If none, write "(none)".
- `[file or directory path]`: [brief reason it matters]

## Important Context
- [facts the next agent cannot continue without and cannot easily find on its own; or "(none)"]
</template>"""

SUMMARY_RULES = """Rules:
- Keep each section concise. Use terse single-line bullets, not prose paragraphs or nested lists.
- Prefer short references over detailed restatement. It is fine to leave out information the next agent can recover from the code or the files listed above.
- Preserve exact file paths, symbols, commands, error strings, URLs and identifiers.
- Carry forward only user questions or requests that remain unanswered or require further action.
- Preserve consequential workflow state, including whether changes are uncommitted, committed, pushed, under review or merged.
- Do not mention the summary process or that context was compacted."""


def build_prompt(update: bool) -> str:
    shared = [
        "Summarize only what the user and the assistant said and did. Leave out instructions and setup the assistant was given rather than "
        "told by the user: repository conventions, instruction files such as AGENTS.md, and environment details. The next agent receives current versions of those separately.",
        SUMMARY_TEMPLATE, SUMMARY_RULES, "Do not continue the task or call tools.",
        "Return only the structured summary in the requested format. Do not include a preamble, explanation or other commentary.",
    ]
    if update:
        head = [
            "Update the existing checkpoint in the conversation above into one consolidated summary.",
            "Newer history always takes precedence over the existing checkpoint. Preserve previous information unless newer history clearly contradicts, "
            "supersedes, resolves or makes it stale. Reconcile Work State and Next Move: move completed work out of Active, remove resolved blockers "
            "and answered questions, and preserve unresolved or pending work.",
        ]
    else:
        head = ["You MUST summarize the conversation above into a structured summary that will be given to another agent to resume the work."]
    return "\n\n".join(head + shared)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def message_tokens(m: Message) -> int:
    n = estimate_tokens(m.text) + 4
    for c in m.tool_calls:
        n += estimate_tokens(c.name + json.dumps(c.args, default=str))
    return n


def render_for_summary(messages: list[Message]) -> str:
    out = []
    for m in messages:
        if m.role == "user":
            out.append(f"[user]{' (harness note)' if m.synthetic and m.kind != 'summary' else ''}\n{m.text}")
        elif m.role == "assistant":
            if m.text.strip():
                out.append(f"[assistant]\n{m.text}")
            for c in m.tool_calls:
                out.append(f"[assistant called {c.name}] {json.dumps(c.args, default=str)[:400]}")
        else:
            body = m.text if len(m.text) <= TOOL_OUTPUT_MAX_CHARS else m.text[:TOOL_OUTPUT_MAX_CHARS] + "\n...(truncated)"
            out.append(f"[{m.tool_name or 'tool'} result{' - error' if m.is_error else ''}]\n{body}")
    return "\n\n".join(out)


class Compactor:
    def __init__(self, model: ChatModel, *, window: int = 200_000, keep: int = 15_000, auto: bool = True, max_output: int = 16_384) -> None:
        self.model, self.window, self.keep, self.auto, self.max_output = model, window, keep, auto, max_output

    def limit(self) -> int:
        return self.window - max(RESERVE_MIN, self.max_output)

    def context_size(self, session: Session, system: str, last_input_tokens: int | None) -> int:
        est = estimate_tokens(system) + sum(message_tokens(m) for m in session.active())
        return max(est, last_input_tokens or 0) if last_input_tokens else est

    def prune(self, session: Session) -> int:
        """Clear the content of old tool results (all but the newest ~40k tokens of them). Returns tokens freed."""
        protected, freed = 0, 0
        for m in reversed(session.active()):
            if m.role != "tool" or m.text == CLEARED:
                continue
            t = estimate_tokens(m.text)
            protected += t
            if protected > PRUNE_PROTECT_TOKENS and t > 200:
                freed += t
                m.text = CLEARED
        if freed:
            session.rewrite()
        return freed

    async def maybe_compact(self, session: Session, system: str, last_input_tokens: int | None, emit: Observer | None) -> bool:
        if not self.auto or self.context_size(session, system, last_input_tokens) < self.limit():
            return False
        self.prune(session)
        if self.context_size(session, system, None) < self.limit():
            if emit:
                emit(Event("compaction", {"mode": "prune"}))
            return True
        return await self.compact(session, emit=emit)

    def _split(self, active: list[Message], keep_tokens: int) -> int:
        """Index where the kept tail starts. The tail never begins with a tool result (it would lose its call)."""
        total, idx = 0, len(active)
        while idx > 0 and total < keep_tokens:
            idx -= 1
            total += message_tokens(active[idx])
        while idx > 0 and active[idx].role == "tool":
            idx -= 1
        return max(idx, 0)

    async def compact(self, session: Session, *, emit: Observer | None = None, shrink: float | None = None) -> bool:
        active = session.active()
        keep = int(self.keep * shrink) if shrink else self.keep
        cut = self._split(active, keep)
        head, tail = active[:cut], active[cut:]
        if not head or not any(m.kind != "summary" for m in head):
            return False
        previous = next((m for m in reversed(head) if m.kind == "summary"), None)
        history = render_for_summary([m for m in head if m.kind != "summary"])
        body = (f"<previous-checkpoint>\n{previous.text}\n</previous-checkpoint>\n\n" if previous else "") + f"<conversation>\n{history}\n</conversation>"
        if emit:
            emit(Event("compaction", {"mode": "summarize", "messages": len(head)}))
        prompt = Message("compact_prompt", "user", body + "\n\n" + build_prompt(update=previous is not None), synthetic=True)
        summary = ""
        for attempt in range(2):
            msgs = [prompt] if attempt == 0 else [prompt, Message("c2", "assistant", summary), Message("c3", "user", "The previous response did not fill in the required summary template. Do not call tools. Return the summary as text using the exact section headings from the template.", synthetic=True)]
            try:
                reply = await self.model.complete(system="You write precise handoff summaries of coding sessions.", messages=msgs, tools=[], tool_choice="none", stage="compaction", max_output_tokens=4096)
            except ModelError:
                return False
            summary = reply.text.strip()
            if "## Objective" in summary:
                break
        else:
            return False
        for m in head:
            m.compacted = True
        marker = Message(
            session.next_message_id(), "user", "<conversation-checkpoint>\n<summary>\n" + summary + "\n</summary>\n</conversation-checkpoint>\n"
            "Earlier parts of this conversation were compacted into the summary above. Continue the work from it.",
            synthetic=True, kind="summary",
        )
        position = session.messages.index(tail[0]) if tail else len(session.messages)
        session.messages.insert(position, marker)
        session.rewrite()
        session.save_meta()
        if emit:
            emit(Event("compaction", {"mode": "done", "summary_tokens": estimate_tokens(summary)}))
        return True
