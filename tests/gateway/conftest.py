"""A gateway wired to scripted models: the meeting is answered by the meeting fakes, the team by the scripted team model, nothing touches the network."""

import time

import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.config import GatewaySettings
from gateway.runner import Deps
from meetings.config import Settings
from tests.meetings.fakes import FakeLLM
from tests.team.test_agile_flow import agile_llm

WORKSPACE = "workspace-demo"


def make_settings(tmp_path, **overrides):
    values = dict(output_dir=tmp_path / "output", data_dir=tmp_path / "data", a2a=False, memory=False, repair_rounds=0, workspace_id=WORKSPACE)
    values.update(overrides)
    return GatewaySettings(**values)


def make_deps(timeline=None):
    team = agile_llm(timeline if timeline is not None else [])
    team.on(r"verification commands fail", [("text", "nothing to fix")])
    return Deps(meeting_settings=lambda: Settings(api_key="k", model="fake"), meeting_llm=lambda settings: FakeLLM(), team_llm=team)


@pytest.fixture
def client(tmp_path):
    deps = make_deps()
    with TestClient(create_app(make_settings(tmp_path), deps)) as c:
        c.deps, c.team_llm, c.tmp = deps, deps.team_llm, tmp_path
        yield c


def snapshot(client):
    return client.get(f"/workspace/{WORKSPACE}/snapshot").json()


def command(client, **body):
    return client.post(f"/workspace/{WORKSPACE}/commands", json={"workspaceId": WORKSPACE, **body})


def wait_for(client, predicate, timeout=240.0, what="the condition"):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = snapshot(client)
        if predicate(last):
            return last
        time.sleep(0.25)
    raise AssertionError(f"timed out waiting for {what}; phase={last['phaseId'] if last else None}, last messages={[m['text'][:60] for m in (last or {}).get('messages', [])[-4:]]}")


def open_questions(snap):
    """Cards in the transcript that have no answer yet."""
    answered = {m.get("answersQuestion") for m in snap["messages"]}
    return [m for m in snap["messages"] if m.get("kind") == "question" and m["question"]["id"] not in answered]


def answer_everything_but_the_documents(client, snap):
    """Plays the person for the questions that are not the documents: product questions get the recommended option, other decisions are approved."""
    for card in open_questions(snap):
        q = card["question"]
        if q["kind"] == "documents":
            continue
        text = q.get("recommended") or "Approve"
        assert command(client, type="sme.directive.submit", meetId=card["meetId"], directive=text, questionId=q["id"]).json()["accepted"] is True


def drive(client, until, timeout=300.0, what="the run to get there"):
    """Keeps answering questions (never the documents) until `until(snapshot)` holds."""
    deadline = time.time() + timeout
    snap = snapshot(client)
    while time.time() < deadline:
        snap = snapshot(client)
        if until(snap):
            return snap
        answer_everything_but_the_documents(client, snap)
        time.sleep(0.25)
    raise AssertionError(f"timed out waiting for {what}; phase={snap['phaseId']}; last: {[m['text'][:70] for m in snap['messages'][-5:]]}")
