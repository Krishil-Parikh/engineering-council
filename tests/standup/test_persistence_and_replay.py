import json
import logging
import threading

import pytest

from standup.adapters.files import FileProjections
from standup.adapters.jsonl_store import JsonlEventStore
from standup.adapters.memory_store import MemoryEventStore
from standup.adapters.system import FixedClock, SequentialIds
from standup.enums import MeetingStatus
from standup.errors import InvalidEvent, StoreError, UnknownMeeting
from standup.events import MeetingEvent, redact
from standup.service import MeetingService
from standup.transcript import format_elapsed, render_transcript
from tests.standup.helpers import WS, join, make_service, open_meeting


def a_busy_meeting(svc, clock):
    mid = open_meeting(svc, devs=3, meeting_type="sprint_review")
    clock.advance(75)
    svc.publish(mid, "topic_started", {"topic": "Timer plugin demo"}, actor_id="sm")
    svc.publish(mid, "statement", {"text": "The timer plugin is merged."}, actor_id="dev-1")
    clock.advance(12)
    svc.publish(mid, "challenge", {"text": "It ignores the speaking state."}, actor_id="dev-2", target_id="dev-1")
    svc.publish(mid, "clarification_requested", {"question_id": "q1", "text": "Should alerts wait for speech?"}, actor_id="dev-2")
    clock.advance(30)
    svc.publish(mid, "clarification_answered", {"question_id": "q1", "answer": "Yes, always."}, actor_id="sme")
    svc.publish(mid, "decision_proposed", {"decision_id": "d1", "title": "Queue alerts"}, actor_id="dev-3")
    svc.publish(mid, "decision_accepted", {"decision_id": "d1", "selected_option": "queue"}, actor_id="sme")
    svc.publish(mid, "action_item_created", {"action_item_id": "a1", "owner_id": "dev-1", "description": "Gate alerts on speech"}, actor_id="sm")
    svc.publish(mid, "meeting_ended", actor_id="system")
    return mid


def dump(state):
    return json.loads(json.dumps({
        "meeting": state.meeting, "people": list(state.participants.values()), "decisions": list(state.decisions.values()), "questions": list(state.questions.values()),
        "actions": list(state.actions.values()), "seq": state.last_sequence, "elapsed": state.last_elapsed, "speaker": state.speaker,
    }, default=lambda o: o.model_dump(mode="json")))


def test_replaying_the_stored_events_ends_where_the_live_meeting_ended():
    svc, clock = make_service()
    mid = a_busy_meeting(svc, clock)
    assert dump(svc.replay(mid)) == dump(svc.state(mid))
    halfway = svc.state_at(mid, 10)
    assert halfway.last_sequence == 10 and halfway.status != MeetingStatus.COMPLETED


def test_replay_scrubber_reaches_every_point_in_order():
    svc, clock = make_service()
    mid = a_busy_meeting(svc, clock)
    total = svc.state(mid).last_sequence
    seen = [svc.state_at(mid, n).last_sequence for n in range(1, total + 1)]
    assert seen == list(range(1, total + 1))
    assert svc.state_at(mid, 0).meeting is None


def test_a_meeting_survives_a_restart(tmp_path):
    svc, clock = make_service(JsonlEventStore(tmp_path))
    mid = a_busy_meeting(svc, clock)
    before = dump(svc.state(mid))
    reopened = MeetingService(WS, JsonlEventStore(tmp_path), clock=FixedClock(), ids=SequentialIds())  # a new process
    assert dump(reopened.state(mid)) == before
    assert [m.meeting_id for m in reopened.meetings()] == [mid]
    assert reopened.state(mid).status == MeetingStatus.COMPLETED


def test_a_meeting_that_was_running_when_the_process_stopped_carries_on(tmp_path):
    svc, clock = make_service(JsonlEventStore(tmp_path))
    mid = open_meeting(svc, devs=2)
    svc.publish(mid, "statement", {"text": "before the crash"}, actor_id="dev-1")
    reopened = MeetingService(WS, JsonlEventStore(tmp_path), clock=clock, ids=SequentialIds())
    event = reopened.publish(mid, "statement", {"text": "after the restart"}, actor_id="dev-2")
    assert event.sequence_number == svc.state(mid).last_sequence + 1
    assert reopened.replay(mid).last_sequence == event.sequence_number


