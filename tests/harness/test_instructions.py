"""Ported from opencode packages/core/test/instructions/index.test.ts."""

import pytest

from harness.instructions import index as I


def source(key, value, initial=None, changed=None, removed=None):
    return I.make(I.Definition(key=key, read=lambda: value, render_initial=initial or str, render_changed=changed or (lambda p, c: c), render_removed=removed))


def test_reads_each_source_once_and_derives_the_initial_delta_and_text():
    reads = []
    ins = I.make(I.Definition(
        key="core/date", read=lambda: (reads.append(1), "2026-07-09")[1],
        render_initial=lambda d: f"Today's date: {d}", render_changed=lambda p, c: f"The date changed from {p} to {c}",
    ))
    admitted = I.diff(I.read(ins))
    h = I.hash_value("2026-07-09")
    assert len(reads) == 1
    assert admitted.delta == {"core/date": h} and admitted.blobs == {h: "2026-07-09"}
    assert I.render_initial(ins, {"core/date": "2026-07-09"}) == "Today's date: 2026-07-09"


def test_no_delta_when_the_encoded_value_is_unchanged():
    ins = source("core/date", "2026-07-09")
    a = I.diff(I.read(ins), {"core/date": I.hash_value("2026-07-09")})
    assert a.delta == {} and a.blobs == {}


def test_renders_a_changed_value_from_stored_values():
    ins = source("core/date", "2026-07-10", changed=lambda p, c: f"The date changed from {p} to {c}")
    a = I.diff(I.read(ins), {"core/date": I.hash_value("2026-07-09")})
    assert a.delta == {"core/date": I.hash_value("2026-07-10")}
    assert I.render_update(ins, {"core/date": "2026-07-09"}, {"core/date": "2026-07-10"}) == "The date changed from 2026-07-09 to 2026-07-10"


def test_admits_and_renders_an_observed_removal():
    ins = source("core/remote", I.REMOVED, removed=lambda p: f"Stop applying {p}")
    a = I.diff(I.read(ins), {"core/remote": I.hash_value("instructions")})
    assert a.delta == {"core/remote": "removed"} and a.blobs == {}
    assert I.render_update(ins, {"core/remote": "instructions"}, {"core/remote": I.REMOVED}) == "Stop applying instructions"


def test_json_null_is_a_value_not_a_removal():
    ins = I.make(I.Definition(key="api/value", read=lambda: None, render_initial=str, render_changed=lambda p, c: str(c), render_removed=lambda p: "removed"))
    a = I.diff(I.read(ins), {"api/value": I.hash_value("previous")})
    assert a.delta == {"api/value": I.hash_value(None)} and a.blobs == {I.hash_value(None): None}
    assert I.render_update(ins, {"api/value": "previous"}, {"api/value": None}) == "None"


def test_blocks_the_initial_delta_while_any_source_is_unavailable():
    with pytest.raises(I.InitializationBlocked) as e:
        I.diff(I.read(source("core/remote", I.UNAVAILABLE)))
    assert e.value.keys == ["core/remote"]


def test_keeps_the_stored_value_while_a_source_is_unavailable_mid_session():
    a = I.diff(I.read(source("core/remote", I.UNAVAILABLE)), {"core/remote": I.hash_value("instructions")})
    assert a.delta == {} and a.blobs == {}


def test_does_not_infer_removal_when_a_source_is_absent_from_the_current_version():
    a = I.diff(I.read(I.empty), {"core/retired": I.hash_value("old instructions")})
    assert a.delta == {} and a.blobs == {}


def test_a_newly_added_source_renders_with_its_initial_renderer():
    ins = source("core/skills", "effect", initial=lambda s: f"Available skill: {s}")
    assert I.render_update(ins, {}, {"core/skills": "effect"}) == "Available skill: effect"


def test_hashes_objects_independently_of_key_order():
    assert I.hash_value({"a": 1, "b": {"x": True, "y": False}}) == I.hash_value({"b": {"y": False, "x": True}, "a": 1})


def test_renders_sources_in_composition_order():
    ins = I.combine([source("core/date", "date"), source("core/location", "location")])
    assert I.render_initial(ins, {"core/date": "date", "core/location": "location"}) == "date\n\nlocation"


def test_rejects_duplicate_source_keys():
    with pytest.raises(I.DuplicateKeyError):
        I.combine([source("core/date", "one"), source("core/date", "two")])


def test_rejects_empty_model_visible_renderings():
    ins = source("core/empty", "value", initial=lambda v: "")
    with pytest.raises(ValueError, match="Instruction source core/empty rendered an empty initial"):
        I.render_initial(ins, {"core/empty": "value"})


def test_diffs_list_values_by_key():
    previous = [{"name": "effect", "description": "Build with Effect"}, {"name": "retired", "description": "Old"}]
    current = [{"name": "effect", "description": "Build with Effect v4"}, {"name": "writing", "description": "Write prose"}]
    d = I.diff_by_key(previous, current, lambda v: v["name"], lambda b, a: b["description"] != a["description"])
    assert d["added"] == [{"name": "writing", "description": "Write prose"}]
    assert d["removed"] == [{"name": "retired", "description": "Old"}]
    assert d["changed"] == [{"previous": previous[0], "current": current[0]}]
