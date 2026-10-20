import copy
import json
import random

import pytest

from standup.enums import DecisionStatus, MeetingStatus, QuestionStatus
from standup.errors import StandupError
from standup.presentation import build_view, translate
from standup.state import MeetingState
from tests.standup.helpers import make_service, open_meeting

TYPES = [
    ("statement", lambda r, c: {"text": f"s{r.randint(0, 99)}"}), ("brainstorm", lambda r, c: {"text": "idea"}), ("proposal", lambda r, c: {"text": "do x"}),
    ("challenge", lambda r, c: {"text": "no"}), ("counterargument", lambda r, c: {"text": "yes"}),
    ("clarification_requested", lambda r, c: {"question_id": f"q{r.randint(0, 5)}", "text": "?"}),
    ("clarification_answered", lambda r, c: {"question_id": f"q{r.randint(0, 5)}", "answer": "a"}),
    ("decision_proposed", lambda r, c: {"decision_id": f"d{r.randint(0, 5)}", "title": "t"}),
    ("decision_accepted", lambda r, c: {"decision_id": f"d{r.randint(0, 5)}"}), ("decision_rejected", lambda r, c: {"decision_id": f"d{r.randint(0, 5)}"}),
    ("decision_deferred", lambda r, c: {"decision_id": f"d{r.randint(0, 5)}"}),
    ("action_item_created", lambda r, c: {"action_item_id": f"a{r.randint(0, 5)}", "owner_id": "dev-1", "description": "do"}),
    ("action_item_updated", lambda r, c: {"action_item_id": f"a{r.randint(0, 5)}", "status": r.choice(["open", "done", "in_progress", "dropped"])}),
    ("participant_left", lambda r, c: {"participant_id": f"dev-{r.randint(1, 4)}"}),
    ("participant_joined", lambda r, c: {"participant_id": f"dev-{r.randint(1, 6)}", "display_name": "D", "participant_type": "developer"}),
    ("meeting_paused", lambda r, c: {}), ("meeting_resumed", lambda r, c: {}), ("risk_raised", lambda r, c: {"risk_id": f"r{r.randint(0, 5)}", "text": "risk"}),
    ("participant_blocked", lambda r, c: {"participant_id": f"dev-{r.randint(1, 4)}"}), ("participant_unblocked", lambda r, c: {"participant_id": f"dev-{r.randint(1, 4)}"}),
    ("document_review_started", lambda r, c: {"path": "PRD.md"}), ("document_approved", lambda r, c: {"path": "PRD.md"}),
    ("sme_approval_requested", lambda r, c: {"request_id": f"r{r.randint(0, 3)}", "subject": "ok?"}), ("sme_approved", lambda r, c: {"request_id": f"r{r.randint(0, 3)}"}),
    ("human_takeover", lambda r, c: {}), ("autopilot_enabled", lambda r, c: {}),
]


def random_meeting(seed, steps=80):
    rng = random.Random(seed)
    svc, clock = make_service()
    mid = open_meeting(svc, devs=4)
    for _ in range(steps):
        clock.advance(rng.choice([0, 1, 5, 30]))
        name, payload = rng.choice(TYPES)
        actor = rng.choice(["dev-1", "dev-2", "dev-3", "dev-4", "sme", "sm", "ghost"])
        try:
            svc.publish(mid, name, payload(rng, clock), actor_id=actor)
        except StandupError:
            pass  # most random events are impossible; the point is that the survivors always make a consistent meeting
        if rng.random() < 0.01 and svc.state(mid).status not in (MeetingStatus.COMPLETED,):
            try:
                svc.publish(mid, "meeting_ended", actor_id="system")
            except StandupError:
                pass
    return svc, mid


