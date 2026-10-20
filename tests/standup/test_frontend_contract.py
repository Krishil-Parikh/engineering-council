"""The browser's types and the backend's models are written separately. These tests read the TypeScript source and fail the moment the two disagree, so a changed event, status or field
cannot reach the screen as a blank panel."""

import json
import re
from pathlib import Path

import pytest

from gateway.standup_routes import OVER
from standup.enums import ActionStatus, ControlMode, DecisionStatus, MeetingStatus, ParticipantStatus, ReviewStatus
from standup.events import KNOWN_TYPES, SCHEMA_VERSION, MeetingEvent
from standup.models import ActionItem, ApprovalRequest, Decision, Dependency, DocumentReview, Question, Risk
from standup.presentation import ParticipantView, PresentationEvent, StandupViewState
from tests.standup.make_fixtures import TARGET, all_fixtures

SRC = TARGET.parent
MODELS = SRC / "models"


def ts(name: str) -> str:
    return (MODELS / name).read_text(encoding="utf-8")


def quoted_list(source: str, const: str) -> list[str]:
    block = re.search(rf"export const {const}\b[^=]*=\s*\[(.*?)\]", source, re.S)
    assert block, f"{const} not found"
    return re.findall(r"'([a-z_]+)'", block.group(1))


def union(source: str, name: str) -> set[str]:
    block = re.search(rf"export type {name} =\s*(.*?);", source, re.S)
    assert block, f"{name} not found"
    return set(re.findall(r"'([a-z_]+)'", block.group(1)))


def interface_fields(source: str, name: str) -> set[str]:
    """The top-level field names of `export interface Name { ... }` (nested object types are skipped by counting braces)."""
    source = re.sub(r"/[*].*?[*]/", "", source, flags=re.S)  # comments are not fields
    start = re.search(r"export interface " + re.escape(name) + r"\s*{", source)
    assert start, f"{name} not found"
    depth, i, body = 1, start.end(), []
    while depth:
        ch = source[i]
        depth += ch == "{"
        depth -= ch == "}"
        if depth:
            body.append(ch if depth == 1 else " ")
        i += 1
    return set(re.findall(r"(?:^|[;{,]|\s)(\w+)\??\s*:", "".join(body)))


@pytest.mark.parametrize("ts_name,model", [
    ("StandupView", StandupViewState), ("StandupParticipant", ParticipantView), ("StandupTimelineEntry", PresentationEvent), ("StandupQuestion", Question), ("StandupDecision", Decision),
    ("StandupActionItem", ActionItem), ("StandupDocumentReview", DocumentReview), ("StandupApproval", ApprovalRequest), ("StandupRisk", Risk), ("StandupDependency", Dependency),
])
def test_every_field_the_screen_reads_is_one_the_backend_sends_and_the_other_way_round(ts_name, model):
    fields, sent = interface_fields(ts("standup.ts"), ts_name), set(model.model_fields)
    assert fields - sent == set(), f"{ts_name} reads fields the backend does not send: {fields - sent}"
    assert sent - fields == set(), f"{ts_name} lacks fields the backend sends (add them to the type): {sent - fields}"


def test_the_event_envelope_agrees():
    assert interface_fields(ts("meeting-events.ts"), "MeetingEventWire") == set(MeetingEvent.model_fields)


def test_the_status_values_in_the_panels_exist():
    source = ts("standup.ts")
    assert union(source.replace("export interface StandupDecision", "export type DecisionStatusX =\n  | 'proposed' | 'accepted' | 'rejected' | 'deferred';\nexport interface StandupDecision"), "DecisionStatusX") == {s.value for s in DecisionStatus}
    assert {"open", "in_progress", "done", "dropped"} == {s.value for s in ActionStatus}
    assert {"in_review", "approved", "changes_requested"} == {s.value for s in ReviewStatus}
    for word in ("'in_progress' | 'done' | 'dropped'", "'in_review' | 'approved' | 'changes_requested'", "'proposed' | 'accepted' | 'rejected' | 'deferred'"):
        assert word in source


def test_the_demo_meetings_are_what_the_backend_makes_today():
    """If this fails, the rules of a meeting changed: run `python -m tests.standup.make_fixtures` and look at the diff, then run the frontend tests."""
    for name, fresh in all_fixtures().items():
        on_disk = json.loads((TARGET / name).read_text(encoding="utf-8"))
        assert on_disk == json.loads(json.dumps(fresh, sort_keys=True)), f"{name} is out of date"
