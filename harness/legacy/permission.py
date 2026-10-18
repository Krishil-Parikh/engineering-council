"""Rule-based permissions, modelled on opencode: a ruleset is an ordered list of (action, resource, effect) and the LAST
matching rule wins. `ask` pauses for a person; approvals can be remembered ("always") for the session or the project."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

Effect = Literal["allow", "deny", "ask"]


@dataclass(frozen=True)
class Rule:
    action: str
    resource: str
    effect: Effect


Ruleset = list[Rule]


def wildcard(text: str, pattern: str) -> bool:
    """`*` matches anything (including slashes), `?` one character. A trailing ` *` also matches the bare command,
    so `git status *` matches `git status`."""
    text = text.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    if pattern == "*":
        return True
    rx = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    if rx.endswith(r"\ .*"):
        rx = rx[: -len(r"\ .*")] + r"(?:\ .*)?"
    return re.fullmatch(rx, text, re.DOTALL) is not None


def evaluate(action: str, resource: str, *rulesets: Ruleset) -> Rule:
    found: Rule | None = None
    for rs in rulesets:
        for r in rs:
            if wildcard(action, r.action) and wildcard(resource, r.resource):
                found = r
    return found or Rule(action, "*", "ask")


def merge(*rulesets: Ruleset) -> Ruleset:
    return [r for rs in rulesets for r in rs]


class PermissionDenied(Exception):
    """A rule denied the action, or a person declined it."""

    def __init__(self, message: str, feedback: str = "") -> None:
        super().__init__(message)
        self.feedback = feedback


Asker = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
"""Receives {action, resources, save, metadata} and returns {"reply": "once"|"always"|"reject", "message": str}."""


class Permissions:
    """Evaluates rules for one agent and remembers approvals. `asker=None` means nobody is there to answer, so every
    `ask` becomes a denial that tells the model what was refused."""

    def __init__(self, asker: Asker | None = None, store: Path | None = None) -> None:
        self.asker = asker
        self.store = store
        self._session: Ruleset = []
        self._project: Ruleset = self._load()
        self._lock = asyncio.Lock()  # one question at a time, however many tools ask together

    def _load(self) -> Ruleset:
        if not self.store or not self.store.exists():
            return []
        try:
            return [Rule(**r) for r in json.loads(self.store.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            return []

    def _save(self) -> None:
        if not self.store:
            return
        try:
            self.store.parent.mkdir(parents=True, exist_ok=True)
            self.store.write_text(json.dumps([r.__dict__ for r in self._project], indent=1), encoding="utf-8")
        except OSError:
            pass

    def check(self, action: str, resource: str, rules: Ruleset) -> Rule:
        return evaluate(action, resource, rules, self._project, self._session)

    async def assert_(
        self, action: str, resources: list[str], rules: Ruleset, *, save: list[str] | None = None, metadata: dict[str, Any] | None = None,
    ) -> None:
        """Raise PermissionDenied unless every resource is allowed (asking when a rule says `ask`)."""
        pending: list[str] = []
        for res in resources:
            rule = self.check(action, res, rules)
            if rule.effect == "deny":
                raise PermissionDenied(f"Permission denied by rule: {action} {res}")
            if rule.effect == "ask":
                pending.append(res)
        if not pending:
            return
        if self.asker is None:
            raise PermissionDenied(
                f"Approval needed for {action}: {', '.join(pending)}. No one is available to approve it, so it was not run. "
                "Choose another way or tell the user what needs their approval."
            )
        async with self._lock:
            pending = [r for r in pending if self.check(action, r, rules).effect == "ask"]  # an earlier "always" may cover it
            if not pending:
                return
            answer = await self.asker({"action": action, "resources": pending, "save": save or pending, "metadata": metadata or {}})
            reply = answer.get("reply", "reject")
            if reply == "reject":
                msg = answer.get("message", "")
                raise PermissionDenied(f"The user declined {action}: {', '.join(pending)}" + (f". Feedback: {msg}" if msg else ""), msg)
            if reply == "always":
                for pattern in save or pending:
                    rule = Rule(action, pattern, "allow")
                    self._session.append(rule)
                    self._project.append(rule)
                self._save()
            elif reply == "session":
                self._session.extend(Rule(action, p, "allow") for p in save or pending)
