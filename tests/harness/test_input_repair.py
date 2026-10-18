"""Tool-input repair, ported from opencode's tool-input-repair.test.ts and tool-input-repair-integration.test.ts."""

import asyncio

from pydantic import BaseModel

from harness.tool import input_repair
from harness.tool.info import ToolInfo, ToolResult
from harness.tool.registry import Call, ToolRegistry

run = input_repair.repair_input


def obj(properties, required=None):
    out = {"type": "object", "properties": properties}
    if required:
        out["required"] = required
    return out


def test_valid_input_keeps_its_identity_and_unknown_properties():
    nested, items = {"enabled": True}, [2, 3]
    value = {"count": 2, "nested": nested, "items": items, "extra": "keep"}
    out = run(value, obj({"count": {"type": "integer"}, "nested": obj({"enabled": {"type": "boolean"}}), "items": {"type": "array", "items": {"type": "number"}}}))
    assert out is value and out["nested"] is nested and out["items"] is items


def test_root_objects_and_nested_stringified_containers_are_parsed():
    schema = obj({"count": {"type": "integer"}, "item": obj({"enabled": {"type": "boolean"}}), "list": {"type": "array", "items": {"type": "integer"}}})
    assert run('{"count":"2","item":"{\\"enabled\\":\\"false\\"}","list":"[\\"3\\"]"}', schema) == {"count": 2, "item": {"enabled": False}, "list": [3]}
    assert run("{broken", schema) == "{broken" and run("[]", schema) == "[]" and run(None, schema) is None


def test_extras_are_removed_only_from_explicitly_closed_objects_without_mutating_the_input():
    value = {"known": "2", "extra": True, "closed": {"keep": "3", "extra": True}, "open": {"keep": "4", "extra": True}, "items": [{"keep": "5", "extra": True}]}
    schema = {
        **obj({
            "known": {"type": "integer"},
            "closed": {**obj({"keep": {"type": "integer"}}), "additionalProperties": False},
            "open": obj({"keep": {"type": "integer"}}),
            "items": {"type": "array", "items": {**obj({"keep": {"type": "integer"}}), "additionalProperties": False}},
        }),
        "additionalProperties": False,
    }
    assert run(value, schema) == {"known": 2, "closed": {"keep": 3}, "open": {"keep": 4, "extra": True}, "items": [{"keep": 5}]}
    assert value["extra"] is True and value["closed"]["extra"] is True and value["items"][0]["extra"] is True
    assert run({"extra": True}, {**obj({}), "additionalProperties": False}) == {}


def test_unknown_keys_survive_when_patterned_ownership_is_unclear():
    value = {"known": 1, "match": "2", "extra": True}
    schema = {**obj({"known": {"type": "integer"}}), "additionalProperties": False, "patternProperties": {"^match$": {"type": "integer"}}}
    out = run(value, schema)
    assert out is value and out["match"] == "2" and out["extra"] is True


def test_properties_that_may_belong_to_composed_schemas_are_kept():
    for keyword in ("allOf", "anyOf", "oneOf"):
        value = {"name": "example", "extra": True}
        assert run(value, {"type": "object", keyword: [obj({"name": {"type": "string"}})], "additionalProperties": False}) is value


def test_only_optional_non_nullable_nulls_and_non_object_empty_placeholders_are_removed():
    value = {"optional": None, "required": None, "nullable": None, "union": None, "constant": None, "permissive": None, "referenced": None,
             "placeholder": {}, "array": {}, "requiredPlaceholder": {}, "object": {}, "unknown": None}
    schema = obj({
        "optional": {"type": "string"}, "required": {"type": "string"}, "nullable": {"type": "string", "nullable": True},
        "union": {"anyOf": [{"type": "integer"}, {"type": "null"}]}, "constant": {"anyOf": [{"type": "integer"}, {"const": None}]},
        "permissive": {"anyOf": [{"type": "integer"}, True]}, "referenced": {"anyOf": [{"type": "integer"}, {"$ref": "#/$defs/nullable"}]},
        "placeholder": {"type": "integer"}, "array": {"type": "array", "items": {"type": "string"}}, "requiredPlaceholder": {"type": "boolean"},
        "object": {"type": "object"}, "unknown": {},
    }, ["required", "requiredPlaceholder"])
    assert run(value, schema) == {"required": None, "nullable": None, "union": None, "constant": None, "permissive": None, "referenced": None,
                                  "requiredPlaceholder": {}, "object": {}, "unknown": None}
    assert value["optional"] is None and value["placeholder"] == {}


