"""Modelled on opencode packages/core/test/instruction-state.test.ts."""

import pytest

from harness.instructions import index as I
from harness.schema import message as M
from harness.session import compaction as C
from harness.session import history
from harness.session import instruction_state as S
from harness.session.compaction import Trigger
from tests.harness.conftest import SUMMARY, FakeLLM, assistant, loaded, make_compaction, run, user


def src(key, box, removed=None):
    return I.make(I.Definition(
        key=key, read=lambda: box["v"], render_initial=lambda v: f"{key}: {v}", render_changed=lambda p, c: f"{key} changed from {p} to {c}",
        render_removed=removed,
    ))


def setup(store):
    return store.create("/p", agent="build")


def test_observing_reads_once_and_changes_nothing_in_storage(store):
    s = setup(store)
    reads = []
    ins = I.combine([I.make(I.Definition(key="test/first", read=lambda: (reads.append(1), "first")[1], render_initial=str, render_changed=lambda p, c: c))])
    obs = S.observe(store.db, ins, s.id)
    assert len(reads) == 1 and obs.initial and obs.previous == {}
    assert obs.delta == {"test/first": I.hash_value("first")} and obs.blobs == {I.hash_value("first"): "first"}
    assert store.db.all("select * from instruction_blob") == [] and store.db.all("select * from instruction_state") == []


def test_first_commit_establishes_the_baseline_without_a_message(store):
    s = setup(store)
    box = {"v": "a"}
    ins = src("test/current", box)
    assert S.prepare(store, ins, s.id) is None
    assert store.messages(s.id) == []
    assert S.initial(store.db, s.id, ins) == "test/current: a"
    assert S.current(store.db, s.id) == {"test/current": I.hash_value("a")}


def test_changes_become_frozen_system_messages_and_the_baseline_does_not_move(store):
    s = setup(store)
    box = {"v": "a"}
    ins = src("test/current", box)
    S.prepare(store, ins, s.id)
    box["v"] = "b"
    system = S.prepare(store, ins, s.id)
    assert isinstance(system, M.System) and system.text == "test/current changed from a to b"
    assert system.metadata["notice"] == "instructions" and system.metadata["instructionSources"] == ["test/current"]
    assert S.initial(store.db, s.id, ins) == "test/current: a"  # the cacheable prefix stays the same
    assert S.current(store.db, s.id) == {"test/current": I.hash_value("b")}
    box["v"] = "c"
    S.prepare(store, ins, s.id)
    texts = [m.text for _, m in store.messages(s.id)]
    assert texts == ["test/current changed from a to b", "test/current changed from b to c"]


def test_no_op_observations_write_nothing(store):
    s = setup(store)
    ins = src("test/x", {"v": "same"})
    S.prepare(store, ins, s.id)
    blobs_before = store.db.all("select * from instruction_blob")
    assert S.prepare(store, ins, s.id) is None
    assert store.messages(s.id) == [] and len(store.db.all("select * from instruction_blob")) == len(blobs_before)


def test_removal_is_rendered_when_the_source_provides_a_removal_text(store):
    s = setup(store)
    box = {"v": "retired"}
    ins = src("test/retired", box, removed=lambda p: f"Stop applying {p}")
    S.prepare(store, ins, s.id)
    box["v"] = I.REMOVED
    system = S.prepare(store, ins, s.id)
    assert system.text == "Stop applying retired" and S.current(store.db, s.id) == {}


def test_unavailable_initial_source_blocks_without_persisting(store):
    s = setup(store)
    ins = src("test/remote", {"v": I.UNAVAILABLE})
    with pytest.raises(I.InitializationBlocked):
        S.prepare(store, ins, s.id)
    assert store.db.all("select * from instruction_state") == []


def test_a_committed_value_is_retained_when_the_source_becomes_unavailable(store):
    s = setup(store)
    box = {"v": "remote rules"}
    ins = src("test/remote", box)
    S.prepare(store, ins, s.id)
    box["v"] = I.UNAVAILABLE
    assert S.prepare(store, ins, s.id) is None
    assert S.current(store.db, s.id) == {"test/remote": I.hash_value("remote rules")}


def test_preview_shows_what_would_change_without_writing(store):
    s = setup(store)
    box = {"v": "a"}
    ins = src("test/p", box)
    S.prepare(store, ins, s.id)
    box["v"] = "b"
    p = S.preview(store.db, s.id, ins, I.read(ins))
    assert p == {"initial": "test/p: a", "update": "test/p changed from a to b"}
    assert S.current(store.db, s.id) == {"test/p": I.hash_value("a")}  # unchanged


def test_assembling_without_state_is_an_error(store):
    s = setup(store)
    with pytest.raises(RuntimeError, match="Instruction state not found"):
        S.initial(store.db, s.id, src("test/x", {"v": 1}))


def test_a_compaction_folds_updates_into_a_new_baseline(store):
    """The whole memory lifecycle: baseline, two updates, then a compaction retires the update messages and moves the baseline."""
    s = setup(store)
    box = {"v": "rules v1"}
    ins = src("project/rules", box)
    S.prepare(store, ins, s.id)
    for i in range(5):
        store.add(s.id, user(f"request {i} " + "x" * 3000))
        store.add(s.id, assistant(f"answer {i}"))
    box["v"] = "rules v2"
    S.prepare(store, ins, s.id)
    assert S.initial(store.db, s.id, ins) == "project/rules: rules v1"
    assert any(isinstance(m, M.System) for m in history.load(store, s.id))

    comp = make_compaction(store, FakeLLM(SUMMARY), settings=C.Settings(keep=500))
    assert run(comp.compact(Trigger("manual", loaded(store, s, initial="project/rules: rules v1")))).status == "completed"

    after = history.load(store, s.id)
    assert isinstance(after[0], M.CompactionCompleted) and not any(isinstance(m, M.System) for m in after)  # the update message is retired
    assert S.initial(store.db, s.id, ins) == "project/rules: rules v2"  # ...because the baseline now includes it
    box["v"] = "rules v3"
    S.prepare(store, ins and ins, s.id)
    assert [m.text for m in history.load(store, s.id) if isinstance(m, M.System)] == ["project/rules changed from rules v2 to rules v3"]
