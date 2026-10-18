"""Per-session instruction state (opencode: packages/core/src/session/instruction-state.ts).

The session remembers, as hashes, what each instruction source looked like when the model last saw it:

  initial_values  the baseline shown at the start of every request (the "system prompt")
  current_values  the latest values the model has been told about

When a source changes, only the difference is sent, as a frozen `system` message in the conversation, so the long baseline
prefix stays identical between requests (prompt-cache friendly). A compaction folds the updates into a new baseline
(`advance_epoch`), which is why the system messages before a compaction are no longer needed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from harness.db.database import Database, jdump, jload
from harness.instructions import index as I
from harness.schema import message as M
from harness.session.store import SessionStore


@dataclass
class Observation:
    session_id: str
    initial: bool
    previous: dict[str, str]
    current: dict[str, str]
    delta: dict[str, str]
    blobs: dict[str, Any]


def _find(db: Database, session_id: str) -> Optional[dict[str, Any]]:
    row = db.get("select * from instruction_state where session_id = ?", (session_id,))
    if not row:
        return None
    return {
        "epoch_start": row["epoch_start"], "through_seq": row["through_seq"],
        "initial_values": jload(row["initial_values"]), "current_values": jload(row["current_values"]),
    }


def _observe_against(observed: I.ReadResult, previous: Optional[Mapping[str, str]]) -> tuple[I.Admission, dict[str, str]]:
    admission = I.diff(observed, previous)
    return admission, I.apply_hash_delta(previous or {}, admission.delta)


def observe(db: Database, instructions: I.List, session_id: str) -> Observation:
    """Read every source and compare with what this session last saw. Raises InitializationBlocked if a first read is unavailable."""
    observed = I.read(instructions)
    stored = _find(db, session_id)
    admission, current = _observe_against(observed, stored["current_values"] if stored else None)
    return Observation(session_id, stored is None, dict(stored["current_values"]) if stored else {}, current, admission.delta, admission.blobs)


def _insert_blobs(db: Database, blobs: Mapping[str, Any]) -> None:
    for h, value in blobs.items():
        db.execute("insert or ignore into instruction_blob (hash, value) values (?, ?)", (h, jdump(value)))


def _load_blobs(db: Database, hashes: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for h in dict.fromkeys(hashes):
        row = db.get("select value from instruction_blob where hash = ?", (h,))
        if row is None:
            raise KeyError(f"Instruction blob not found: {h}")
        out[h] = jload(row["value"])
    return out


def _dereference(values: Mapping[str, str], blobs: Mapping[str, Any]) -> dict[str, Any]:
    return {k: blobs[h] for k, h in values.items()}


def _dereference_delta(delta: Mapping[str, str], blobs: Mapping[str, Any]) -> dict[str, Any]:
    return {k: (I.REMOVED if h == I.REMOVED_MARK else blobs[h]) for k, h in delta.items()}


def _render_update_text(db: Database, instructions: I.List, obs: Observation) -> str:
    replaced = {k: h for k, h in obs.previous.items() if k in obs.delta}
    stored = _load_blobs(db, list(replaced.values()))
    previous = {k: stored[h] for k, h in replaced.items()}
    return I.render_update(instructions, previous, _dereference_delta(obs.delta, obs.blobs))


def apply(db: Database, session_id: str, seq: int, delta: Mapping[str, str]) -> None:
    stored = _find(db, session_id)
    current = I.apply_hash_delta(stored["current_values"] if stored else {}, delta)
    if stored is None:
        db.execute(
            "insert into instruction_state (session_id, epoch_start, through_seq, initial_values, current_values) values (?,?,?,?,?)",
            (session_id, seq, seq, jdump(current), jdump(current)),
        )
        return
    db.execute("update instruction_state set through_seq = ?, current_values = ? where session_id = ?", (seq, jdump(current), session_id))


def initialize(db: Database, session_id: str, seq: int, values: Mapping[str, str]) -> None:
    db.execute(
        "insert or ignore into instruction_state (session_id, epoch_start, through_seq, initial_values, current_values) values (?,?,?,?,?)",
        (session_id, seq, seq, jdump(dict(values)), jdump(dict(values))),
    )


def advance_epoch(db: Database, session_id: str, epoch_start: int) -> None:
    db.execute(
        "update instruction_state set epoch_start = ?, through_seq = ?, initial_values = current_values where session_id = ?",
        (epoch_start, epoch_start, session_id),
    )


def reset(db: Database, session_id: str) -> None:
    db.execute("delete from instruction_state where session_id = ?", (session_id,))


def commit(store: SessionStore, instructions: I.List, obs: Observation) -> Optional[M.System]:
    """Record what changed. The first observation only establishes the baseline; later changes become one `system` message
    whose text is frozen now, because re-rendering later would need the original sources."""
    db = store.db
    if not obs.initial and len(obs.delta) == 0:
        return None
    text = "" if obs.initial else _render_update_text(db, instructions, obs)
    with db.transaction():
        _insert_blobs(db, obs.blobs)
        seq = store.next_seq(obs.session_id)
        system: Optional[M.System] = None
        if len(text) > 0:
            system = M.System(
                text=text,
                description=f"Instructions updated: {', '.join(obs.delta.keys())}",
                metadata={"notice": "instructions", "instructionSources": list(obs.delta.keys())},
            )
            store.add(obs.session_id, system)
        apply(db, obs.session_id, seq, obs.delta)
    return system


def prepare(store: SessionStore, instructions: I.List, session_id: str) -> Optional[M.System]:
    return commit(store, instructions, observe(store.db, instructions, session_id))


def initial(db: Database, session_id: str, instructions: I.List) -> str:
    """Render the epoch baseline shown at the start of every model request."""
    state = _find(db, session_id)
    if state is None:
        raise RuntimeError(f"Instruction state not found during assembly: {session_id}")
    blobs = _load_blobs(db, list(state["initial_values"].values()))
    return I.render_initial(instructions, _dereference(state["initial_values"], blobs))


def current(db: Database, session_id: str) -> Optional[dict[str, str]]:
    state = _find(db, session_id)
    return state["current_values"] if state else None


def preview(db: Database, session_id: str, instructions: I.List, observed: I.ReadResult) -> dict[str, str]:
    state = _find(db, session_id)
    admission, current_values = _observe_against(observed, state["current_values"] if state else None)
    observed_blobs = dict(admission.blobs)
    if state is None:
        return {"initial": I.render_initial(instructions, _dereference(current_values, observed_blobs)), "update": ""}
    stored = _load_blobs(db, [*state["initial_values"].values(), *state["current_values"].values()])
    return {
        "initial": I.render_initial(instructions, _dereference(state["initial_values"], stored)),
        "update": I.render_update(instructions, _dereference(state["current_values"], stored), _dereference_delta(admission.delta, observed_blobs)),
    }