def test_a_half_written_last_line_is_cut_off_and_the_meeting_goes_on(tmp_path, caplog):
    svc, clock = make_service(JsonlEventStore(tmp_path))
    mid = open_meeting(svc, devs=1)
    path = tmp_path / WS / mid / "events.jsonl"
    good = path.read_bytes()
    path.write_bytes(good + b'{"event_id":"evt-torn","event_type":"state')  # the power went out mid-write
    with caplog.at_level(logging.WARNING, logger="standup"):
        reopened = MeetingService(WS, JsonlEventStore(tmp_path), clock=clock, ids=SequentialIds())
        assert reopened.state(mid).status == MeetingStatus.ACTIVE
        reopened.publish(mid, "statement", {"text": "still here"}, actor_id="dev-1")
    assert "half-written" in caplog.text
    assert all(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())  # the file is whole JSON lines again


def test_damage_in_the_middle_of_a_stream_is_reported_not_skipped(tmp_path):
    svc, _ = make_service(JsonlEventStore(tmp_path))
    mid = open_meeting(svc, devs=1)
    path = tmp_path / WS / mid / "events.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[2] = "{this is not json"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(StoreError, match="damaged"):
        MeetingService(WS, JsonlEventStore(tmp_path)).state(mid)


def test_a_failed_write_is_retried_and_then_reported_without_changing_the_meeting():
    store = MemoryEventStore()
    svc, _ = make_service(store, retries=3)
    mid = open_meeting(svc, devs=1)
    before = svc.state(mid).last_sequence
    store.fail_next(2)  # two hiccups: the third attempt works
    svc.publish(mid, "statement", {"text": "survived"}, actor_id="dev-1")
    assert svc.state(mid).last_sequence == before + 1
    store.fail_next(5)
    with pytest.raises(StoreError):
        svc.publish(mid, "statement", {"text": "lost?"}, actor_id="dev-1")
    store.fail_next(0)
    assert svc.state(mid).last_sequence == before + 1 and svc.replay(mid).last_sequence == before + 1  # no half-applied event anywhere
    svc.publish(mid, "statement", {"text": "recovered"}, actor_id="dev-1")
    assert svc.state(mid).last_sequence == before + 2


def test_people_who_watch_are_told_only_after_the_event_is_stored_and_cannot_break_it():
    store = MemoryEventStore()
    seen = []

    class Watcher:
        def publish(self, event):
            seen.append((event.sequence_number, len(store.read(WS, event.meeting_id))))

    class Broken:
        def publish(self, event):
            raise RuntimeError("the screen is gone")

    class BrokenWriter:
        def write(self, event, state):
            raise OSError("disk full")

        def rebuild(self, *a):
            pass

    svc, _ = make_service(store, publishers=[Broken(), Watcher()], writers=[BrokenWriter()])
    mid = open_meeting(svc, devs=1)
    assert seen and all(stored >= seq for seq, stored in seen)  # when told, the event was already in the store
    assert svc.state(mid).status == MeetingStatus.ACTIVE


def test_a_workspace_cannot_reach_another_workspaces_meeting(tmp_path):
    store = JsonlEventStore(tmp_path)
    one, _ = make_service(store, workspace="ws-a")
    two, _ = make_service(store, workspace="ws-b")
    mid = open_meeting(one, devs=1)
    with pytest.raises(UnknownMeeting):
        two.state(mid)
    assert two.meetings() == [] and one.meetings()[0].meeting_id == mid
    assert [m.meeting_id for m in one.meetings()] == [mid]


def test_several_meetings_in_one_workspace_stay_apart():
    svc, _ = make_service()
    a, b = open_meeting(svc, devs=1, mid="alpha"), open_meeting(svc, devs=2, mid="beta")
    svc.publish(a, "statement", {"text": "in alpha"}, actor_id="dev-1")
    assert len(svc.state(a).participants) == 3 and len(svc.state(b).participants) == 4
    assert svc.state(b).speaker is None
    assert {m.meeting_id for m in svc.meetings()} == {"alpha", "beta"}


def test_no_id_can_climb_out_of_the_storage_folder(tmp_path):
    svc, _ = make_service(JsonlEventStore(tmp_path / "root"))
    for evil in ("..", "../x", "a/../../b", "C:\\evil", "x\x00y"):
        with pytest.raises(InvalidEvent):
            svc.publish(evil, "meeting_started", actor_id="system")
    assert not (tmp_path / "x").exists()


def test_events_published_from_many_threads_get_one_unbroken_sequence(tmp_path):
    svc, _ = make_service(JsonlEventStore(tmp_path))
    mid = open_meeting(svc, devs=4)
    errors = []

    def talk(dev):
        try:
            for i in range(25):
                svc.publish(mid, "statement", {"text": f"{dev} says {i}"}, actor_id=dev)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=talk, args=(f"dev-{i}",)) for i in range(1, 5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    events = svc.events(mid)
    assert [e.sequence_number for e in events] == list(range(1, len(events) + 1))
    assert sum(1 for e in events if e.event_type == "statement") == 100
    assert dump(svc.replay(mid)) == dump(svc.state(mid))


def test_secrets_never_reach_the_record():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=1)
    svc.publish(mid, "statement", {"text": "use key AIzaSyA12345678901234567890123456789012345 and token=ghp_abcdefghijklmnopqrstuv please", "nested": {"api_key": "supersecretvalue1"}}, actor_id="dev-1")
    event = svc.events(mid)[-1]
    blob = json.dumps(event.payload)
    assert "AIza" not in blob and "ghp_" not in blob and "supersecretvalue1" not in blob and "[redacted]" in blob
    assert redact("-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----") == "[redacted]"
    assert redact("nothing secret here") == "nothing secret here"


