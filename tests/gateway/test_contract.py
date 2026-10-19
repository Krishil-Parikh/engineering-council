"""The frontend contract, checked from the outside: shapes, errors, auth, limits, and the rules of the projection behind them."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.models import COMMAND_TYPES, EVENT_TYPES, PHASES, Snapshot, validate_command
from gateway.projection import Projection
from tests.gateway.conftest import WORKSPACE, command, make_deps, make_settings, snapshot


def test_a_fresh_workspace_is_a_valid_non_empty_snapshot(client):
    snap = snapshot(client)
    Snapshot.model_validate(snap)  # every field the browser requires is present and typed
    assert snap["workspaceId"] == WORKSPACE and snap["phaseId"] == "kickoff" and snap["version"] > 0
    ids = {a["id"] for a in snap["agents"]}
    assert {"agent-sm", "sme-01"} <= ids  # never empty: the browser hides its views for an empty workspace
    for key in ("agents", "messages", "skills", "artifacts", "meets", "sprints", "edges", "processedEventIds"):
        assert isinstance(snap[key], list), key
    assert set(snap["metrics"]) >= {"totalMessagesToday", "totalPRs", "prHistory"}


def test_the_browser_rules_for_a_snapshot_are_met(client):
    """The checks in frontend/.../adapters/validateWorkspaceSnapshot.ts, written out."""
    snap = snapshot(client)
    assert isinstance(snap["workspaceId"], str) and isinstance(snap["version"], int) and isinstance(snap["phaseId"], str)
    assert all(isinstance(snap[k], list) for k in ("agents", "messages", "artifacts", "meets", "processedEventIds")) and isinstance(snap["metrics"], dict)
    assert snap["phaseId"] in PHASES


def test_unknown_workspaces_are_404_and_the_error_is_machine_readable(client):
    response = client.get("/workspace/nope/snapshot")
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"
    assert client.post("/workspace/nope/commands", json={"type": "prd.accept", "workspaceId": "nope", "artifactId": "x"}).status_code == 404
    assert client.get("/workspace/nope/events").status_code == 404


@pytest.mark.parametrize("body, message", [
    ({"type": "sprint.start", "brief": "   "}, "brief is required"),
    ({"type": "phase.advance", "phaseId": ""}, "phaseId is required"),
    ({"type": "agent.task.reassign", "agentId": "", "task": "x"}, "agentId is required"),
    ({"type": "agent.task.reassign", "agentId": "a", "task": " "}, "task is required"),
    ({"type": "message.create", "message": {"meetId": "m", "senderId": "s", "text": " "}}, "message.text is required"),
    ({"type": "message.create", "message": {"text": "x", "senderId": "s"}}, "message.meetId is required"),
    ({"type": "message.create", "message": {"text": "x", "meetId": "m"}}, "message.senderId is required"),
    ({"type": "sme.directive.submit", "meetId": "", "directive": "x"}, "meetId is required"),
    ({"type": "sme.directive.submit", "meetId": "m", "directive": ""}, "directive is required"),
    ({"type": "prd.accept", "artifactId": ""}, "artifactId is required"),
    ({"type": "debate.inject", "meetId": "m", "text": ""}, "text is required"),
    ({"type": "consensus.force", "meetId": ""}, "meetId is required"),
    ({"type": "no.such.command"}, "Unknown command type"),
])
def test_invalid_commands_are_400_with_the_browsers_own_messages(client, body, message):
    response = command(client, **body)
    assert response.status_code == 400 and message in response.json()["error"]["message"]
    assert validate_command({"workspaceId": WORKSPACE, **body}) is not None


def test_every_command_and_event_type_in_the_contract_is_known():
    assert len(COMMAND_TYPES) == 8 and len(EVENT_TYPES) == 9 and PHASES == ("kickoff", "brainstorm", "prd", "build", "review", "ship")


def test_a_workspace_id_that_does_not_match_the_url_is_refused(client):
    response = client.post(f"/workspace/{WORKSPACE}/commands", json={"type": "prd.accept", "workspaceId": "other", "artifactId": "x"})
    assert response.status_code == 400


def test_commands_that_do_not_fit_reality_are_declined_not_faked(client):
    assert command(client, type="prd.accept", artifactId="art-prd").json()["accepted"] is False  # nothing is waiting for approval
    assert command(client, type="consensus.force", meetId="meet-01").json()["accepted"] is False
    assert command(client, type="agent.task.reassign", agentId="agent-03", task="do it").json()["accepted"] is False  # no team yet
    spoken = command(client, type="message.create", message={"meetId": "meet-01", "senderId": "agent-03", "senderName": "A", "text": "hi", "timestamp": "00:00:00"}).json()
    assert spoken["accepted"] is False and "Only you" in spoken["note"]  # the demo button cannot make agents speak
    assert command(client, type="sme.directive.submit", meetId="meet-01", directive="use sqlite").json()["accepted"] is False  # no team to tell yet


def test_the_phase_cannot_be_pushed_ahead_of_reality(client):
    assert command(client, type="phase.advance", phaseId="kickoff").json()["accepted"] is True  # already there: fine
    for phase in ("build", "review", "ship", "prd"):
        response = command(client, type="phase.advance", phaseId=phase)
        assert response.status_code == 409, phase
    assert snapshot(client)["phaseId"] == "kickoff"


def test_commands_are_rate_limited(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, rate_per_minute=3), make_deps())) as c:
        codes = [command(c, type="prd.accept", artifactId="a").status_code for _ in range(5)]
        assert codes == [200, 200, 200, 429, 429]


def test_a_token_is_required_when_one_is_set(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, token="s3cret"), make_deps())) as c:
        assert c.get(f"/workspace/{WORKSPACE}/snapshot").status_code == 401
        assert c.get(f"/workspace/{WORKSPACE}/snapshot", headers={"Authorization": "Bearer wrong"}).status_code == 403
        assert c.get(f"/workspace/{WORKSPACE}/snapshot", headers={"Authorization": "Bearer s3cret"}).status_code == 200
        assert c.get(f"/workspace/{WORKSPACE}/snapshot?token=s3cret").status_code == 200  # the event stream cannot send headers, so the query form exists
        assert c.get("/health").status_code == 200


def test_cross_origin_requests_from_the_dev_server_are_allowed(client):
    response = client.get(f"/workspace/{WORKSPACE}/snapshot", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    preflight = client.options(
        f"/workspace/{WORKSPACE}/commands",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"},
    )
    assert preflight.status_code == 200


# ---------------------------------------------------------------------------------------------- the projection


def test_events_get_rising_versions_and_unique_ids_and_rebuild_the_same_state_after_a_restart(tmp_path):
    log = tmp_path / "events.jsonl"
    p = Projection("w", log)
    p.emit("agent.updated", {"id": "agent-01", "name": "DEV_1", "role": "Backend Developer", "status": "idle"})
    p.emit("agent.updated", {"id": "agent-01", "status": "active", "activeTask": "work"})
    p.emit("message.created", {"id": "m1", "meetId": "meet-01", "senderId": "agent-01", "senderName": "DEV_1", "text": "hi", "timestamp": "00:00:00"})
    p.emit("message.created", {"id": "m1", "meetId": "meet-01", "senderId": "agent-01", "senderName": "DEV_1", "text": "duplicate id", "timestamp": "00:00:01"})
    p.emit("phase.changed", {"phaseId": "build"})
    versions = [e["version"] for e in p.recent()]
    assert versions == sorted(set(versions)) and len({e["eventId"] for e in p.recent()}) == len(versions)
    agent = p.snapshot()["agents"][0]
    assert agent["name"] == "DEV_1" and agent["status"] == "active" and agent["activeTask"] == "work"  # merged field by field, like the browser's reducer
    assert len(p.snapshot()["messages"]) == 1  # a repeated message id is ignored
    again = Projection("w", log)  # a new process reads the log
    assert again.snapshot()["agents"] == p.snapshot()["agents"] and again.version == p.version and again.phase == "build"


def test_a_bad_event_is_refused_before_it_can_reach_a_browser():
    p = Projection("w")
    with pytest.raises(ValueError):
        p.emit("agent.exploded", {})
    with pytest.raises(ValueError):
        p.emit("phase.changed", {"phaseId": "sideways"})


def test_subscribers_hear_events_as_they_happen_and_slow_ones_are_dropped():
    async def main():
        p = Projection("w")
        fast = p.subscribe()
        p.emit("phase.changed", {"phaseId": "build"})
        assert (await fast.get())["payload"] == {"phaseId": "build"}
        slow = asyncio.Queue(maxsize=1)
        p._subscribers.add(slow)
        p.emit("phase.changed", {"phaseId": "review"})
        p.emit("phase.changed", {"phaseId": "ship"})
        assert slow not in p._subscribers and fast in p._subscribers

    asyncio.run(main())


def test_the_snapshot_keeps_only_the_most_recent_messages_but_the_log_keeps_all(tmp_path):
    p = Projection("w", tmp_path / "e.jsonl", max_messages=5)
    for i in range(12):
        p.emit("message.created", {"id": f"m{i}", "meetId": "x", "senderId": "a", "senderName": "A", "text": str(i), "timestamp": "0"})
    assert [m["id"] for m in p.snapshot()["messages"]] == [f"m{i}" for i in range(7, 12)]
    assert len((tmp_path / "e.jsonl").read_text().splitlines()) == 12


def test_the_snapshot_lists_recent_event_ids_so_a_replay_is_ignored_by_the_browser():
    p = Projection("w")
    for _ in range(3):
        p.emit("phase.changed", {"phaseId": "build"})
    snap = p.snapshot()
    assert snap["processedEventIds"] == [e["eventId"] for e in p.recent()] and snap["version"] == p.version
