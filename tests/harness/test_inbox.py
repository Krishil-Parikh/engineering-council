"""The session inbox: delivery modes, promotion order, compaction priority, idempotent admission."""

import pytest

from harness.schema import message as M
from harness.session.inbox import LifecycleConflict, SessionInbox


@pytest.fixture
def box(db):
    return SessionInbox(db)


@pytest.fixture
def session(store):
    return store.create("/tmp/x").id


def texts(store, session):
    return [m.text for _, m in store.messages(session) if isinstance(m, (M.User, M.Synthetic))]


def user(box, session, text, delivery="queue", id=None):
    return box.admit(session, "user", {"text": text}, delivery, id)


def test_items_are_pending_until_promoted_and_keep_their_ids(box, store, session):
    item = user(box, session, "hello", "queue", id="msg_fixed")
    assert [i.id for i in box.list(session)] == ["msg_fixed"] and texts(store, session) == []
    assert box.promote(store, session, "input") == 1
    assert texts(store, session) == ["hello"] and box.list(session) == []
    assert [m.id for _, m in store.messages(session)] == ["msg_fixed"]  # the message has the item's id
    assert item.delivery == "queue"


def test_admission_is_idempotent_and_conflicts_are_rejected(box, store, session):
    first = user(box, session, "once", id="msg_a")
    assert user(box, session, "different text, same id", id="msg_a").payload == first.payload  # the first admission wins
    box.promote(store, session, "input")
    again = user(box, session, "once", id="msg_a")  # already promoted: nothing new is enqueued
    assert box.list(session) == [] and again.id == "msg_a" and texts(store, session) == ["once"]
    with pytest.raises(LifecycleConflict):
        box.admit(session, "synthetic", {"text": "x"}, "steer", id="msg_a")  # same id, other type
    other = store.create("/tmp/y").id
    with pytest.raises(LifecycleConflict):
        user(box, other, "x", id="msg_a")  # same id, other session
    with pytest.raises(ValueError):
        box.admit(session, "user", {"text": "x"}, "sideways")


def test_steers_come_before_queued_items(box, store, session):
    user(box, session, "queued first", "queue")
    user(box, session, "steer second", "steer")
    assert box.next_promotable(session, "input").payload["text"] == "steer second"
    assert box.next_promotable(session, "steer").payload["text"] == "steer second"


def test_a_steer_scope_never_takes_a_queued_item(box, store, session):
    user(box, session, "later", "queue")
    assert box.next_promotable(session, "steer") is None and box.promote(store, session, "steer") == 0
    assert texts(store, session) == [] and box.has(session, "queue") and not box.has(session, "steer")


def test_the_input_scope_takes_one_queued_item_at_a_time_in_order(box, store, session):
    user(box, session, "one", "queue")
    user(box, session, "two", "queue")
    assert box.promote(store, session, "input") == 1 and texts(store, session) == ["one"]
    assert box.promote(store, session, "input") == 1 and texts(store, session) == ["one", "two"]
    assert box.promote(store, session, "input") == 0


def test_all_pending_steers_go_in_together_in_arrival_order(box, store, session):
    user(box, session, "a", "steer")
    box.admit(session, "synthetic", {"text": "b", "description": "note"}, "steer")
    user(box, session, "c", "steer")
    assert box.promote(store, session, "steer") == 3 and texts(store, session) == ["a", "b", "c"]
    assert isinstance([m for _, m in store.messages(session)][1], M.Synthetic)


def test_a_compaction_is_hoisted_ahead_of_earlier_steers_and_owns_the_boundary(box, store, session):
    user(box, session, "before", "steer")
    compaction = box.admit_compaction(session, "steer")
    user(box, session, "after", "steer")
    assert box.next_promotable(session, "steer").id == compaction.id  # compact first, so "before" stays verbatim after the checkpoint
    assert box.promote(store, session, "steer") is None and texts(store, session) == []  # the runner must handle the compaction
    box.deliver(session, compaction.id)
    assert box.promote(store, session, "steer") == 2 and texts(store, session) == ["before", "after"]


def test_prompts_stop_at_a_compaction_behind_them(box, store, session):
    user(box, session, "first", "steer")
    user(box, session, "second", "steer")
    box.admit_compaction(session, "steer")
    user(box, session, "after the compaction", "steer")
    # the compaction is hoisted to the front, so nothing is promoted until it is handled
    assert box.promote(store, session, "steer") is None


def test_a_queued_compaction_must_be_handled_before_anything_after_it(box, store, session):
    box.admit_compaction(session, "queue")
    user(box, session, "after", "queue")
    assert box.promote(store, session, "input") is None and texts(store, session) == []


def test_only_one_compaction_waits_at_a_time(box, session):
    first = box.admit_compaction(session)
    assert box.admit_compaction(session).id == first.id and len([i for i in box.list(session) if i.type == "compaction"]) == 1


def test_promoting_a_queued_item_also_picks_up_steers_that_arrived_meanwhile(box, store, session):
    user(box, session, "queued", "queue")
    original = box._publish

    def publish_then_arrive(store_, session_id, items):
        count = original(store_, session_id, items)
        if items and items[0].payload["text"] == "queued":
            user(box, session, "steered in meanwhile", "steer")
        return count

    box._publish = publish_then_arrive
    assert box.promote(store, session, "input") == 2 and texts(store, session) == ["queued", "steered in meanwhile"]


def test_cancel_and_changing_the_delivery(box, store, session):
    a = user(box, session, "a", "queue")
    b = user(box, session, "b", "queue")
    box.steer(session, b.id)
    assert box.next_promotable(session, "steer").id == b.id
    with pytest.raises(LifecycleConflict):
        box.steer(session, b.id)  # already steered
    box.queue(session, b.id)
    assert box.next_promotable(session, "steer") is None
    box.cancel(session, a.id)
    assert [i.id for i in box.list(session)] == [b.id]
    for action in (lambda: box.cancel(session, a.id), lambda: box.steer(session, "msg_nope"), lambda: box.deliver(session, a.id)):
        with pytest.raises(LifecycleConflict):
            action()


def test_events_are_reported(db, store, session):
    seen = []
    box = SessionInbox(db, lambda kind, data: seen.append((kind, data["id"])))
    item = user(box, session, "x", "steer")
    box.promote(store, session, "steer")
    other = user(box, session, "y", "queue")
    box.cancel(session, other.id)
    assert [k for k, _ in seen] == ["inbox.enqueued", "inbox.delivered", "inbox.enqueued", "inbox.cancelled"] and seen[0][1] == item.id


def test_pending_items_vanish_with_their_session(box, store, session):
    user(box, session, "x", "queue")
    store.remove(session)
    assert box.list(session) == []
