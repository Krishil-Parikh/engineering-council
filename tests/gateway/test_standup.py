import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from gateway import autopilot
from gateway.autopilot import SmeAnswer
from gateway.models import Question
from gateway.standup_hub import StandupHub, classify
from standup.enums import ControlMode, MeetingStatus
from tests.gateway.conftest import WORKSPACE, command

BASE = f"/workspace/{WORKSPACE}/standup"


@pytest.fixture
def run(client):
    return client.app.state.hub.get(WORKSPACE)


def say(run, key, who, text, hint=None, **kw):
    run.standup.hint = hint
    try:
        return run.narrator.say(key, who, text, **kw)
    finally:
        run.standup.hint = None


def types(run, mid):
    return [e.event_type for e in run.standup.service.events(mid)]


@pytest.mark.parametrize("meet_id,expected", [
    ("meet-01", ("discovery", "kickoff")), ("meet-plan", ("sprint_planning", "work-plan")), ("meet-prd", ("prd_review", "document-review")),
    ("meet-decisions", ("sme_checkpoint", "decisions")), ("meet-s2-standup3", ("daily_standup", "s2-standup3")), ("meet-s1-review", ("sprint_review", "s1-review")),
    ("meet-s3-retro", ("sprint_retrospective", "s3-retro")), ("meet-design-bus-or-queue", ("design_review", "design-bus-or-queue")),
])
def test_the_formal_meetings_are_recognised(meet_id, expected):
    kind, mid = classify(meet_id)
    assert (kind.value, mid) == expected


@pytest.mark.parametrize("meet_id", ["meet-merge", "meet-team", "meet-briefings", "meet-s1-nonsense", "meet-"])
def test_merge_talk_and_team_chatter_are_not_scrum_meetings(meet_id):
    assert classify(meet_id) is None


def test_only_formal_meetings_reach_the_record(run):
    run.narrator.meet("merge", "Merge conflicts", "live")
    say(run, "merge", "DEV_1", "resolving a conflict in contracts.py")
    say(run, "team", "DEV_2", "chatter")
    run.narrator.meet("s1-standup1", "Sprint 1 standup 1", "live")
    say(run, "s1-standup1", "DEV_3", "Yesterday: the router. Today: tests. Blockers: none.")
    run.standup.flush()
    assert [m.meeting_id for m in run.standup.service.meetings()] == ["s1-standup1"]


def test_contributions_become_the_right_kind_of_event(run):
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    say(run, "01", "DEV_1", "We could keep timers in memory.", hint="proposal")
    say(run, "01", "DEV_2", "That loses them on restart.", hint="objection")
    say(run, "01", "DEV_1", "The brief says memory only.", hint="rebuttal")
    say(run, "01", "DEV_3", "A first thought.", hint="blind")
    say(run, "01", "scrum-master", "Timers stay in memory.\n\nBecause the brief says so.", hint="decision")
    say(run, "01", "scrum-master", "[3/10] Each developer re-thinks the problem", kind="system")
    say(run, "01", "scrum-master", "Warning: one developer was slow", kind="system")
    run.standup.flush()
    seen = types(run, "kickoff")
    assert ["proposal", "challenge", "counterargument", "brainstorm", "decision_proposed", "decision_accepted", "topic_started", "facilitator_intervention"] == [t for t in seen if t not in
        ("meeting_created", "participant_joined", "meeting_started")]
    state = run.standup.service.state("kickoff")
    assert [d.title for d in state.decisions.values()] == ["Timers stay in memory."] and state.participants["agent-02"].display_name == "DEV_2"
    assert state.participants["sme-01"].participant_type == "business_sme" and state.participants["agent-sm"].participant_type == "scrum_master"


def test_a_product_question_waits_for_the_human_and_the_answer_is_recorded(run):
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    got = []
    qid = run.questions.open("01", "meeting", "Do timers survive a restart?", "Why: changes storage.", ["Yes", "No"], "No", got.append)
    run.standup.flush()
    state = run.standup.service.state("kickoff")
    assert state.status == MeetingStatus.WAITING_FOR_SME and state.questions[qid].options == ["Yes", "No"] and state.questions[qid].recommended == "No"
    run.questions.answer("No, memory only", qid)
    run.standup.flush()
    state = run.standup.service.state("kickoff")
    assert state.status == MeetingStatus.ACTIVE and state.questions[qid].answer == "No, memory only" and got == ["No, memory only"]
    answered = [e for e in run.standup.service.events("kickoff") if e.event_type == "clarification_answered"][0]
    assert answered.actor_id == "sme-01" and answered.payload["source"] == "human"