@pytest.mark.parametrize("seed", range(40))
def test_whatever_happens_the_record_stays_consistent(seed):
    svc, mid = random_meeting(seed)
    events = svc.events(mid)
    live = svc.state(mid)
    assert [e.sequence_number for e in events] == list(range(1, len(events) + 1))  # strictly increasing, no gaps
    assert all(a.elapsed_seconds <= b.elapsed_seconds for a, b in zip(events, events[1:]))  # time never runs backwards
    fresh = svc.replay(mid)
    assert json.dumps(fresh.meeting, default=lambda o: o.model_dump(mode="json")) == json.dumps(live.meeting, default=lambda o: o.model_dump(mode="json"))  # replay == live
    assert {k: v.status for k, v in fresh.decisions.items()} == {k: v.status for k, v in live.decisions.items()}
    before = copy.deepcopy(live.decisions)
    assert all(live.apply(e) is False for e in events[-20:])  # applying the same events again changes nothing
    assert live.decisions == before and live.last_sequence == len(events)
    types = [e.event_type for e in events]
    proposed = {e.payload["decision_id"] for e in events if e.event_type == "decision_proposed"}
    assert all(d in proposed for d, v in live.decisions.items() if v.status != DecisionStatus.PROPOSED)  # nothing is settled that was not proposed
    asked = {e.payload["question_id"] for e in events if e.event_type in ("question", "clarification_requested")}
    assert all(q in asked for q, v in live.questions.items() if v.status == QuestionStatus.ANSWERED)
    if live.status == MeetingStatus.COMPLETED:
        assert "meeting_started" in types  # a finished meeting did start
    joined = {e.payload["participant_id"] for e in events if e.event_type == "participant_joined"}
    assert all(e.payload["participant_id"] in joined for e in events if e.event_type == "participant_left")


@pytest.mark.parametrize("seed", range(10))
def test_a_prefix_of_the_record_is_a_valid_meeting_too(seed):
    svc, mid = random_meeting(seed, steps=40)
    total = svc.state(mid).last_sequence
    for cut in range(1, total + 1, 7):
        part = MeetingState()
        part.apply_all(svc.events(mid)[:cut])
        assert part.last_sequence == cut


def test_unknown_events_never_corrupt_the_projection():
    svc, mid = random_meeting(3, steps=30)
    state = svc.state(mid)
    expected = copy.deepcopy(state.decisions), state.status
    from standup.events import MeetingEvent

    junk = MeetingEvent(event_id="evt-junk", event_type="future_thing", meeting_id=mid, workspace_id="ws-1", sequence_number=state.last_sequence + 1, timestamp=state.last_timestamp,
                        elapsed_seconds=state.last_elapsed, payload={"anything": [1, 2, 3]})
    assert state.apply(junk) is True and state.unknown_events == 1
    assert (state.decisions, state.status) == expected


def test_the_view_lists_who_needs_attention_first_and_shows_the_open_question():
    svc, clock = make_service()
    mid = open_meeting(svc, devs=3, duration_limit_seconds=600)
    svc.publish(mid, "skill_selected", {"participant_id": "dev-1", "skill": "backend"}, actor_id="system")
    svc.publish(mid, "statement", {"text": "Let us begin."}, actor_id="dev-2")
    svc.publish(mid, "participant_blocked", {"participant_id": "dev-3", "reason": "needs the bus"}, actor_id="dev-3")
    clock.advance(120)
    svc.publish(mid, "clarification_requested", {"question_id": "q1", "text": "Memory only?", "options": ["yes", "no"]}, actor_id="dev-1")
    view = build_view(svc.state(mid), clock.now())
    order = [p.display_name for p in view.participants]
    assert order[0] == "Business SME" and view.participants[0].needs_sme and view.participants[0].badge == "needs you"
    assert order.index("Developer 03") < order.index("Developer 02")  # blocked before speaking before the rest
    assert view.status == "waiting_for_sme" and view.pending_question.question_id == "q1" and view.pending_question.options == ["yes", "no"]
    assert view.elapsed == "00:02:00" and view.remaining_seconds == pytest.approx(480) and view.control_mode == "human"
    assert any(p.skill == "backend" for p in view.participants)
    assert view.recent[-1].tone == "ask" and view.recent[-1].actor_name == "Developer 01" and view.recent[-1].kind == "standup.clarification_requested"


def test_translating_an_event_is_pure_and_names_people_not_ids():
    svc, _ = make_service()
    mid = open_meeting(svc, devs=2)
    svc.publish(mid, "challenge", {"text": "That is premature."}, actor_id="dev-2", target_id="dev-1")
    state = svc.state(mid)
    event = svc.events(mid)[-1]
    first, second = translate(event, state), translate(event, state)
    assert first == second and first.text == "to Developer 01: That is premature." and first.actor_name == "Developer 02" and first.tone == "warn"
    assert build_view(state, state.last_timestamp).recent[-1] == first


def test_a_view_of_a_meeting_that_was_never_created_is_an_error():
    with pytest.raises(ValueError):
        build_view(MeetingState(), __import__("datetime").datetime.now())
