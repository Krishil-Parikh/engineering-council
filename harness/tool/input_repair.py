"""Repairing a model's tool input (opencode: packages/core/src/plugin/tool-input-repair.ts).

Models often get the *shape* of tool arguments slightly wrong: a number sent as the string "20", an object sent as a JSON string, `null` for an
omitted option, a single value where a list is expected. When the tool's own input schema makes the intended meaning unambiguous, the input is
corrected before it is validated, so the model does not waste a step on "invalid arguments". Where the schema leaves any doubt (unions that
could mean either, compositions, enums, references that cannot be followed) the input is left exactly as it came.

What is repaired, always without touching the original input:
  - a stringified object or array, at the root or nested:        '{"limit":"20"}'          -> {"limit": 20}
  - numeric and boolean strings:                                  {"limit": "20"}           -> {"limit": 20}
  - null or {} for an optional field that cannot be null:         {"limit": null}           -> {}
  - extra keys on an object that is explicitly closed:            {"a": 1, "extra": true}   -> {"a": 1}
  - one nullable alternative:                                     {"count": "2"}            -> {"count": 2}
  - a single value for a list of that type:                       {"tags": "a"}             -> {"tags": ["a"]}
  - positional (tuple) items, dictionaries of typed values, nested fields, and simple local references.

Unchanged input is returned as the very same object, so callers can tell cheaply whether anything was repaired."""

from __future__ import annotations

import json
import math
import re
from typing import Any, Callable

from harness.tool.registry import ToolRegistry, definition

MAX_DEPTH = 6
_NUMBER = re.compile(r"^\s*(?:[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|[+-]?Infinity)\s*$")
_COMPOSITION = ("anyOf", "oneOf", "allOf")
_NOT_PLAIN = ("anyOf", "oneOf", "allOf", "enum", "const", "$ref", "nullable")
MAX_SAFE_INTEGER = 2**53 - 1


