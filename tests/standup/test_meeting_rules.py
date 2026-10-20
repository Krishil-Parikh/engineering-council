import pytest

from standup.enums import ControlMode, DecisionStatus, MeetingStatus, ParticipantStatus, ReviewStatus
from standup.errors import InvalidEvent, InvalidTransition, OutOfOrder, UnknownMeeting
from standup.events import MeetingEvent
from tests.standup.helpers import WS, join, make_service, open_meeting


def test_a_meeting_goes_through_its_life_in_order():
    svc, clock = make_service()
    mid = svc.create_meeting("Kickoff", "discovery", duration_limit_seconds=3600)
    assert svc.state(mid).status == MeetingStatus.CREATED
    join(svc, mid, "dev-1", "Developer 01")
    assert svc.state(mid).status == MeetingStatus.WAITING_FOR_PARTICIPANTS
    svc.publish(mid, "meeting_started", actor_id="system")
    assert svc.state(mid).status == MeetingStatus.ACTIVE
    svc.publish(mid, "meeting_paused", actor_id="system")
    assert svc.state(mid).status == MeetingStatus.PAUSED
    svc.publish(mid, "meeting_resumed", actor_id="system")
    assert svc.state(mid).status == MeetingStatus.ACTIVE
    svc.publish(mid, "meeting_ended", actor_id="system")
    assert svc.state(mid).status == MeetingStatus.COMPLETED
    assert svc.state(mid).meeting.ended_at is not None
    assert all(p.status == ParticipantStatus.FINISHED for p in svc.state(mid).participants.values())


@pytest.mark.parametrize("event,payload", [("statement", {"text": "hi"}), ("meeting_paused", {}), ("meeting_ended", {}), ("topic_started", {"topic": "x"})])
def test_nothing_but_setup_happens_before_the_meeting_starts(event, payload):
    svc, _ = make_service()
    mid = svc.create_meeting("Kickoff", "discovery")
    with pytest.raises(InvalidTransition):
        svc.publish(mid, event, payload, actor_id="system")


def test_a_paused_meeting_takes_no_talk_and_a_finished_one_takes_nothing():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=2)
    svc.publish(mid, "meeting_paused", actor_id="system")
    with pytest.raises(InvalidTransition):
        svc.publish(mid, "statement", {"text": "hello"}, actor_id="dev-1")
    with pytest.raises(InvalidTransition):
        svc.publish(mid, "meeting_paused", actor_id="system")  # already paused
    svc.publish(mid, "meeting_resumed", actor_id="system")
    with pytest.raises(InvalidTransition):
        svc.publish(mid, "meeting_resumed", actor_id="system")
    svc.publish(mid, "meeting_ended", actor_id="system")
    for event, payload in (("statement", {"text": "late"}), ("meeting_started", {}), ("participant_joined", {"participant_id": "x", "display_name": "X", "participant_type": "developer"})):
        with pytest.raises(InvalidTransition):
            svc.publish(mid, event, payload, actor_id="system")


def test_the_clock_does_not_run_while_paused_and_a_late_meeting_times_out():
    svc, clock = make_service()
    mid = open_meeting(svc, devs=1, duration_limit_seconds=100)
    clock.advance(30)
    svc.publish(mid, "statement", {"text": "a"}, actor_id="dev-1")
    svc.publish(mid, "meeting_paused", actor_id="system")
    clock.advance(500)  # a long pause costs the meeting nothing
    svc.publish(mid, "meeting_resumed", actor_id="system")
    state = svc.state(mid)
    assert state.elapsed_at(clock.now()) == pytest.approx(30)
    assert state.remaining_at(clock.now()) == pytest.approx(70)
    assert svc.check_timeouts() == []
    clock.advance(80)
    assert svc.check_timeouts() == [mid]
    assert svc.state(mid).status == MeetingStatus.TIMED_OUT
    assert svc.check_timeouts() == []  # only once


