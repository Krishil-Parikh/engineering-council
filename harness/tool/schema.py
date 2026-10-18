"""JSON schemas for tools and input validation (opencode: packages/core/src/tool/runtime.ts).

Schemas sent to the model are simplified the way opencode does it: local `$ref`s are inlined, unused `$defs` dropped, and
`{type, allOf:[{minimum}]}` flattened, because some providers handle the verbose form poorly. Gemini additionally dislikes
`anyOf: [X, null]` for optional fields, so those collapse to X (the field is simply not required)."""

from __future__ import annotations

import json
from typing import Any, Union

from pydantic import BaseModel, ValidationError

from harness.tool.info import ToolInfo


def _is_record(v: Any) -> bool:
    return isinstance(v, dict)


def _inline_refs(value: Any, definitions: dict[str, Any] | None = None, seen: frozenset[str] = frozenset()) -> Any:
    if isinstance(value, list):
        return [_inline_refs(v, definitions, seen) for v in value]
    if not _is_record(value):
        return value
    local = definitions if definitions is not None else (value.get("$defs") if _is_record(value.get("$defs")) else None)
    ref = value.get("$ref")
    if isinstance(ref, str) and local and ref.startswith("#/$defs/"):
        name = ref[len("#/$defs/"):]
        if name not in seen and name in local:
            rest = {k: v for k, v in value.items() if k != "$ref"}
            target = _inline_refs(local[name], local, seen | {name})
            siblings = _inline_refs(rest, local, seen)
            if not (_is_record(target) and _is_record(siblings)):
                return target
            if all(k not in siblings for k in target):
                return {**target, **siblings}
            return {"allOf": [target, siblings]}
    return {k: _inline_refs(v, local, seen) for k, v in value.items()}


def _has_local_ref(value: Any) -> bool:
    if isinstance(value, list):
        return any(_has_local_ref(v) for v in value)
    if not _is_record(value):
        return False
    if isinstance(value.get("$ref"), str) and value["$ref"].startswith("#/$defs/"):
        return True
    return any(_has_local_ref(v) for v in value.values())


def _flatten_all_of(value: Any) -> Any:
    if isinstance(value, list):
        return [_flatten_all_of(v) for v in value]
    if not _is_record(value):
        return value
    schema = {k: _flatten_all_of(v) for k, v in value.items()}
    all_of = schema.get("allOf")
    if not (isinstance(all_of, list) and all(_is_record(i) for i in all_of)):
        return schema
    keys = {k for k in schema if k != "allOf"}
    for item in all_of:
        for k in item:
            if k in keys:
                return schema
            keys.add(k)
    merged: dict[str, Any] = {}
    for item in all_of:
        merged.update(item)
    merged.update({k: v for k, v in schema.items() if k != "allOf"})
    return _flatten_all_of(merged)


def _simplify_optionals(value: Any) -> Any:
    """anyOf [X, {type: null}] -> X, and drop titles (noise for the model)."""
    if isinstance(value, list):
        return [_simplify_optionals(v) for v in value]
    if not _is_record(value):
        return value
    out = {k: _simplify_optionals(v) for k, v in value.items() if k != "title"}
    any_of = out.get("anyOf")
    if isinstance(any_of, list):
        non_null = [a for a in any_of if not (_is_record(a) and a.get("type") == "null")]
        if len(non_null) == 1 and len(any_of) == 2:
            rest = {k: v for k, v in out.items() if k != "anyOf"}
            return {**non_null[0], **rest}
    if "default" in out and out["default"] is None:
        del out["default"]
    return out


def to_json_schema(schema: Union[type[BaseModel], dict[str, Any]]) -> dict[str, Any]:
    """The simplified JSON schema sent to the model."""
    raw = schema.model_json_schema() if isinstance(schema, type) and issubclass(schema, BaseModel) else dict(schema)
    inlined = _inline_refs(raw)
    if not _has_local_ref(inlined) and _is_record(inlined):
        inlined = {k: v for k, v in inlined.items() if k != "$defs"}
    result = _simplify_optionals(_flatten_all_of(inlined))
    result.setdefault("type", "object")
    if result["type"] == "object":
        result.setdefault("properties", {})
    return result


def _format_issues(tool: str, issues: list[dict[str, Any]], value: Any) -> str:
    details = []
    for issue in issues[:5]:
        path = ""
        for seg in issue.get("loc", ()):
            path = f"{path}[{seg}]" if isinstance(seg, int) else (str(seg) if path == "" else f"{path}.{seg}")
        details.append(f"- {path or 'root'}: {issue.get('msg', 'invalid')}")
    if len(issues) > 5:
        more = len(issues) - 5
        details.append(f"- ...and {more} more {'issue' if more == 1 else 'issues'}")
    return (
        f'Invalid arguments for tool "{tool}":\n' + "\n".join(details)
        + f"\n\nArguments provided:\n{json.dumps(value, indent=2, default=str)}\n\nUpdate the arguments and call the tool again."
    )


def decode_input(tool: ToolInfo, value: Any) -> Any:
    """Validate the model's arguments. Returns the parsed model (or the raw value for a raw JSON schema). Raises ValueError with a model-readable message."""
    if isinstance(tool.input, type) and issubclass(tool.input, BaseModel):
        try:
            return tool.input.model_validate(value if value is not None else {})
        except ValidationError as exc:
            raise ValueError(_format_issues(tool.id or tool.name, exc.errors(), value)) from None
    return value
