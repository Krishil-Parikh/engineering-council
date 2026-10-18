"""Instruction sources (opencode: packages/core/src/instructions/index.ts).

An instruction source reads one piece of context (the date, the environment, a file of project rules, the skill list) and
knows how to render it the first time, when it changes, and when it disappears. Sources are ordered and combined; the
engine stores a hash of each value per session so it can tell what changed since the model last saw it."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Generic, Mapping, Optional, TypeVar, Union

A = TypeVar("A")
Json = Any
Hash = str
REMOVED_MARK = "removed"  # delta value meaning "this key was removed"


class _NonValue:
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"<{self.name}>"


UNAVAILABLE = _NonValue("unavailable")  # the read failed temporarily; the stored value stands
REMOVED = _NonValue("removed")  # an observed absence: the source exists but its value is gone
DECODE_FAILED = _NonValue("decode-failed")  # a stored value no longer decodes (JSON null is a valid value, so None cannot mean this)


class InitializationBlocked(Exception):
    def __init__(self, keys: list[str]) -> None:
        super().__init__(f"Instruction initialization blocked by unavailable sources: {', '.join(keys)}")
        self.keys = keys


class DuplicateKeyError(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(f"Duplicate instruction key: {key}")
        self.key = key


@dataclass
class Source:
    """One composable instruction source over canonical JSON (the representation that is hashed, stored and replayed)."""

    key: str
    read: Callable[[], Union[Json, _NonValue]]
    initial: Callable[[Json], Optional[str]]
    changed: Callable[[Json, Json], Optional[str]]
    removed: Callable[[Json], Optional[str]]


List = list[Source]


@dataclass
class Definition(Generic[A]):
    key: str
    read: Callable[[], Union[A, _NonValue]]
    render_initial: Callable[[A], str]
    render_changed: Callable[[A, A], str]
    render_removed: Optional[Callable[[A], str]] = None
    # codec: encode a typed value to JSON-compatible data, decode it back (None = value already JSON)
    encode: Callable[[A], Json] = staticmethod(lambda v: v)  # type: ignore[assignment]
    decode: Callable[[Json], Any] = staticmethod(lambda v: v)  # return DECODE_FAILED for undecodable data


def _require_text(key: str, kind: str, text: str) -> str:
    if len(text) == 0:
        raise ValueError(f"Instruction source {key} rendered an empty {kind}")
    return text


def make(defn: Definition[A]) -> List:
    """Close a typed definition into one Source so differently typed sources compose."""

    def read() -> Union[Json, _NonValue]:
        value = defn.read()
        if value is UNAVAILABLE or value is REMOVED:
            return value
        return defn.encode(value)  # type: ignore[arg-type]

    def initial(value: Json) -> Optional[str]:
        decoded = defn.decode(value)
        return None if decoded is DECODE_FAILED else _require_text(defn.key, "initial", defn.render_initial(decoded))

    def changed(previous: Json, current: Json) -> Optional[str]:
        before, after = defn.decode(previous), defn.decode(current)
        if after is DECODE_FAILED:
            return None
        if before is DECODE_FAILED:
            return _require_text(defn.key, "initial", defn.render_initial(after))
        return _require_text(defn.key, "changed", defn.render_changed(before, after))

    def removed(previous: Json) -> Optional[str]:
        decoded = defn.decode(previous)
        if decoded is DECODE_FAILED or defn.render_removed is None:
            return None
        return _require_text(defn.key, "removed", defn.render_removed(decoded))

    return [Source(defn.key, read, initial, changed, removed)]


def combine(values: list[List]) -> List:
    sources = [s for lst in values for s in lst]
    seen: set[str] = set()
    for s in sources:
        if s.key in seen:
            raise DuplicateKeyError(s.key)
        seen.add(s.key)
    return sources


ReadResult = list[tuple[str, Union[Json, _NonValue]]]


def read(value: List) -> ReadResult:
    return [(s.key, s.read()) for s in value]


@dataclass
class Admission:
    delta: dict[str, str]  # key -> hash, or REMOVED_MARK
    blobs: dict[str, Json]  # hash -> value


def diff(observed: ReadResult, previous: Optional[Mapping[str, Hash]] = None) -> Admission:
    blocked = [] if previous is not None else [k for k, v in observed if v is UNAVAILABLE]
    if blocked:
        raise InitializationBlocked(blocked)
    delta: dict[str, str] = {}
    blobs: dict[str, Json] = {}
    for key, value in observed:
        if value is UNAVAILABLE:
            continue
        if value is REMOVED:
            if previous is not None and key in previous:
                delta[key] = REMOVED_MARK
            continue
        nxt = hash_value(value)
        if previous is not None and previous.get(key) == nxt:
            continue
        delta[key] = nxt
        blobs[nxt] = value
    return Admission(delta, blobs)


def render_initial(value: List, values: Mapping[str, Json]) -> str:
    parts = []
    for s in value:
        if s.key in values:
            text = s.initial(values[s.key])
            if text is not None:
                parts.append(text)
    return "\n\n".join(parts)


def render_update(value: List, previous: Mapping[str, Json], delta: Mapping[str, Json]) -> str:
    """delta maps key -> the new value, or REMOVED when the source disappeared (JSON null is a value, not a removal)."""
    parts = []
    for s in value:
        if s.key not in delta:
            continue
        current = delta[s.key]
        if current is REMOVED:
            text = s.removed(previous[s.key]) if s.key in previous else None
        elif s.key in previous:
            text = s.changed(previous[s.key], current)
        else:
            text = s.initial(current)
        if text is not None:
            parts.append(text)
    return "\n\n".join(parts)


def canonical(value: Json) -> str:
    if isinstance(value, list):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(f"{json.dumps(k, ensure_ascii=False)}:{canonical(value[k])}" for k in sorted(value)) + "}"
    return json.dumps(value, ensure_ascii=False)


def hash_value(value: Json) -> Hash:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def apply_hash_delta(values: Mapping[str, Hash], delta: Mapping[str, str]) -> dict[str, Hash]:
    result = dict(values)
    for key, value in delta.items():
        if value == REMOVED_MARK:
            result.pop(key, None)
        else:
            result[key] = value
    return result


def diff_by_key(previous: list[Any], current: list[Any], key: Callable[[Any], str], changed: Callable[[Any, Any], bool]) -> dict[str, list[Any]]:
    current_keys = {key(v) for v in current}
    previous_by_key = {key(v): v for v in previous}
    return {
        "added": [v for v in current if key(v) not in previous_by_key],
        "removed": [v for v in previous if key(v) not in current_keys],
        "changed": [{"previous": previous_by_key[key(v)], "current": v} for v in current if key(v) in previous_by_key and changed(previous_by_key[key(v)], v)],
    }


empty: List = []