def test_people_come_and_go_and_nobody_leaves_without_having_joined():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=2)
    svc.publish(mid, "participant_left", {"participant_id": "dev-2"}, actor_id="system")
    assert svc.state(mid).participants["dev-2"].status == ParticipantStatus.LEFT
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "participant_left", {"participant_id": "dev-2"}, actor_id="system")  # already left
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "participant_left", {"participant_id": "ghost"}, actor_id="system")
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "statement", {"text": "I left"}, actor_id="dev-2")
    with pytest.raises(InvalidEvent):
        join(svc, mid, "dev-1", "Developer 01 again")  # already here
    join(svc, mid, "dev-2", "Developer 02")  # a person who left may come back
    assert svc.state(mid).participants["dev-2"].status == ParticipantStatus.JOINED


@pytest.mark.parametrize("devs", [0, 1, 6, 8, 13])
def test_any_number_of_developers_can_take_part(devs):
    svc, _ = make_service()
    mid = open_meeting(svc, devs=devs)
    people = svc.state(mid).participants
    assert len([p for p in people.values() if p.participant_type == "developer"]) == devs
    for i in range(1, devs + 1):
        svc.publish(mid, "statement", {"text": f"from {i}"}, actor_id=f"dev-{i}")
    assert svc.state(mid).speaker == (f"dev-{devs}" if devs else None)


def test_skills_and_roles_are_choices_for_this_meeting_and_can_repeat():
    svc, _ = make_service()
    first = open_meeting(svc, devs=3, mid="m-one")
    for dev in ("dev-1", "dev-2"):
        svc.publish(first, "skill_selected", {"participant_id": dev, "skill": "backend"}, actor_id="system")  # two developers, one skill
    svc.publish(first, "skill_selected", {"participant_id": "dev-3", "skill": "devops"}, actor_id="system")
    svc.publish(first, "role_assigned", {"participant_id": "dev-2", "role": "adversarial reviewer"}, actor_id="sm")
    people = svc.state(first).participants
    assert people["dev-1"].skill == people["dev-2"].skill == "backend"
    assert people["dev-2"].temporary_meeting_role == "adversarial reviewer" and people["dev-1"].temporary_meeting_role is None
    second = open_meeting(svc, devs=3, mid="m-two")
    svc.publish(second, "skill_selected", {"participant_id": "dev-1", "skill": "database"}, actor_id="system")  # the same developer, another skill
    assert svc.state(second).participants["dev-1"].skill == "database" and svc.state(first).participants["dev-1"].skill == "backend"
    with pytest.raises(InvalidEvent):
        svc.publish(second, "skill_selected", {"participant_id": "ghost", "skill": "x"}, actor_id="system")


def test_talk_moves_the_spotlight_and_challenges_are_kept():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=3)
    svc.publish(mid, "statement", {"text": "Let us split the service."}, actor_id="dev-1")
    assert svc.state(mid).speaker == "dev-1" and svc.state(mid).participants["dev-1"].status == ParticipantStatus.SPEAKING
    svc.publish(mid, "brainstorm", {"text": "Or keep one process."}, actor_id="dev-2")
    svc.publish(mid, "challenge", {"text": "We do not know the traffic."}, actor_id="dev-3", target_id="dev-1")
    svc.publish(mid, "counterargument", {"text": "Then measure first."}, actor_id="dev-1")
    state = svc.state(mid)
    assert state.speaker == "dev-1"
    assert state.participants["dev-2"].status == ParticipantStatus.LISTENING and state.participants["dev-3"].status == ParticipantStatus.LISTENING
    assert [e.event_type for e in state.recent][-4:] == ["statement", "brainstorm", "challenge", "counterargument"]
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "statement", {"text": ""}, actor_id="dev-1")  # nothing to say
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "statement", {"text": "from a stranger"}, actor_id="stranger")