def test_approvals_are_recorded_as_the_sme_approving_or_declining(run):
    run.narrator.meet("decisions", "Decisions waiting for you", "live")
    a = run.questions.open("decisions", "approval", "Add a new dependency?", "", ["Approve", "Decline"], None, lambda t: None)
    b = run.questions.open("decisions", "approval", "Change the public API?", "", ["Approve", "Decline"], None, lambda t: None)
    run.standup.flush()
    assert run.standup.service.state("decisions").status == MeetingStatus.AWAITING_APPROVAL
    run.questions.answer("Approve", a)
    run.questions.answer("Decline: too risky", b)
    run.standup.flush()
    approvals = run.standup.service.state("decisions").approvals
    assert approvals[a].approved is True and approvals[b].approved is False and approvals[b].comment == "Decline: too risky"
    assert run.standup.service.state("decisions").status == MeetingStatus.ACTIVE  # nothing is waiting any more


def test_a_ceremony_marked_complete_keeps_taking_talk_and_a_late_line_goes_to_a_follow_up(run):
    run.narrator.meet("s1-planning", "Sprint 1 planning", "live")
    say(run, "s1-planning", "scrum-master", "Sprint 1 planned: storage")
    run.narrator.meet("s1-planning", "Sprint 1 planning", "completed")
    say(run, "s1-planning", "DEV_1", "Commit: True")  # said after it was marked completed: still part of it
    run.standup.flush()  # now the quiet period is over and the meeting ends
    say(run, "s1-planning", "DEV_2", "Goal: the API serves data")  # and this comes much later
    run.standup.flush()
    ids = {m.meeting_id: m for m in run.standup.service.meetings()}
    assert ids["s1-planning"].status == MeetingStatus.COMPLETED and "Commit: True" in " ".join(str(e.payload) for e in run.standup.service.events("s1-planning"))
    assert "s1-planning-followup" in ids and ids["s1-planning-followup"].title == "Sprint 1 planning (follow-up)"
    assert run.standup.dropped == 0


def test_documents_under_review_are_tracked_until_approved(run):
    doc = {"id": "art-prd", "title": "PRD", "filename": "PRD.md", "status": "draft", "currentVersion": "v1.0"}
    run.p.emit("artifact.updated", {**doc, "markdownContent": "x", "acceptedBy": [], "acceptedCount": 0, "totalRequired": 2, "versions": []})
    run.p.emit("artifact.updated", {**doc, "status": "in_review", "markdownContent": "x", "acceptedBy": [], "acceptedCount": 0, "totalRequired": 2, "versions": []})
    run.p.emit("artifact.updated", {"id": "art-x", "title": "agile", "filename": "docs/agile/x.md", "status": "approved", "currentVersion": "v1.0", "markdownContent": "y", "acceptedBy": [], "acceptedCount": 0, "totalRequired": 0, "versions": []})
    run.standup.flush()
    state = run.standup.service.state("document-review")
    assert state.reviews["PRD.md"].status.value == "in_review" and state.status == MeetingStatus.REVIEWING and "docs/agile/x.md" not in state.documents
    run.p.emit("artifact.updated", {**doc, "status": "approved", "markdownContent": "x", "acceptedBy": ["SME-01"], "acceptedCount": 2, "totalRequired": 2, "versions": []})
    run.standup.flush()
    assert run.standup.service.state("document-review").reviews["PRD.md"].status.value == "approved"


def test_a_skill_taken_after_joining_is_recorded(run):
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    say(run, "01", "DEV_1", "hello")
    run.narrator.agent("DEV_1", role="Backend Developer", claimedSkill="Backend")
    run.standup.flush()
    assert run.standup.service.state("kickoff").participants["agent-01"].skill == "backend"


