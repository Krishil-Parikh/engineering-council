"""Forms: structured questions put to the user and answered later (opencode: packages/core/src/form.ts, schema/form.ts).

A form is a list of fields (dicts with `key`, `type` and the type's options). `ask` registers the form and waits for the terminal state:
{"status": "answered", "answer": {...}} or {"status": "cancelled", "message"?}. Fields can depend on earlier answers through `when`
conditions; inactive fields are neither required nor answerable. Settled forms stay readable for ten minutes."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from harness.schema.message import ascending

RETENTION_SECONDS = 10 * 60
Field = dict[str, Any]


class FormError(Exception):
    pass


class NotFoundError(FormError):
    def __init__(self, id: str) -> None:
        super().__init__(f"Form not found: {id}")
        self.id = id


class AlreadySettledError(FormError):
    def __init__(self, id: str) -> None:
        super().__init__(f"Form already settled: {id}")
        self.id = id


class AlreadyExistsError(FormError):
    def __init__(self, id: str) -> None:
        super().__init__(f"Form already exists: {id}")
        self.id = id


class InvalidAnswerError(FormError):
    def __init__(self, id: str, message: str) -> None:
        super().__init__(message)
        self.id = id


class InvalidFormError(FormError):
    pass


def new_id() -> str:
    return "frm_" + ascending()


# ------------------------------------------------------------------ validation

def _matches(when: dict[str, Any], value: Any) -> bool:
    if value is None:
        return False  # an unanswered referenced field makes the condition false for both ops
    hit = any(item == when["value"] for item in value) if isinstance(value, list) else value == when["value"]
    return hit if when["op"] == "eq" else not hit


def _active(field: Field, answer: dict[str, Any]) -> bool:
    return all(_matches(w, answer.get(w["key"])) for w in field.get("when") or [])


def validate_fields(fields: list[Field]) -> Optional[str]:
    """Create-time checks: each condition must point at an earlier field and carry a value of that field's type."""
    if not fields:
        return "Form must have at least one field"
    earlier: dict[str, Field] = {}
    for field in fields:
        if field["key"] in earlier:
            return f"Duplicate form field key: {field['key']}"
        if field["type"] == "external":
            earlier[field["key"]] = field
            continue
        for when in field.get("when") or []:
            target = earlier.get(when["key"])
            if target is None:
                return f"Form field condition must reference an earlier field: {field['key']} -> {when['key']}"
            invalid = _validate_when(when, target)
            if invalid:
                return f"{invalid}: {field['key']} -> {when['key']}"
        earlier[field["key"]] = field
    return None


def _validate_when(when: dict[str, Any], target: Field) -> Optional[str]:
    value = when["value"]
    if target["type"] == "boolean":
        return None if isinstance(value, bool) else "Form field condition value must be a boolean"
    if target["type"] in ("number", "integer"):
        return None if isinstance(value, (int, float)) and not isinstance(value, bool) else "Form field condition value must be a number"
    if not isinstance(value, str):
        return "Form field condition value must be a string"
    closed = not target.get("custom") if target["type"] == "multiselect" else target.get("options") is not None and not target.get("custom")
    if closed and not any(o["value"] == value for o in target.get("options") or []):
        return "Form field condition value must be one of the field's options"
    return None


