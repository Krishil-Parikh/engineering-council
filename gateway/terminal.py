"""A live terminal for every agent: what each developer is running and reading, as it happens, so clicking an agent in the browser shows its work.

The developers' harness reports every tool call (shell commands, file reads, searches, edits), whether it worked, and what the model said. They are turned into
short terminal lines here, kept per agent (the most recent few), and sent to the browser as the agent's `terminal` field."""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Optional

from gateway.logs import one_line
from gateway.narrator import agent_id

KEEP = 40  # lines kept per agent: enough to see what it just did, small enough to travel with every update
WIDTH = 200

FILE_TOOLS = {"write", "edit", "patch", "apply_patch", "multiedit", "create", "delete", "move"}


def describe_call(tool: str, data: dict[str, Any]) -> str:
    """One line for a tool call: `$ command` for the shell, `read path`, `glob pattern`, ..."""
    args = data.get("input") if isinstance(data.get("input"), dict) else {}
    if tool == "shell":
        return "$ " + one_line(args.get("command", ""), WIDTH)
    if tool == "read":
        where = args.get("path") or args.get("filePath") or ""
        start = args.get("startingLine")
        return f"read {where}" + (f":{start}" if start else "")
    if tool in ("glob", "grep", "search"):
        return f"{tool} {one_line(args.get('pattern') or args.get('query') or args, WIDTH)}"
    if tool in FILE_TOOLS:
        return f"{tool} {args.get('path') or args.get('filePath') or args.get('file') or ''}".rstrip()
    if tool == "skill":
        return f"skill {args.get('id', '')}".rstrip()
    return f"{tool or 'tool'} {one_line(args, WIDTH)}".rstrip()


class AgentTerminals:
    def __init__(self, keep: int = KEEP) -> None:
        self.keep = keep
        self.lines: dict[str, deque[str]] = {}
        self.tools: dict[str, str] = {}  # call id -> tool name (the name arrives before the input does)

    def note(self, who: str, text: str) -> list[str]:
        """A line the engine itself adds to an agent's terminal (a commit it made for it, a push). Returns the agent's lines."""
        buffer = self.lines.setdefault(agent_id(who), deque(maxlen=self.keep))
        buffer.append(f"{time.strftime('%H:%M:%S')} {text}")
        return list(buffer)

    def feed(self, who: str, event: str, data: dict[str, Any]) -> Optional[list[str]]:
        """Takes one harness event of agent `who`. Returns the agent's terminal lines when the event added something, else None."""
        if event == "tool.input.started":
            self.tools[data.get("call", "")] = str(data.get("tool") or "")
            return None
        added: list[str] = []
        if event == "tool.called":
            added.append(describe_call(self.tools.get(data.get("call", ""), ""), data))
        elif event == "tool.failed":
            added.append("! " + one_line(data.get("error", "the tool failed"), WIDTH))
        elif event == "shell.exited":
            code = data.get("exit")
            added.append(f"  exit {code}" if code is not None else "  finished")
        elif event == "text.ended":
            text = one_line(data.get("text", ""), WIDTH)
            if text:
                added.append("# " + text)
        elif event == "retry.scheduled":
            added.append("~ retrying: " + one_line(data.get("reason") or data.get("error") or data, 120))
        if not added:
            return None
        stamp = time.strftime("%H:%M:%S")
        buffer = self.lines.setdefault(agent_id(who), deque(maxlen=self.keep))
        for line in added:
            buffer.append(f"{stamp} {line}")
        return list(buffer)