def test_the_listing_the_view_the_events_the_transcript_and_the_replay_point(client, run):
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    for i in range(5):
        say(run, "01", f"DEV_{i + 1}", f"point {i}", hint="proposal")
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "completed")
    run.standup.flush()
    listing = client.get(f"{BASE}/meetings").json()
    assert [m["meeting_id"] for m in listing["meetings"]] == ["kickoff"] and listing["meetings"][0]["participants"] == 7 and listing["autopilot"] is False
    full = client.get(f"{BASE}/meetings/kickoff").json()
    assert full["view"]["status"] == "completed" and full["view"]["title"] == "Kickoff meeting: Jarvis" and full["lastSequence"] == len(run.standup.service.events("kickoff"))
    early = client.get(f"{BASE}/meetings/kickoff", params={"at": 6}).json()
    assert early["lastSequence"] == 6 and early["view"]["status"] != "completed"
    page = client.get(f"{BASE}/meetings/kickoff/events", params={"after": 3, "limit": 4}).json()
    assert [e["sequence_number"] for e in page["events"]] == [4, 5, 6, 7] and page["more"] is True and page["lastSequence"] == 7
    text = client.get(f"{BASE}/meetings/kickoff/transcript")
    assert text.headers["content-type"].startswith("text/plain") and "DEV_3 — Proposal:\npoint 2" in text.text
    assert client.get(f"{BASE}/meetings/missing").status_code == 404 and client.get(f"{BASE}/meetings/missing/transcript").status_code == 404
    assert client.get(f"{BASE}/meetings/..%2Fetc").status_code in (400, 404)
    assert client.get(f"{BASE}/meetings", params={"record": "nope"}).status_code == 409
    assert client.get("/workspace/other/standup/meetings").status_code == 404  # a workspace that is not this one


def test_a_new_project_starts_a_new_record_and_the_old_one_can_still_be_replayed(client, run):
    run.narrator.meet("01", "Kickoff meeting: Old", "live")
    say(run, "01", "DEV_1", "from the old project")
    run.standup.flush()
    old = run.standup.tag
    run.reset()
    run.narrator.meet("01", "Kickoff meeting: New", "live")
    run.standup.flush()
    assert run.standup.tag != old
    assert [m["title"] for m in client.get(f"{BASE}/meetings").json()["meetings"]] == ["Kickoff meeting: New"]
    earlier = client.get(f"{BASE}/meetings", params={"record": old}).json()
    assert [m["title"] for m in earlier["meetings"]] == ["Kickoff meeting: Old"] and old in earlier["records"] and run.standup.tag in earlier["records"]
    assert "from the old project" in client.get(f"{BASE}/meetings/kickoff/transcript", params={"record": old}).text


def test_the_record_survives_a_gateway_restart(run):
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    say(run, "01", "DEV_1", "before the restart")
    run.standup.flush()
    before = run.standup.service.state("kickoff").last_sequence
    run.p.listeners.remove(run.standup.on_event)
    reopened = StandupHub(run)  # what a new process does
    try:
        assert reopened.tag == run.standup.tag and reopened.service.state("kickoff").last_sequence == before
        assert reopened.service.replay("kickoff").last_sequence == before
    finally:
        run.p.listeners.remove(reopened.on_event)
        run.p.listeners.append(run.standup.on_event)


def test_events_also_travel_on_the_workspace_stream_in_order(client, run):
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    say(run, "01", "DEV_1", "hello")
    run.standup.flush()
    stream = [e for e in run.p.recent(500) if e["type"] == "standup.event"]
    assert stream and [e["payload"]["sequence_number"] for e in stream] == sorted(e["payload"]["sequence_number"] for e in stream)
    assert all(e["payload"]["workspace_id"] == WORKSPACE and e["payload"]["schema_version"] == 1 for e in stream)
    versions = [e["version"] for e in run.p.recent(500)]
    assert versions == sorted(versions)


def read_frames(client, url, count=None, headers=None):
    """The sequence numbers of the frames, and whether the server ended the stream. Stops after `count` frames, or when the stream ends."""
    got, ended = [], False
    with client.stream("GET", url, headers=headers or {}) as response:
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("id: "):
                got.append(int(line[4:]))
            if line.startswith("event: end"):
                ended = True
                break
            if count is not None and len(got) >= count:
                break
    return got, ended