def _is_date(value: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") == value
    except ValueError:
        return False


def _is_date_time(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _is_uri(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme) and (bool(parsed.netloc) or bool(parsed.path))


def _validate_field(field: Field, value: Any) -> Optional[str]:
    key, kind = field["key"], field["type"]
    if kind == "string":
        if not isinstance(value, str):
            return f"Expected string for form field: {key}"
        if field.get("required") and not value:
            return f"Missing required form field: {key}"
        if field.get("minLength") is not None and len(value) < field["minLength"]:
            return f"Form field is too short: {key}"
        if field.get("maxLength") is not None and len(value) > field["maxLength"]:
            return f"Form field is too long: {key}"
        if field.get("pattern") is not None:
            try:
                if not re.search(field["pattern"], value):
                    return f"Form field does not match pattern: {key}"
            except re.error:
                return f"Form field has invalid pattern: {key}"
        fmt = field.get("format")
        if fmt == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            return f"Expected email for form field: {key}"
        if fmt == "uri" and not _is_uri(value):
            return f"Expected URI for form field: {key}"
        if fmt == "date" and not _is_date(value):
            return f"Expected date for form field: {key}"
        if fmt == "date-time" and not _is_date_time(value):
            return f"Expected date-time for form field: {key}"
        if field.get("options") and not field.get("custom") and not any(o["value"] == value for o in field["options"]):
            return f"Invalid option for form field: {key}"
        return None
    if kind in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
            return f"Expected number for form field: {key}"
        if kind == "integer" and int(value) != value:
            return f"Expected integer for form field: {key}"
        if field.get("minimum") is not None and value < field["minimum"]:
            return f"Form field is too small: {key}"
        if field.get("maximum") is not None and value > field["maximum"]:
            return f"Form field is too large: {key}"
        return None
    if kind == "boolean":
        return None if isinstance(value, bool) else f"Expected boolean for form field: {key}"
    if kind == "multiselect":
        if not isinstance(value, list) or not all(isinstance(i, str) for i in value):
            return f"Expected string array for form field: {key}"
        if field.get("required") and not value:
            return f"Missing required form field: {key}"
        if field.get("minItems") is not None and len(value) < field["minItems"]:
            return f"Too few selections for form field: {key}"
        if field.get("maxItems") is not None and len(value) > field["maxItems"]:
            return f"Too many selections for form field: {key}"
        if not field.get("custom") and any(not any(o["value"] == i for o in field["options"]) for i in value):
            return f"Invalid option for form field: {key}"
    return None


def validate_answer(fields: list[Field], answer: dict[str, Any]) -> Optional[str]:
    known = {f["key"]: f for f in fields}
    for key in answer:
        if key not in known:
            return f"Unknown form field: {key}"
    for field in fields:
        value = answer.get(field["key"])
        if field["type"] == "external":
            if value is not True:
                return f"External form field must be acknowledged: {field['key']}"
            continue
        active = _active(field, answer)
        if value is None:
            if field.get("required") and active:
                return f"Missing required form field: {field['key']}"
            continue
        if not active:
            return f"Form field is not active: {field['key']}"
        invalid = _validate_field(field, value)
        if invalid:
            return invalid
    return None


# ------------------------------------------------------------------ service

@dataclass
class _Entry:
    form: dict[str, Any]
    state: dict[str, Any]
    future: asyncio.Future
    settled_at: Optional[float] = None


class FormService:
    def __init__(self, on_event: Optional[Callable[[str, dict[str, Any]], None]] = None, clock: Callable[[], float] = time.monotonic) -> None:
        self._forms: dict[str, _Entry] = {}
        self._closed = False
        self._on_event = on_event or (lambda kind, data: None)
        self._clock = clock

    def _prune(self) -> None:
        now = self._clock()
        for id in [i for i, e in self._forms.items() if e.settled_at is not None and now - e.settled_at > RETENTION_SECONDS]:
            del self._forms[id]

    def _require(self, id: str) -> _Entry:
        self._prune()
        entry = self._forms.get(id)
        if entry is None:
            raise NotFoundError(id)
        return entry

    def create(self, session_id: str, title: str, fields: list[Field], metadata: Optional[dict[str, Any]] = None, id: Optional[str] = None) -> dict[str, Any]:
        self._prune()
        id = id or new_id()
        if id in self._forms:
            raise AlreadyExistsError(id)
        invalid = validate_fields(fields)
        if invalid:
            raise InvalidFormError(invalid)
        form: dict[str, Any] = {"id": id, "sessionID": session_id, "title": title, "fields": fields, **({"metadata": metadata} if metadata is not None else {})}
        self._forms[id] = _Entry(form, {"status": "pending"}, asyncio.get_running_loop().create_future())
        self._on_event("created", {"form": form})
        if self._closed:
            self.cancel(id)
        return form

    async def ask(self, session_id: str, title: str, fields: list[Field], metadata: Optional[dict[str, Any]] = None, id: Optional[str] = None) -> dict[str, Any]:
        form = self.create(session_id, title, fields, metadata, id)
        entry = self._require(form["id"])
        try:
            return await asyncio.shield(entry.future)
        except asyncio.CancelledError:
            if entry.state["status"] == "pending":
                self.cancel(form["id"])  # an interrupted asker takes its question back
            raise

    def get(self, id: str) -> dict[str, Any]:
        return self._require(id).form

    def list(self, session_id: Optional[str] = None) -> list[dict[str, Any]]:
        self._prune()
        return [e.form for e in self._forms.values() if e.state["status"] == "pending" and (session_id is None or e.form["sessionID"] == session_id)]

    def state(self, id: str) -> dict[str, Any]:
        return self._require(id).state

    def _settle(self, entry: _Entry, state: dict[str, Any]) -> None:
        entry.state = state
        entry.settled_at = self._clock()
        if not entry.future.done():
            entry.future.set_result(state)

    def reply(self, id: str, answer: dict[str, Any]) -> None:
        entry = self._require(id)
        if entry.state["status"] != "pending":
            raise AlreadySettledError(id)
        invalid = validate_answer(entry.form["fields"], answer)
        if invalid:
            raise InvalidAnswerError(id, invalid)
        self._on_event("replied", {"id": id, "sessionID": entry.form["sessionID"], "answer": answer})
        self._settle(entry, {"status": "answered", "answer": answer})

    def cancel(self, id: str, message: Optional[str] = None) -> None:
        entry = self._require(id)
        if entry.state["status"] != "pending":
            raise AlreadySettledError(id)
        self._on_event("cancelled", {"id": id, "sessionID": entry.form["sessionID"]})
        self._settle(entry, {"status": "cancelled", **({"message": message} if message is not None else {})})

    def close(self) -> None:
        self._closed = True
        for entry in list(self._forms.values()):
            if entry.state["status"] == "pending":
                self.cancel(entry.form["id"])