def test_nulls_whose_validity_is_hidden_inside_compositions_are_kept():
    value = {"wrapped": None, "enumerated": None, "permissive": None, "constant": None}
    schema = obj({"wrapped": {"anyOf": [{"type": ["string", "null"]}]}, "enumerated": {"anyOf": [{"enum": [None, "keep"]}]}, "permissive": {"anyOf": [{}]}, "constant": {"type": "string", "const": "keep"}})
    assert run(value, schema) is value


def test_optional_looking_nulls_stay_when_the_parent_composes_requirements():
    value = {"value": None}
    assert run(value, {**obj({"value": {"type": "string"}}), "allOf": [{"required": ["value"]}]}) is value


def test_numeric_and_boolean_strings_are_coerced_and_invalid_or_existing_values_kept():
    value = {"number": "1.5", "integer": "42", "enabled": "true", "disabled": "false", "valid": 3, "empty": " ", "infinite": "Infinity",
             "fractional": "1.5", "unsafe": "9007199254740992", "uppercase": "TRUE"}
    schema = obj({"number": {"type": "number"}, "integer": {"type": "integer"}, "enabled": {"type": "boolean"}, "disabled": {"type": "boolean"}, "valid": {"type": "integer"},
                  "empty": {"type": "number"}, "infinite": {"type": "number"}, "fractional": {"type": "integer"}, "unsafe": {"type": "integer"}, "uppercase": {"type": "boolean"}})
    assert run(value, schema) == {**value, "number": 1.5, "integer": 42, "enabled": True, "disabled": False}


def test_scalars_are_wrapped_after_repairing_array_items():
    value = {"text": "one", "integer": "42", "boolean": "false", "item": '{"count":"2"}', "incompatible": 2, "fractional": 1.5, "unconstrained": "4"}
    schema = obj({
        "text": {"type": "array", "items": {"type": "string"}}, "integer": {"type": "array", "items": {"type": "integer"}},
        "boolean": {"type": "array", "items": {"type": "boolean"}}, "item": {"type": "array", "items": obj({"count": {"type": "integer"}})},
        "incompatible": {"type": "array", "items": {"type": "string"}}, "fractional": {"type": "array", "items": {"type": "integer"}}, "unconstrained": {"type": "array"},
    })
    assert run(value, schema) == {"text": ["one"], "integer": [42], "boolean": [False], "item": [{"count": 2}], "incompatible": 2, "fractional": 1.5, "unconstrained": "4"}


def test_question_like_nested_input_is_repaired_without_mutating_the_original():
    question = {"question": "Pick one", "multiple": "false", "options": {"label": "First", "description": None}}
    value = {"questions": [question]}
    schema = obj({"questions": {"type": "array", "items": obj({
        "question": {"type": "string"}, "multiple": {"type": "boolean"},
        "options": {"type": "array", "items": obj({"label": {"type": "string"}, "description": {"type": "string"}}, ["label"])},
    })}})
    assert run(value, schema) == {"questions": [{"question": "Pick one", "multiple": False, "options": [{"label": "First"}]}]}
    assert value == {"questions": [question]} and question["options"]["description"] is None


def test_unique_nullable_alternatives_are_repaired_and_accepted_union_values_kept():
    value = {"number": "2", "boolean": "false", "nullable": None, "typed": "3", "typedBoolean": "true", "accepted": "4", "valid": 5}
    schema = obj({
        "number": {"anyOf": [{"type": "number"}, {"type": "null"}]}, "boolean": {"oneOf": [{"type": "boolean"}, {"type": "null"}]},
        "nullable": {"anyOf": [{"type": "number"}, {"type": "null"}]}, "typed": {"type": ["integer", "null"]}, "typedBoolean": {"type": ["boolean", "null"]},
        "accepted": {"anyOf": [{"type": "string"}, {"type": "number"}]}, "valid": {"type": ["number", "null"]},
    })
    assert run(value, schema) == {**value, "number": 2, "boolean": False, "typed": 3, "typedBoolean": True}