def test_a_question_for_the_business_sme_pauses_the_asker_until_it_is_answered():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=2)
    svc.publish(mid, "clarification_requested", {"question_id": "q1", "text": "Do timers survive a restart?", "options": ["yes", "no"], "recommended": "no"}, actor_id="dev-1")
    state = svc.state(mid)
    assert state.status == MeetingStatus.WAITING_FOR_SME
    assert state.participants["sme"].status == ParticipantStatus.NEEDS_SME and state.participants["dev-1"].status == ParticipantStatus.WAITING
    assert state.open_questions()[0].recommended == "no"
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "clarification_requested", {"question_id": "q1", "text": "again"}, actor_id="dev-2")  # same id
    svc.publish(mid, "clarification_answered", {"question_id": "q1", "answer": "no, memory only"}, actor_id="sme")
    state = svc.state(mid)
    assert state.status == MeetingStatus.ACTIVE and state.questions["q1"].answer == "no, memory only" and state.questions["q1"].answered_by == "sme"
    assert state.participants["sme"].status == ParticipantStatus.LISTENING and state.participants["dev-1"].status == ParticipantStatus.LISTENING
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "clarification_answered", {"question_id": "q1", "answer": "twice"}, actor_id="sme")
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "clarification_answered", {"question_id": "never-asked", "answer": "x"}, actor_id="sme")


def test_the_sme_stays_needed_until_every_question_is_answered():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=2)
    svc.publish(mid, "question", {"question_id": "a", "text": "A?"}, actor_id="dev-1")
    svc.publish(mid, "question", {"question_id": "b", "text": "B?"}, actor_id="dev-2")
    svc.publish(mid, "clarification_answered", {"question_id": "a", "answer": "yes"}, actor_id="sme")
    assert svc.state(mid).status == MeetingStatus.WAITING_FOR_SME and svc.state(mid).participants["sme"].status == ParticipantStatus.NEEDS_SME
    svc.publish(mid, "clarification_answered", {"question_id": "b", "answer": "yes"}, actor_id="sme")
    assert svc.state(mid).status == MeetingStatus.ACTIVE


def test_a_question_between_developers_does_not_stop_the_meeting_for_the_sme():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=2)
    svc.publish(mid, "question", {"question_id": "d", "text": "Can you take the router?", "target": "dev-2"}, actor_id="dev-1")
    assert svc.state(mid).status == MeetingStatus.ACTIVE
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "question", {"question_id": "e", "text": "Hello?", "target": "nobody"}, actor_id="dev-1")


def test_control_passes_between_a_human_and_autopilot():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=1, control_mode="autopilot")
    assert svc.state(mid).meeting.control_mode == ControlMode.AUTOPILOT
    svc.publish(mid, "human_takeover", actor_id="sme")
    assert svc.state(mid).meeting.control_mode == ControlMode.HUMAN
    svc.publish(mid, "autopilot_enabled", actor_id="sme")
    assert svc.state(mid).meeting.control_mode == ControlMode.AUTOPILOT
    svc.publish(mid, "meeting_paused", actor_id="system")
    svc.publish(mid, "human_takeover", actor_id="sme")  # allowed while paused
    assert svc.state(mid).meeting.control_mode == ControlMode.HUMAN


def test_a_decision_must_be_proposed_before_it_is_settled_and_only_once():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=2)
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "decision_accepted", {"decision_id": "d1"}, actor_id="sme")
    svc.publish(mid, "decision_proposed", {"decision_id": "d1", "title": "Timers in memory", "alternatives": ["memory", "sqlite"]}, actor_id="dev-1")
    svc.publish(mid, "decision_deferred", {"decision_id": "d1"}, actor_id="sm")
    assert svc.state(mid).decisions["d1"].status == DecisionStatus.DEFERRED
    svc.publish(mid, "decision_accepted", {"decision_id": "d1", "selected_option": "memory"}, actor_id="sme")
    d = svc.state(mid).decisions["d1"]
    assert d.status == DecisionStatus.ACCEPTED and d.selected_option == "memory" and d.decided_by == "sme" and d.proposed_by == "dev-1"
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "decision_rejected", {"decision_id": "d1"}, actor_id="sme")
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "decision_proposed", {"decision_id": "d1", "title": "again"}, actor_id="dev-2")
    svc.publish(mid, "decision_proposed", {"decision_id": "d2", "title": "Persist timers"}, actor_id="dev-2")
    svc.publish(mid, "decision_rejected", {"decision_id": "d2", "reason": "out of scope"}, actor_id="sme")
    assert svc.state(mid).decisions["d2"].status == DecisionStatus.REJECTED and svc.state(mid).decisions["d2"].reason == "out of scope"


