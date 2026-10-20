"""Builds the demo meetings the frontend shows when there is no backend, by running them through the real Standup service with a fixed clock.

The frontend never re-implements the meeting rules: what it shows in demo mode is exactly what the backend computed. A test fails when the committed files differ from what
this script makes, so the fixtures cannot drift from the code:

    python -m tests.standup.make_fixtures          # rewrite the files
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from standup.adapters.memory_store import MemoryEventStore
from standup.adapters.system import FixedClock, SequentialIds
from standup.presentation import build_view, translate
from standup.service import MeetingService
from standup.transcript import render_transcript

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "frontend" / "agentic-scrum-control-plane" / "src" / "views" / "standup" / "fixtures"
START = datetime(2026, 3, 2, 9, 30, 0, tzinfo=timezone.utc)
WORKSPACE = "workspace-demo"


def service() -> tuple[MeetingService, FixedClock]:
    clock = FixedClock(START)
    return MeetingService(WORKSPACE, MemoryEventStore(), clock=clock, ids=SequentialIds()), clock


def join(svc: MeetingService, mid: str, pid: str, name: str, kind: str, **extra: str) -> None:
    svc.publish(mid, "participant_joined", {"participant_id": pid, "display_name": name, "participant_type": kind, **extra}, actor_id="system")


def discovery() -> tuple[MeetingService, str]:
    svc, clock = service()
    mid = svc.create_meeting("Discovery: Jarvis timers and reminders", "discovery", meeting_id="discovery", duration_limit_seconds=3600, created_by="scrum-master")
    join(svc, mid, "sme", "Business SME", "business_sme")
    join(svc, mid, "sm", "Scrum Master", "scrum_master")
    for i in range(1, 7):
        join(svc, mid, f"dev-{i}", f"Developer {i:02d}", "developer")  # six generic developers: no skill yet
    svc.publish(mid, "meeting_started", actor_id="system")

    def at(seconds: float) -> None:
        clock.advance(seconds)

    svc.publish(mid, "topic_started", {"topic": "What are we building, and for whom?"}, actor_id="sm")
    at(8)
    svc.publish(mid, "statement", {"text": "Jarvis is a voice assistant. Timers and reminders must fit its router, its session loop and its plugin rules."}, actor_id="dev-1")
    at(11)
    svc.publish(mid, "brainstorm", {"text": "Keep timers in a small plugin driven by a heartbeat, so the core never learns about timers."}, actor_id="dev-2")
    at(14)
    svc.publish(mid, "proposal", {"text": "One timer plugin, one Tick event, one fake clock for tests."}, actor_id="dev-3")
    at(9)
    svc.publish(mid, "challenge", {"text": "A heartbeat per second drifts. Compare against the clock, never count ticks."}, actor_id="dev-4", target_id="dev-3")
    at(16)
    svc.publish(mid, "counterargument", {"text": "Agreed: the plugin stores deadlines and checks them on each tick."}, actor_id="dev-3")
    at(12)
    svc.publish(mid, "risk_raised", {"risk_id": "risk-1", "text": "An alert could talk over the user.", "severity": "high"}, actor_id="dev-5")
    svc.publish(mid, "dependency_identified", {"dependency_id": "dep-1", "text": "The alert needs the session's speaking state.", "from": "dev-3", "to": "dev-6"}, actor_id="dev-5")
    at(10)
    svc.publish(mid, "facilitator_intervention", {"text": "Let us settle the alert rule before we split the work."}, actor_id="sm")
    at(6)
    svc.publish(mid, "clarification_requested", {"question_id": "q-1", "text": "Should timers survive a restart?", "options": ["Yes, persist them", "No, memory only"], "recommended": "No, memory only"}, actor_id="dev-2")
    at(40)
    svc.publish(mid, "clarification_answered", {"question_id": "q-1", "answer": "No, memory only", "source": "human"}, actor_id="sme")
    at(7)
    svc.publish(mid, "decision_proposed", {"decision_id": "dec-1", "title": "Alerts wait while Jarvis speaks or listens", "alternatives": ["wait", "interrupt"]}, actor_id="dev-6")
    at(5)
    svc.publish(mid, "decision_accepted", {"decision_id": "dec-1", "selected_option": "wait"}, actor_id="sme")
    svc.publish(mid, "action_item_created", {"action_item_id": "act-1", "owner_id": "dev-3", "description": "Write the timer plugin against the clock port", "due_reference": "sprint 1"}, actor_id="sm")
    svc.publish(mid, "action_item_created", {"action_item_id": "act-2", "owner_id": "dev-6", "description": "Expose the speaking state to the plugin", "due_reference": "sprint 1"}, actor_id="sm")
    svc.publish(mid, "action_item_updated", {"action_item_id": "act-2", "status": "in_progress"}, actor_id="dev-6")
    at(20)
    svc.publish(mid, "document_created", {"path": "PRD.md"}, actor_id="sm")
    svc.publish(mid, "document_review_started", {"path": "PRD.md", "reviewer_id": "sme"}, actor_id="sm")
    at(25)
    svc.publish(mid, "document_changes_requested", {"path": "PRD.md", "comments": ["List the refusals: zero, negative, over 24 hours."]}, actor_id="sme")
    svc.publish(mid, "document_review_started", {"path": "PRD.md", "reviewer_id": "sme"}, actor_id="sm")
    at(18)
    svc.publish(mid, "sme_approval_requested", {"request_id": "req-1", "subject": "Accept the PRD", "kind": "documents"}, actor_id="sm")
    at(12)
    svc.publish(mid, "sme_approved", {"request_id": "req-1", "comment": "Approve"}, actor_id="sme")
    svc.publish(mid, "document_approved", {"path": "PRD.md"}, actor_id="sme")
    svc.publish(mid, "topic_completed", {"topic": "What are we building, and for whom?"}, actor_id="sm")
    at(6)
    svc.publish(mid, "summary_generated", {"text": "Timers live in a plugin driven by Tick events and an injected clock. Alerts wait for speech. Memory only. PRD approved."}, actor_id="sm")
    svc.publish(mid, "meeting_ended", actor_id="system")
    return svc, mid


def planning() -> tuple[MeetingService, str]:
    svc, clock = service()
    clock.advance(4000)
    mid = svc.create_meeting("Sprint 1 planning", "sprint_planning", meeting_id="s1-planning", control_mode="human", duration_limit_seconds=1800, sprint_id="sprint-1", created_by="scrum-master")
    join(svc, mid, "sme", "Business SME", "business_sme")
    join(svc, mid, "sm", "Scrum Master", "scrum_master")
    for i in range(1, 9):  # eight developers: nothing in the screen assumes six
        join(svc, mid, f"dev-{i}", f"Developer {i:02d}", "developer")
    svc.publish(mid, "meeting_started", actor_id="system")
    for dev, skill in (("dev-1", "backend"), ("dev-2", "backend"), ("dev-3", "database"), ("dev-4", "devops"), ("dev-5", "backend"), ("dev-6", "frontend")):
        svc.publish(mid, "skill_selected", {"participant_id": dev, "skill": skill}, actor_id="system")  # two or three developers may take the same skill
    svc.publish(mid, "role_assigned", {"participant_id": "dev-2", "role": "adversarial reviewer"}, actor_id="sm")
    svc.publish(mid, "role_assigned", {"participant_id": "dev-5", "role": "alternative designer"}, actor_id="sm")
    svc.publish(mid, "topic_started", {"topic": "Pick the work for sprint 1"}, actor_id="sm")
    clock.advance(15)
    svc.publish(mid, "statement", {"text": "Contracts and events first: everything else needs the clock port and the tick."}, actor_id="dev-1")
    clock.advance(9)
    svc.publish(mid, "challenge", {"text": "That serialises the whole team behind one task. Can the router work against a stub?"}, actor_id="dev-2", target_id="dev-1")
    clock.advance(12)
    svc.publish(mid, "proposal", {"text": "Freeze the interfaces today; build the plugin and the router in parallel against fakes."}, actor_id="dev-5")
    clock.advance(10)
    svc.publish(mid, "participant_blocked", {"participant_id": "dev-3", "reason": "needs the persistence decision"}, actor_id="dev-3")
    svc.publish(mid, "clarification_requested", {"question_id": "q-2", "text": "Is a limit of 10 timers right?", "options": ["10", "20", "unlimited"], "recommended": "10"}, actor_id="dev-3")
    waiting_at = svc.state(mid).last_sequence  # the demo stops here until the Business SME answers; what follows is what happens next
    clock.advance(30)
    svc.publish(mid, "clarification_answered", {"question_id": "q-2", "answer": "10", "source": "human"}, actor_id="sme")
    svc.publish(mid, "participant_unblocked", {"participant_id": "dev-3"}, actor_id="system")
    clock.advance(8)
    svc.publish(mid, "decision_proposed", {"decision_id": "dec-2", "title": "Sprint 1: contracts, router and timer plugin in parallel", "alternatives": ["parallel", "sequential"]}, actor_id="dev-5")
    clock.advance(6)
    svc.publish(mid, "decision_accepted", {"decision_id": "dec-2", "selected_option": "parallel"}, actor_id="sm")
    svc.publish(mid, "action_item_created", {"action_item_id": "act-3", "owner_id": "dev-1", "description": "Freeze the Clock, Tick and announce interfaces today"}, actor_id="sm")
    clock.advance(5)
    svc.publish(mid, "meeting_ended", actor_id="system")
    svc.waiting_at = waiting_at  # type: ignore[attr-defined]
    return svc, mid


def build(svc: MeetingService, mid: str) -> dict:
    events = svc.events(mid)
    final = svc.state(mid)
    views = {}
    for event in events:
        state = svc.state_at(mid, event.sequence_number)
        view = build_view(state, state.last_timestamp or START).model_dump(mode="json")
        view["recent"] = []  # rebuilt from `timeline` by whoever serves it: the same timeline would otherwise be stored 70 times
        views[str(event.sequence_number)] = view
    timeline = []
    for event in events:
        timeline.append(translate(event, svc.state_at(mid, event.sequence_number)).model_dump(mode="json"))
    meeting = final.meeting.model_dump(mode="json")
    row = {**meeting, "open_questions": len(final.open_questions()), "decisions": len(final.decisions), "action_items": len(final.actions),
           "participants": len([p for p in final.participants.values() if p.status.value != "left"]), "last_sequence": final.last_sequence}
    return {"meeting": row, "events": [e.wire() for e in events], "views": views, "timeline": timeline, "transcript": render_transcript(events), "waiting_at": getattr(svc, "waiting_at", None)}


def all_fixtures() -> dict[str, dict]:
    return {"discovery.json": build(*discovery()), "planning.json": build(*planning())}


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, data in all_fixtures().items():
        (TARGET / name).write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {TARGET / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