def _typeof(value: Any) -> str:
    """JavaScript's typeof, because the schemas are compared against it: null, arrays and objects are all 'object'."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "object"


def _is_object(value: Any) -> bool:
    return isinstance(value, dict)


def _decode(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return None


def _resolve(ref: str, root: dict[str, Any]) -> Any:
    for prefix, key in (("#/$defs/", "$defs"), ("#/definitions/", "definitions")):
        if ref.startswith(prefix) and "/" not in ref[len(prefix):] and len(ref) > len(prefix):
            definitions = root.get(key)
            if not _is_object(definitions):
                return None
            name = ref[len(prefix):].replace("~1", "/").replace("~0", "~")
            target = definitions.get(name)
            return target if _is_object(target) else None
    return None


def repair(value: Any, schema: Any, root: dict[str, Any], depth: int = 0) -> Any:
    if depth > MAX_DEPTH or not _is_object(schema):
        return value

    ref = schema.get("$ref")
    if isinstance(ref, str):
        target = _resolve(ref, root)
        return repair(value, target, root, depth + 1) if target is not None else value

    kind = schema.get("type")
    if isinstance(kind, list):
        if value is None and "null" in kind:
            return value
        if _typeof(value) in kind:
            return value
        types = [t for t in kind if t != "null"]
        return repair(value, {**schema, "type": types[0]}, root, depth + 1) if len(types) == 1 else value

    if kind is None:
        if isinstance(schema.get("anyOf"), list) and isinstance(schema.get("oneOf"), list):
            return value
        branches = schema["anyOf"] if isinstance(schema.get("anyOf"), list) else schema.get("oneOf")
        if not isinstance(branches, list) or value is None:
            return value
        if any(not _is_object(b) or b.get("type") == _typeof(value) for b in branches):
            return value
        candidates = [b for b in branches if _is_object(b) and b.get("type") != "null"]
        return repair(value, candidates[0], root, depth + 1) if len(candidates) == 1 else value

    if kind in ("number", "integer"):
        if not isinstance(value, str) or not value.strip() or not _NUMBER.match(value):
            return value
        parsed = float(value)
        if not math.isfinite(parsed):
            return value
        if kind == "integer":
            return int(parsed) if parsed == int(parsed) and abs(parsed) <= MAX_SAFE_INTEGER else value
        return int(parsed) if parsed == int(parsed) and abs(parsed) <= MAX_SAFE_INTEGER else parsed
    if kind == "boolean":
        return True if value == "true" else False if value == "false" else value
    if kind == "object":
        return _repair_object(value, schema, root, depth)
    if kind == "array":
        return _repair_array(value, schema, root, depth)
    return value


def _without(result: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in result.items() if k != key}


def _repair_object(value: Any, schema: dict[str, Any], root: dict[str, Any], depth: int) -> Any:
    parsed = _decode(value)
    if not _is_object(parsed):
        return value
    properties = schema["properties"] if _is_object(schema.get("properties")) else {}
    required = schema["required"] if isinstance(schema.get("required"), list) else []
    patterned = _is_object(schema.get("patternProperties"))
    composed = any(isinstance(schema.get(k), list) for k in _COMPOSITION)

    result = parsed
    for key in list(parsed):
        current = result[key]
        declared = key in properties
        prop = properties[key] if declared else (schema.get("additionalProperties") if not patterned else None)

        if not declared and schema.get("additionalProperties") is False and not patterned and not composed:
            result = _without(result, key)  # an explicitly closed object: unknown keys are not allowed, so they are dropped
            continue
        if not _is_object(prop):
            continue

        # Only a bare single-type property provably rejects null and {}. Compositions, enums, constants, references and nullable flags may
        # accept them, so those are left alone.
        plain = isinstance(prop.get("type"), str) and prop["type"] != "null" and not composed and all(k not in prop for k in _NOT_PLAIN)
        placeholder = _is_object(current) and len(current) == 0 and prop.get("type") != "object"
        if declared and key not in required and plain and (current is None or placeholder):
            result = _without(result, key)
            continue

        repaired = repair(current, prop, root, depth + 1)
        if repaired is not current:
            result = {**result, key: repaired}
    return result


def _repair_array(value: Any, schema: dict[str, Any], root: dict[str, Any], depth: int) -> Any:
    parsed = _decode(value)
    prefix = schema.get("prefixItems")
    items = schema.get("items")
    tuple_ = prefix if isinstance(prefix, list) else items if isinstance(items, list) else None

    if isinstance(parsed, list):
        repaired = []
        for index, item in enumerate(parsed):
            if tuple_ is not None:
                member = tuple_[index] if index < len(tuple_) else (items if isinstance(prefix, list) else schema.get("additionalItems"))
            else:
                member = items
            repaired.append(repair(item, member, root, depth + 1) if _is_object(member) else item)
        return parsed if all(a is b for a, b in zip(repaired, parsed)) else repaired

    if tuple_ is not None or not _is_object(items):
        return value
    repaired_one = repair(value, items, root, depth + 1)
    kind = items.get("type")
    if kind == "object":
        compatible = _is_object(repaired_one)
    elif kind == "array":
        compatible = isinstance(repaired_one, list)
    elif kind == "integer":
        compatible = isinstance(repaired_one, (int, float)) and not isinstance(repaired_one, bool) and float(repaired_one) == int(repaired_one) and abs(repaired_one) <= MAX_SAFE_INTEGER
    elif kind == "number":
        compatible = isinstance(repaired_one, (int, float)) and not isinstance(repaired_one, bool) and math.isfinite(repaired_one)
    elif kind == "string":
        compatible = isinstance(repaired_one, str)
    elif kind == "boolean":
        compatible = isinstance(repaired_one, bool)
    else:
        compatible = False
    return [repaired_one] if compatible else value


def repair_input(value: Any, schema: dict[str, Any]) -> Any:
    """Repairs `value` against a tool's input schema. Only object schemas are repaired (a schema with no `type` is not understood well enough)."""
    if schema.get("type") != "object":
        return value
    return repair(value, schema, schema, 0)


def install(registry: ToolRegistry) -> Callable[[dict[str, Any]], None]:
    """Registers the repair as a before-execution hook on the registry, so every tool call is repaired against that tool's schema first."""

    def hook(event: dict[str, Any]) -> None:
        tool = registry.get(event["tool"])
        if tool is None:
            return
        event["input"] = repair_input(event["input"], definition(tool).input_schema)

    registry.before.append(hook)
    return hook