def test_action_items_can_be_created_and_moved_along():
    svc, clock = make_service()
    mid = open_meeting(svc, devs=2)
    svc.publish(mid, "action_item_created", {"action_item_id": "a1", "owner_id": "dev-2", "description": "Write the timer tests", "due_reference": "sprint 2"}, actor_id="sm")
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "action_item_created", {"action_item_id": "a1", "owner_id": "dev-1", "description": "dup"}, actor_id="sm")
    svc.publish(mid, "action_item_updated", {"action_item_id": "a1", "status": "in_progress"}, actor_id="dev-2")
    svc.publish(mid, "action_item_updated", {"action_item_id": "a1", "status": "done"}, actor_id="dev-2")
    item = svc.state(mid).actions["a1"]
    assert item.status.value == "done" and item.completed_at is not None and item.due_reference == "sprint 2"
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "action_item_updated", {"action_item_id": "a1", "status": "someday"}, actor_id="dev-2")
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "action_item_updated", {"action_item_id": "nope", "status": "done"}, actor_id="dev-2")


def test_documents_are_reviewed_and_the_sme_approves_or_rejects():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=2, meeting_type="prd_review")
    svc.publish(mid, "document_created", {"path": "PRD.md"}, actor_id="sm")
    svc.publish(mid, "document_review_started", {"path": "PRD.md", "reviewer_id": "dev-1"}, actor_id="sm")
    assert svc.state(mid).status == MeetingStatus.REVIEWING
    svc.publish(mid, "document_changes_requested", {"path": "PRD.md", "comments": ["add timers", "add limits"]}, actor_id="dev-1")
    review = svc.state(mid).reviews["PRD.md"]
    assert review.status == ReviewStatus.CHANGES_REQUESTED and review.comments == ["add timers", "add limits"] and svc.state(mid).status == MeetingStatus.ACTIVE
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "document_approved", {"path": "PRD.md"}, actor_id="dev-1")  # no longer under review
    svc.publish(mid, "document_review_started", {"path": "PRD.md"}, actor_id="sm")
    svc.publish(mid, "sme_approval_requested", {"request_id": "r1", "subject": "Accept PRD.md"}, actor_id="sm")
    assert svc.state(mid).status == MeetingStatus.AWAITING_APPROVAL
    svc.publish(mid, "sme_approved", {"request_id": "r1", "comment": "good"}, actor_id="sme")
    svc.publish(mid, "document_approved", {"path": "PRD.md"}, actor_id="sme")
    assert svc.state(mid).reviews["PRD.md"].status == ReviewStatus.APPROVED and svc.state(mid).status == MeetingStatus.ACTIVE
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "sme_rejected", {"request_id": "r1"}, actor_id="sme")  # already closed
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "sme_approved", {"request_id": "unknown"}, actor_id="sme")


def test_blockers_risks_and_dependencies_are_recorded():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=2)
    svc.publish(mid, "participant_blocked", {"participant_id": "dev-1", "reason": "waiting for the bus"}, actor_id="dev-1")
    assert svc.state(mid).participants["dev-1"].status == ParticipantStatus.BLOCKED
    svc.publish(mid, "risk_raised", {"risk_id": "r1", "text": "ticks drift", "severity": "high"}, actor_id="dev-2")
    svc.publish(mid, "dependency_identified", {"dependency_id": "x1", "text": "timer needs the clock port", "from": "dev-1", "to": "dev-2"}, actor_id="dev-2")
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "risk_raised", {"risk_id": "r1", "text": "dup"}, actor_id="dev-2")
    svc.publish(mid, "participant_unblocked", {"participant_id": "dev-1"}, actor_id="system")
    assert svc.state(mid).participants["dev-1"].status == ParticipantStatus.LISTENING and svc.state(mid).risks["r1"].severity == "high"
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "participant_unblocked", {"participant_id": "dev-1"}, actor_id="system")