def test_the_transcript_reads_like_minutes_and_is_the_same_however_it_is_made(tmp_path):
    svc, clock = make_service(JsonlEventStore(tmp_path), writers=[FileProjections(tmp_path)])
    mid = open_meeting(svc, devs=3, meeting_type="sprint_review")
    svc.publish(mid, "skill_selected", {"participant_id": "dev-2", "skill": "backend"}, actor_id="system")
    svc.publish(mid, "role_assigned", {"participant_id": "dev-2", "role": "adversarial reviewer"}, actor_id="sm")
    clock.advance(72)
    svc.publish(mid, "statement", {"text": "The proposed service split is premature."}, actor_id="dev-2")
    svc.publish(mid, "decision_proposed", {"decision_id": "d1", "title": "Keep one process"}, actor_id="dev-1")
    svc.publish(mid, "decision_accepted", {"decision_id": "d1", "selected_option": "one process"}, actor_id="sme")
    svc.publish(mid, "meeting_ended", actor_id="system")
    text = (tmp_path / WS / mid / "transcript.txt").read_text(encoding="utf-8")
    assert "[00:01:12] Developer 02 [backend] (adversarial reviewer) — Statement:\nThe proposed service split is premature." in text
    assert "Decision accepted: Keep one process -> one process" in text and "Meeting created: Discovery" in text
    assert text == render_transcript(svc.events(mid))  # appended line by line == rendered from the events at once
    (tmp_path / WS / mid / "transcript.txt").unlink()
    svc.rebuild_projections(mid)
    assert (tmp_path / WS / mid / "transcript.txt").read_text(encoding="utf-8") == text  # and it can always be rebuilt
    assert format_elapsed(3725) == "01:02:05" and format_elapsed(-5) == "00:00:00"


def test_the_json_summaries_follow_the_meeting(tmp_path):
    svc, clock = make_service(JsonlEventStore(tmp_path), writers=[FileProjections(tmp_path)])
    mid = a_busy_meeting(svc, clock)
    folder = tmp_path / WS / mid
    decisions = json.loads((folder / "decisions.json").read_text(encoding="utf-8"))
    questions = json.loads((folder / "questions.json").read_text(encoding="utf-8"))
    actions = json.loads((folder / "action-items.json").read_text(encoding="utf-8"))
    meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    assert decisions[0]["status"] == "accepted" and questions[0]["answer"] == "Yes, always." and actions[0]["owner_id"] == "dev-1"
    assert meta["meeting"]["status"] == "completed" and meta["last_sequence"] == svc.state(mid).last_sequence
    assert len(json.loads((folder / "participants.json").read_text(encoding="utf-8"))) == 5
    assert not list(folder.glob("*.tmp"))


def test_the_same_inputs_give_the_same_record():
    one, c1 = make_service()
    two, c2 = make_service()
    m1, m2 = a_busy_meeting(one, c1), a_busy_meeting(two, c2)
    assert [e.wire() for e in one.events(m1)] == [e.wire() for e in two.events(m2)]  # injected clock and ids make a meeting reproducible