def test_tuple_positions_and_rest_items_are_repaired_and_valid_arrays_keep_identity():
    valid = [2, False]
    value = {"prefix": ["2", "false", "3"], "draft": '["4","true"]', "valid": valid, "scalar": "5"}
    schema = obj({
        "prefix": {"type": "array", "prefixItems": [{"type": "integer"}, {"type": "boolean"}], "items": {"type": "number"}},
        "draft": {"type": "array", "items": [{"type": "integer"}, {"type": "boolean"}]},
        "valid": {"type": "array", "prefixItems": [{"type": "integer"}, {"type": "boolean"}]},
        "scalar": {"type": "array", "prefixItems": [{"type": "integer"}]},
    })
    out = run(value, schema)
    assert out == {"prefix": [2, False, 3], "draft": [4, True], "valid": valid, "scalar": "5"} and out["valid"] is valid
    assert value["prefix"] == ["2", "false", "3"]


def test_typed_dictionaries_and_simple_local_references_are_repaired():
    value = {"modern": "2", "legacy": "false", "nested": {"count": "3"}, "dictionary": {"first": "4"}, "missing": "5", "pointer": "6", "escaped": "7"}
    schema = {
        **obj({
            "modern": {"$ref": "#/$defs/integer"}, "legacy": {"$ref": "#/definitions/boolean"}, "nested": {"$ref": "#/$defs/nested"},
            "dictionary": {"type": "object", "additionalProperties": {"$ref": "#/$defs/integer"}}, "missing": {"$ref": "#/$defs/missing"},
            "pointer": {"$ref": "#/$defs/nested/properties/count"}, "escaped": {"$ref": "#/$defs/a~1b~0c"},
        }),
        "$defs": {"integer": {"type": "integer"}, "a/b~c": {"type": "integer"}, "nested": obj({"count": {"$ref": "#/$defs/integer"}})},
        "definitions": {"boolean": {"type": "boolean"}},
    }
    assert run(value, schema) == {"modern": 2, "legacy": False, "nested": {"count": 3}, "dictionary": {"first": 4}, "missing": "5", "pointer": "6", "escaped": 7}
    assert value["nested"]["count"] == "3" and value["dictionary"]["first"] == "4"


def test_ambiguous_unions_compositions_and_unsupported_roots_are_left_alone():
    value = {"numeric": "2", "objects": {"value": "3"}, "both": "4", "composed": "5", "unknown": "6"}
    schema = obj({
        "numeric": {"anyOf": [{"type": "number"}, {"type": "integer"}]},
        "objects": {"oneOf": [obj({"value": {"type": "integer"}}, ["value"]), obj({"value": {"type": "number"}}, ["value"])]},
        "both": {"anyOf": [{"type": "integer"}], "oneOf": [{"type": "integer"}]}, "composed": {"allOf": [{"type": "integer"}]}, "unknown": {},
    })
    assert run(value, schema) is value
    assert run(value, {"properties": {"numeric": {"type": "integer"}}}) is value
    assert run(value, {"allOf": [obj({"numeric": {"type": "integer"}})]}) is value


# ------------------------------------------------------------------ through the registry

class Counted(BaseModel):
    count: int
    enabled: bool


def test_tools_receive_repaired_input_and_the_hook_follows_schema_changes():
    seen = []

    async def execute(inp, ctx):
        seen.append(inp.model_dump())
        return ToolResult(content="ok")

    registry = ToolRegistry()
    registry.add(ToolInfo("repairable", "Repairable", Counted, execute))
    input_repair.install(registry)

    async def call(raw):
        snap = registry.snapshot()
        return await snap.execute(session_id="ses_r", agent="build", message_id="msg_r", call=Call("call_r", "repairable", raw))

    asyncio.run(call('{"count":"2","enabled":"true","extra":true}'))  # a JSON string with a stray key and strings for the numbers
    assert seen == [{"count": 2, "enabled": True}]

    class Flags(BaseModel):
        count: bool
        enabled: bool

    registry.update("repairable", lambda tool: setattr(tool, "input", Flags))
    asyncio.run(call({"count": "false", "enabled": "true"}))  # the hook reads the *current* schema
    assert seen[-1] == {"count": False, "enabled": True}

    registry.remove("repairable")
    try:
        asyncio.run(call({}))
    except Exception as exc:
        assert 'No tool named "repairable"' in str(exc)
    else:
        raise AssertionError("a removed tool must not be callable")