def test_the_contract_refuses_what_it_does_not_know_or_what_is_incomplete():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=1)
    for bad in (("shout", {"text": "x"}), ("decision_proposed", {"decision_id": "d"}), ("participant_joined", {"participant_id": "p"}), ("question", {"text": "no id"})):
        with pytest.raises(InvalidEvent):
            svc.publish(mid, bad[0], bad[1], actor_id="dev-1")
    with pytest.raises(InvalidEvent):
        svc.create_meeting("x", "not-a-type")
    for unsafe in ("../escape", "a/b", "", "x" * 200, ".hidden"):
        with pytest.raises(InvalidEvent):
            svc.publish(unsafe, "statement", {"text": "x"}, actor_id="dev-1")
    with pytest.raises(UnknownMeeting):
        svc.publish("never-created", "statement", {"text": "x"}, actor_id="dev-1")
    assert svc.state(mid).last_sequence == len(svc.events(mid))  # none of the refusals left a trace


def test_a_meeting_cannot_be_created_twice_but_asking_again_is_harmless():
    svc, _ = make_service()
    mid = svc.create_meeting("One", "discovery", meeting_id="same")
    assert svc.create_meeting("One", "discovery", meeting_id="same") == mid  # same idempotency key: the first creation stands
    assert len(svc.events(mid)) == 1
    with pytest.raises(InvalidTransition):
        svc.publish(mid, "meeting_created", {"title": "Two", "meeting_type": "custom"}, actor_id="system")


def test_events_are_numbered_without_gaps_and_old_or_skipped_events_are_refused():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=2)
    svc.publish(mid, "statement", {"text": "a"}, actor_id="dev-1")
    svc.publish(mid, "statement", {"text": "b"}, actor_id="dev-2")
    events = svc.events(mid)
    assert [e.sequence_number for e in events] == list(range(1, len(events) + 1))
    assert all(a.elapsed_seconds <= b.elapsed_seconds for a, b in zip(events, events[1:]))
    state = svc.state(mid)
    last = events[-1]
    assert state.apply(last) is False  # the same event again changes nothing
    gap = MeetingEvent(event_id="evt-x", event_type="statement", meeting_id=mid, workspace_id=WS, sequence_number=last.sequence_number + 2, timestamp=last.timestamp, elapsed_seconds=last.elapsed_seconds,
                       actor_id="dev-1", payload={"text": "skipped one"})
    with pytest.raises(OutOfOrder) as caught:
        state.apply(gap)
    assert caught.value.expected == last.sequence_number + 1
    clash = gap.model_copy(update={"sequence_number": last.sequence_number, "event_id": "evt-other"})
    with pytest.raises(InvalidEvent):
        state.apply(clash)  # another event claiming a used number
    backwards = gap.model_copy(update={"sequence_number": last.sequence_number + 1, "elapsed_seconds": 0.0, "timestamp": last.timestamp})
    if last.elapsed_seconds > 0:
        with pytest.raises(InvalidEvent):
            state.apply(backwards)
    assert state.last_sequence == last.sequence_number


def test_an_idempotency_key_makes_a_retry_harmless():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=1)
    first = svc.publish(mid, "statement", {"text": "once"}, actor_id="dev-1", idempotency_key="k-1")
    again = svc.publish(mid, "statement", {"text": "once"}, actor_id="dev-1", idempotency_key="k-1")
    assert again.event_id == first.event_id
    assert sum(1 for e in svc.events(mid) if e.event_type == "statement") == 1


def test_an_event_of_a_kind_this_version_does_not_know_is_kept_and_ignored():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=1)
    state = svc.state(mid)
    future = MeetingEvent(event_id="evt-future", event_type="hologram_started", meeting_id=mid, workspace_id=WS, sequence_number=state.last_sequence + 1, timestamp=state.last_timestamp,
                          elapsed_seconds=state.last_elapsed, payload={"anything": 1}, schema_version=7)
    svc.store.append(WS, future)  # a newer producer wrote it
    fresh = svc.replay(mid)
    assert fresh.unknown_events == 1 and fresh.last_sequence == future.sequence_number and fresh.status == MeetingStatus.ACTIVE
    with pytest.raises(InvalidEvent):
        svc.publish(mid, "hologram_started", {}, actor_id="dev-1")  # but nobody may publish it here