def wait_until_nobody_is_watching(run):
    for _ in range(100):  # a closed stream is cleaned up a moment after the client leaves
        if not run.standup._subscribers:
            return True
        time.sleep(0.05)
    return False


def test_a_screen_can_resume_the_stream_where_it_stopped_without_duplicates(client, run):
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    for i in range(6):
        say(run, "01", "DEV_1", f"line {i}")
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "completed")
    run.standup.flush()  # the meeting is over, so every stream below ends by itself
    total = run.standup.service.state("kickoff").last_sequence
    assert read_frames(client, f"{BASE}/meetings/kickoff/stream", 4) == ([1, 2, 3, 4], False)
    assert read_frames(client, f"{BASE}/meetings/kickoff/stream", headers={"Last-Event-ID": "4"}) == (list(range(5, total + 1)), True)  # nothing repeated, nothing missed
    assert read_frames(client, f"{BASE}/meetings/kickoff/stream") == (list(range(1, total + 1)), True)
    assert read_frames(client, f"{BASE}/meetings/kickoff/stream?after={total - 1}") == ([total], True)
    assert client.get(f"{BASE}/meetings/missing/stream").status_code == 404
    assert wait_until_nobody_is_watching(run)


def test_a_live_meeting_streams_new_events_to_a_waiting_screen(client, run):
    import threading

    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    say(run, "01", "DEV_1", "already said")
    run.standup.flush()
    start = run.standup.service.state("kickoff").last_sequence

    def later():
        time.sleep(0.4)
        say(run, "01", "DEV_2", "said while you watch")
        run.standup.flush()

    thread = threading.Thread(target=later)
    thread.start()
    got, ended = read_frames(client, f"{BASE}/meetings/kickoff/stream?after={start}", 1)
    thread.join()
    assert got == [start + 1] and ended is False


def test_answering_through_the_meeting_screen_resolves_the_question(client, run):
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    got = []
    qid = run.questions.open("01", "meeting", "Memory only?", "", ["Yes", "No"], "Yes", got.append)
    run.standup.flush()
    assert client.post(f"{BASE}/meetings/kickoff/answer", json={"questionId": qid, "answer": " "}).status_code == 400
    assert client.post(f"{BASE}/meetings/kickoff/answer", json={"questionId": "nope", "answer": "x"}).status_code == 409
    assert client.post(f"{BASE}/meetings/missing/answer", json={"questionId": qid, "answer": "x"}).status_code == 404
    assert client.post(f"{BASE}/meetings/kickoff/answer", json={"questionId": qid, "answer": "Yes"}).json() == {"accepted": True}
    assert got == ["Yes"] and client.post(f"{BASE}/meetings/kickoff/answer", json={"questionId": qid, "answer": "again"}).status_code == 409
    run.standup.flush()
    assert run.standup.service.state("kickoff").questions[qid].answer == "Yes"


def test_the_sme_can_say_something_to_the_team_from_the_meeting_screen(client, run):
    assert client.post(f"{BASE}/meetings/kickoff/direct", json={"text": " "}).status_code == 400
    reply = client.post(f"{BASE}/meetings/kickoff/direct", json={"text": "Please keep it simple."})
    assert reply.status_code == 200 and "accepted" in reply.json()


def test_control_can_be_handed_to_the_autopilot_and_taken_back(client, run):
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    run.standup.flush()
    assert client.post(f"{BASE}/control", json={"mode": "robot"}).status_code == 400
    assert client.post(f"{BASE}/control", json={"mode": "autopilot"}).json() == {"mode": "autopilot", "meetingsTold": 1}
    assert run.standup.service.state("kickoff").meeting.control_mode == ControlMode.AUTOPILOT
    run.narrator.meet("s1-planning", "Sprint 1 planning", "live")
    run.standup.flush()
    assert run.standup.service.state("s1-planning").meeting.control_mode == ControlMode.AUTOPILOT  # a meeting that starts later begins in the same mode
    assert client.get(f"{BASE}/meetings").json()["autopilot"] is True
    assert client.post(f"{BASE}/control", json={"mode": "human"}).json()["meetingsTold"] == 2
    assert run.standup.service.state("kickoff").meeting.control_mode == ControlMode.HUMAN and "human_takeover" in types(run, "kickoff")
    assert client.post(f"{BASE}/control", json={"mode": "human"}).json()["meetingsTold"] == 0  # nothing to change


