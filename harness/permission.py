"""Permissions (opencode: packages/core/src/permission.ts).

A ruleset is an ordered list of (action, resource, effect); the LAST matching rule wins and nothing matching means `ask`.
`assert_` is called by a tool before it does something: a denying rule blocks it, an allowing rule lets it through, and `ask`
suspends the tool until a person replies (once / always / reject). `always` is remembered per project in the database and also
approves any other pending request it now covers. A rejection with feedback becomes a CorrectedError so the model can adjust."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Optional

from harness.db.database import Database
from harness.schema.permission import Effect, Reply, Request, Rule, Ruleset
from harness.util import wildcard

MISSING_AGENT_PERMISSIONS: Ruleset = [Rule("*", "*", "deny")]


class DeclinedError(Exception):
    """The user said no."""


class CorrectedError(Exception):
    """The user said no and told the agent what to do instead."""

    def __init__(self, feedback: str) -> None:
        super().__init__(feedback)
        self.feedback = feedback


class BlockedError(Exception):
    """A rule denies the action."""

    def __init__(self, rules: Ruleset, permission: str, resources: list[str], reason: Optional[str] = None) -> None:
        super().__init__(reason or f"Permission denied: {permission}")
        self.rules, self.permission, self.resources, self.reason = rules, permission, resources, reason


class NotFoundError(Exception):
    def __init__(self, request_id: str) -> None:
        super().__init__(f"Permission request not found: {request_id}")
        self.request_id = request_id


def evaluate(action: str, resource: str, *rulesets: Ruleset) -> Rule:
    found: Optional[Rule] = None
    for rs in rulesets:
        for rule in rs:
            if wildcard.match(action, rule.action) and wildcard.match(resource, rule.resource):
                found = rule
    return found or Rule(action, "*", "ask")


def merge(*rulesets: Ruleset) -> Ruleset:
    return [r for rs in rulesets for r in rs]


class _Pending:
    def __init__(self, request: Request, agent: Optional[str]) -> None:
        self.request = request
        self.agent = agent
        self.future: asyncio.Future[None] = asyncio.get_event_loop().create_future()


class PermissionSaved:
    """Approvals the user chose to remember ("always"), per project."""

    def __init__(self, db: Database, project: str) -> None:
        self.db, self.project = db, project

    def list(self) -> Ruleset:
        rows = self.db.all("select action, resource from permission_saved where project = ?", (self.project,))
        return [Rule(r["action"], r["resource"], "allow") for r in rows]

    def add(self, action: str, resources: list[str]) -> None:
        for resource in resources:
            self.db.execute("insert or ignore into permission_saved (project, action, resource, effect) values (?,?,?, 'allow')", (self.project, action, resource))


RulesFor = Callable[[str, Optional[str]], Ruleset]  # (session_id, agent_id) -> rules for that session and agent
Observer = Callable[[str, dict[str, Any]], None]
Hook = Callable[[dict[str, Any]], None]


class Permission:
    def __init__(self, saved: PermissionSaved, rules_for: RulesFor, observer: Optional[Observer] = None, evaluate_hook: Optional[Hook] = None) -> None:
        self.saved = saved
        self.rules_for = rules_for
        self.observer = observer
        self.evaluate_hook = evaluate_hook  # may change {"effect", "message"} (opencode: the "permission.evaluate" plugin hook)
        self._pending: dict[str, _Pending] = {}
        self._closed = False

    def _emit(self, kind: str, **data: Any) -> None:
        if self.observer:
            self.observer(kind, data)

    # ---- evaluation
    @staticmethod
    def _denied(action: str, resources: list[str], rules: Ruleset) -> bool:
        return any(evaluate(action, r, rules).effect == "deny" for r in resources)

    def _evaluate_input(
        self, session_id: str, action: str, resources: list[str], agent: Optional[str], metadata: dict[str, Any], source: Any
    ) -> tuple[Effect, Optional[str], Ruleset]:
        rules = self.rules_for(session_id, agent)
        if self._denied(action, resources, rules):
            return "deny", None, rules
        allrules = [*rules, *self.saved.list()]
        effects = [evaluate(action, r, allrules).effect for r in resources]
        effect: Effect = "ask" if "ask" in effects else "allow"
        event: dict[str, Any] = {
            "sessionID": session_id, "agent": agent, "action": action, "resources": resources, "metadata": metadata, "source": source,
            "effect": effect, "message": None,
        }
        if self.evaluate_hook:
            self.evaluate_hook(event)
        return event["effect"], event["message"], allrules

    def _create(self, request: Request, agent: Optional[str]) -> _Pending:
        item = _Pending(request, agent)
        if self._closed:
            item.future.set_exception(DeclinedError())
            item.future.exception()  # mark retrieved
            return item
        if request.id in self._pending:
            raise RuntimeError(f"Duplicate pending permission ID: {request.id}")
        self._pending[request.id] = item
        self._emit("permission.asked", request=request)
        return item

    # ---- API
    async def assert_(
        self, *, session_id: str, action: str, resources: list[str], agent: Optional[str] = None, save: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None, source: Optional[dict[str, Any]] = None, id: Optional[str] = None,
    ) -> None:
        """Raise BlockedError if denied, DeclinedError/CorrectedError if the user says no; return when allowed."""
        if self._closed:
            raise DeclinedError()
        effect, message, rules = self._evaluate_input(session_id, action, resources, agent, metadata or {}, source)
        if effect == "deny":
            raise BlockedError([r for r in rules if wildcard.match(action, r.action)], action, resources, message)
        if effect == "allow":
            return
        item = self._create(Request(id or "per_" + os.urandom(8).hex(), session_id, action, resources, save, metadata or {}, source, message), agent)
        try:
            await item.future
        finally:
            self._pending.pop(item.request.id, None)

    def ask(self, *, session_id: str, action: str, resources: list[str], agent: Optional[str] = None, save: Optional[list[str]] = None,
            metadata: Optional[dict[str, Any]] = None, source: Optional[dict[str, Any]] = None, id: Optional[str] = None) -> dict[str, Any]:
        """Evaluate and, when it needs an answer, register the request without waiting for it."""
        rid = id or "per_" + os.urandom(8).hex()
        if self._closed:
            return {"id": rid, "effect": "deny"}
        effect, message, _ = self._evaluate_input(session_id, action, resources, agent, metadata or {}, source)
        if effect == "ask":
            self._create(Request(rid, session_id, action, resources, save, metadata or {}, source, message), agent)
        return {"id": rid, "effect": effect}

    def reply(self, request_id: str, reply: Reply, message: Optional[str] = None) -> None:
        existing = self._pending.get(request_id)
        if existing is None:
            raise NotFoundError(request_id)
        self._emit("permission.replied", sessionID=existing.request.session_id, requestID=request_id, reply=reply)
        if reply == "reject":
            self._fail(existing, CorrectedError(message) if message else DeclinedError())
            # Feedback applies to the whole batch, so parallel asks of the same session do not end the step one by one.
            for rid, item in list(self._pending.items()):
                if item.request.session_id != existing.request.session_id:
                    continue
                self._emit("permission.replied", sessionID=item.request.session_id, requestID=rid, reply="reject")
                self._fail(item, CorrectedError(message) if message else DeclinedError())
            return
        if reply == "always" and existing.request.save:
            self.saved.add(existing.request.action, existing.request.save)
        self._succeed(existing)
        if reply != "always" or not existing.request.save:
            return
        for rid, item in list(self._pending.items()):  # other pending asks the new rule now covers
            effect, _, _ = self._evaluate_input(item.request.session_id, item.request.action, item.request.resources, item.agent, item.request.metadata, item.request.source)
            if effect != "allow":
                continue
            self._emit("permission.replied", sessionID=item.request.session_id, requestID=rid, reply="always")
            self._succeed(item)

    def _succeed(self, item: _Pending) -> None:
        if not item.future.done():
            item.future.set_result(None)
        self._pending.pop(item.request.id, None)

    def _fail(self, item: _Pending, error: Exception) -> None:
        if not item.future.done():
            item.future.set_exception(error)
            item.future.exception()  # the awaiting tool receives it; avoid "never retrieved" noise if nobody is waiting
        self._pending.pop(item.request.id, None)

    def get(self, request_id: str) -> Optional[Request]:
        item = self._pending.get(request_id)
        return item.request if item else None

    def for_session(self, session_id: str) -> list[Request]:
        return [i.request for i in self._pending.values() if i.request.session_id == session_id]

    def list(self) -> list[Request]:
        return [i.request for i in self._pending.values()]

    def close(self) -> None:
        self._closed = True
        for item in list(self._pending.values()):
            self._emit("permission.replied", sessionID=item.request.session_id, requestID=item.request.id, reply="reject")
            self._fail(item, DeclinedError())
        self._pending.clear()