# ---------------------------------------------------------------------- the autopilot Business SME


def fake_deps(run, reply=None, fail=False):
    class Llm:
        async def generate(self, prompt, schema, *, stage, system=""):
            assert schema is SmeAnswer and "THE BRIEF" in prompt and "Business SME" in system
            if fail:
                raise RuntimeError("model unavailable")
            return reply

    run.deps = SimpleNamespace(meeting_settings=lambda: None, meeting_llm=lambda s: Llm())
    run.settings.autopilot_delay = 0.0
    run.brief = "Add timers to Jarvis."


def ask(run, kind="meeting", options=("Yes", "No"), recommended="No"):
    got = []
    qid = run.questions.open("01", kind, "Do timers survive a restart?", "storage", list(options), recommended, got.append)
    run.standup.flush()
    return qid, got


def test_the_autopilot_answers_a_product_question_and_the_record_says_so(run):
    fake_deps(run, SmeAnswer(answer="no", reasoning="The brief says memory only."))
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    qid, got = ask(run)
    run.standup.autopilot = True
    asyncio.run(autopilot.answer_later(run, qid, "Do timers survive a restart?", "storage", ["Yes", "No"], "No"))
    run.standup.flush()
    assert got == ["No"]  # matched to the option exactly as written
    answered = [e for e in run.standup.service.events("kickoff") if e.event_type == "clarification_answered"][0]
    assert answered.payload["source"] == "autopilot" and run.autopilot_log


def test_the_autopilot_falls_back_to_the_recommended_default_when_the_model_fails(run):
    fake_deps(run, fail=True)
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    qid, got = ask(run)
    run.standup.autopilot = True
    asyncio.run(autopilot.answer_later(run, qid, "q", "c", ["Yes", "No"], "No"))
    assert got == ["No"]


def test_the_autopilot_leaves_a_question_without_a_default_to_the_human_when_it_cannot_answer(run):
    fake_deps(run, fail=True)
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    qid, got = ask(run, options=(), recommended=None)
    run.standup.autopilot = True
    asyncio.run(autopilot.answer_later(run, qid, "q", "c", [], None))
    assert got == [] and qid in run.questions.pending


def test_taking_control_back_stops_the_autopilot_answering(run):
    fake_deps(run, SmeAnswer(answer="Yes"))
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    qid, got = ask(run)
    run.standup.autopilot = True

    async def scenario():
        task = asyncio.ensure_future(autopilot.answer_later(run, qid, "q", "c", ["Yes", "No"], "No"))
        run.standup.autopilot = False  # the human took over before it finished
        await task

    asyncio.run(scenario())
    assert got == [] and qid in run.questions.pending


def test_the_autopilot_never_answers_documents_or_approvals(run):
    fake_deps(run, SmeAnswer(answer="Approve"))
    run.narrator.meet("prd", "Document review", "live")
    run.standup.autopilot = True

    async def scenario():
        for kind in ("documents", "approval"):
            got = []
            run.questions.open("prd", kind, "Accept the documents?", "", ["Approve", "Decline"], "Approve", got.append)
        await asyncio.sleep(0.05)
        return list(run.background)

    assert asyncio.run(scenario()) == []  # nothing was even started for them
    assert len(run.questions.pending) == 2


def test_a_product_question_asked_while_the_autopilot_is_on_is_picked_up(run):
    fake_deps(run, SmeAnswer(answer="Yes"))
    run.narrator.meet("01", "Kickoff meeting: Jarvis", "live")
    run.standup.autopilot = True

    async def scenario():
        got = []
        run.loop = asyncio.get_running_loop()
        run.questions.open("01", "meeting", "Memory only?", "", ["Yes", "No"], "No", got.append)
        for _ in range(100):
            if got:
                break
            await asyncio.sleep(0.02)
        return got

    assert asyncio.run(scenario()) == ["Yes"]


def test_pick_matches_options_loosely_but_returns_them_exactly():
    assert autopilot.pick("  YES ", ["Yes", "No"]) == "Yes"
    assert autopilot.pick("Only in memory, for now", ["Yes", "No"]) == "Only in memory, for now"
    assert autopilot.pick("anything", []) == "anything"
