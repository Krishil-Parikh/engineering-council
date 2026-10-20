"""A whole run through the gateway, using only the three endpoints the frontend uses: a brief goes in, product questions are answered, the documents are
read and accepted, the sprints run, and the finished work is on a final branch. Scripted models, real git, real engine."""

import json
import time

from tests.gateway.conftest import WORKSPACE, command, drive, open_questions, snapshot, wait_for

BRIEF = "# Project: Todo CLI\n\nA small command line task list with add, list and done commands, stored in a JSON file."
PHASE_ORDER = ["kickoff", "brainstorm", "prd", "build", "review", "ship"]


def stream_events(client, count):
    """Reads `count` frames from the event stream, the way the browser's EventSource does."""
    events = []
    with client.stream("GET", f"/workspace/{WORKSPACE}/events") as response:
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
                if len(events) >= count:
                    break
    return events


def test_a_brief_becomes_documents_you_accept_and_then_a_built_project(client):
    started = command(client, type="sprint.start", brief=BRIEF)
    assert started.status_code == 200 and started.json()["accepted"] is True
    assert command(client, type="sprint.start", brief=BRIEF).status_code == 409  # one run at a time in a workspace

    # the meeting runs, asks its product question(s) as cards, and ends with the documents waiting for you
    snap = drive(client, lambda s: s["phaseId"] == "prd" and any(q["question"]["kind"] == "documents" for q in open_questions(s)), what="the documents to be ready")
    assert snap["phaseId"] == "prd"
    cards = [m for m in snap["messages"] if m.get("kind") == "question"]
    assert any(m["question"]["kind"] == "meeting" and m["question"]["options"] for m in cards)  # the meeting's own question was asked, with options
    assert any(m.get("kind") == "answer" for m in snap["messages"])  # and your answer is in the transcript
    docs = {a["filename"]: a for a in snap["artifacts"] if a["id"] in ("art-prd", "art-tech", "art-design")}
    assert set(docs) == {"PRD.md", "Technical_Approach.md", "Design.md"}
    assert all(a["status"] == "in_review" and a["markdownContent"] and a["acceptedCount"] < a["totalRequired"] for a in docs.values())
    assert {a["id"] for a in snap["agents"] if a["id"].startswith("agent-0")} == {f"agent-0{i}" for i in range(1, 7)}  # the roster the meeting chose
    assert snap["meets"] and snap["skills"]

    # nothing is built until you say so
    time.sleep(1.0)
    assert not any("Task:" in str(r.messages) for r in client.team_llm.requests), "coding started before the documents were accepted"
    assert snapshot(client)["phaseId"] == "prd"
    assert command(client, type="phase.advance", phaseId="build").status_code == 409  # the browser cannot skip your approval

    # you accept
    accepted = command(client, type="prd.accept", artifactId="art-prd")
    assert accepted.json()["accepted"] is True
    snap = wait_for(client, lambda s: s["phaseId"] == "build", what="the build phase", timeout=60)
    assert all(a["status"] == "approved" and "SME-01" in a["acceptedBy"] for a in snap["artifacts"] if a["id"] in ("art-prd", "art-tech", "art-design"))

    # the sprints run; more questions (a document change, a design vote) appear as cards and are answered
    snap = drive(client, lambda s: s["phaseId"] == "ship", what="the run to finish", timeout=420)

    # what the browser ends up showing
    assert snap["phaseId"] == "ship"
    assert [s["status"] for s in snap["sprints"]] == ["completed", "completed"] and all(s["progress"] == 100 for s in snap["sprints"])
    assert snap["metrics"]["totalPRs"] == 3 and snap["metrics"]["prHistory"]
    names = {a["filename"] for a in snap["artifacts"]}
    assert "team_report.md" in names and any(n.endswith("sprint_report.md") for n in names) and any("standup" in n for n in names)  # the agile documents are visible
    standups = [m for m in snap["meets"] if "standup" in m["title"].lower()]
    assert standups and all(m["status"] == "completed" for m in standups)
    assert any(e["isActive"] is False for e in snap["edges"]) and any(e["source"] == "agent-sm" for e in snap["edges"])
    developers = [a for a in snap["agents"] if a["id"].startswith("agent-0")]
    assert developers and all(a["status"] in ("idle", "complete") for a in developers)  # nobody is left "working" when it is over
    texts = " ".join(m["text"] for m in snap["messages"])
    assert "final/" in texts and "nothing was merged into main" in texts.lower()
    assert "Nothing was pushed to GitHub" in texts  # no repository was given: the page says where the branches are instead of claiming a push

    # what the team learned is there to look at: the project's memory, each agent's own, and a search that says why it found what it found
    memory = client.get(f"/workspace/{WORKSPACE}/memory").json()
    assert memory["available"] is True and memory["nodes"] and memory["edges"] and memory["scope"] == "project"
    kinds = {n["kind"] for n in memory["nodes"]}
    assert {"task", "feature", "agent"} <= kinds
    assert "DEV_1" in memory["agents"] and memory["overview"]["project"]["nodes"] == memory["stats"]["nodes"]
    own = client.get(f"/workspace/{WORKSPACE}/memory", params={"scope": "DEV_1"}).json()
    assert own["scope"] == "DEV_1" and own["nodes"] and all(n["owner"] in (None, "DEV_1") for n in own["nodes"] if n["kind"] != "agent")
    found = client.get(f"/workspace/{WORKSPACE}/memory/search", params={"q": "storage task"}).json()
    assert found["hits"] and {"score", "signals", "kind", "name"} <= set(found["hits"][0]) and "bm25" in found["hits"][0]["signals"]
    assert client.get(f"/workspace/{WORKSPACE}/memory/search", params={"q": " "}).json()["hits"] == []

    # the stream is consistent with the snapshot
    events = stream_events(client, 40)
    versions = [e["version"] for e in events]
    assert versions == sorted(versions) and len({e["eventId"] for e in events}) == len(events)
    assert all(e["workspaceId"] == WORKSPACE and e["type"] in {"agent.updated", "message.created", "phase.changed", "artifact.updated", "meet.updated", "metrics.updated", "skill.updated", "sprint.updated", "edge.updated", "standup.event"} for e in events)
    assert events[-1]["version"] <= snap["version"]

    # the formal meetings were recorded as a structured, replayable stream, and the chatter was not
    base = f"/workspace/{WORKSPACE}/standup"
    listing = client.get(f"{base}/meetings").json()
    by_id = {m["meeting_id"]: m for m in listing["meetings"]}
    assert by_id["kickoff"]["status"] == "completed" and by_id["kickoff"]["meeting_type"] == "discovery"
    assert any(m["meeting_type"] == "daily_standup" for m in by_id.values()) and any(m["meeting_type"] == "sprint_planning" for m in by_id.values())
    assert not {"merge", "team", "briefings"} & set(by_id)  # merge talk and team chatter are not Scrum meetings
    kick = client.get(f"{base}/meetings/kickoff").json()
    assert kick["view"]["participants"] and any(p["skill"] for p in kick["view"]["participants"] if p["participant_type"] == "developer")
    text = client.get(f"{base}/meetings/kickoff/transcript").text
    assert "Meeting created: Kickoff meeting" in text and "Answer:" in text and text.rstrip().endswith("Meeting ended")
    wire = client.get(f"{base}/meetings/kickoff/events").json()
    assert [e["sequence_number"] for e in wire["events"]] == list(range(1, len(wire["events"]) + 1))
    review = client.get(f"{base}/meetings/document-review").json()["view"]
    assert {r["document_path"] for r in review["reviews"]} == {"PRD.md", "Technical_Approach.md", "Design.md"} and all(r["status"] == "approved" for r in review["reviews"])
    assert client.get(f"{base}/meetings/nope").status_code == 404
    assert (client.app.state.hub.get(WORKSPACE).standup.dropped) == 0


def test_the_phases_only_ever_moved_forward_in_order(client):
    command(client, type="sprint.start", brief=BRIEF)
    drive(client, lambda s: s["phaseId"] == "prd" and any(q["question"]["kind"] == "documents" for q in open_questions(s)), what="the documents")
    command(client, type="prd.accept", artifactId="art-prd")
    drive(client, lambda s: s["phaseId"] == "ship", what="the end", timeout=420)
    run = client.app.state.hub.get(WORKSPACE)
    assert run.phase_log == ["brainstorm", "prd", "build", "review", "ship"]
    assert [PHASE_ORDER.index(p) for p in run.phase_log] == sorted(PHASE_ORDER.index(p) for p in run.phase_log)


def test_a_page_reload_midway_shows_the_same_workspace_and_a_new_stream_replays_what_it_missed(client):
    command(client, type="sprint.start", brief=BRIEF)
    drive(client, lambda s: s["phaseId"] == "prd" and any(q["question"]["kind"] == "documents" for q in open_questions(s)), what="the documents")
    first = snapshot(client)
    second = snapshot(client)
    assert first["version"] == second["version"] and first["messages"] == second["messages"]
    events = stream_events(client, 30)  # a fresh subscriber is given the recent past
    assert events and all(e["version"] <= first["version"] for e in events)
    # applying that replay on top of the snapshot changes nothing: the browser drops events it has already processed
    assert {e["eventId"] for e in events} <= set(first["processedEventIds"])
    client.app.state.hub.get(WORKSPACE).questions.answer("Decline: too vague", kind="documents")  # leave the run waiting; the fixture shuts it down


def test_declining_the_documents_asks_for_changes_and_comes_back_for_a_second_look(client):
    client.team_llm.on(r"asked for changes", [("tool", "write", {"path": "docs/PRD.md", "content": "# PRD\nrevised after feedback\n"}), ("text", "docs/PRD.md")])
    command(client, type="sprint.start", brief=BRIEF)
    snap = drive(client, lambda s: s["phaseId"] == "prd" and any(q["question"]["kind"] == "documents" for q in open_questions(s)), what="the documents")
    card = next(q for q in open_questions(snap) if q["question"]["kind"] == "documents")
    declined = command(client, type="sme.directive.submit", meetId=card["meetId"], directive="Decline: add offline support", questionId=card["question"]["id"])
    assert declined.json()["accepted"] is True
    snap = wait_for(client, lambda s: any(q["question"]["id"] != card["question"]["id"] and q["question"]["kind"] == "documents" for q in open_questions(s)), what="a second look at the documents", timeout=120)
    assert snap["phaseId"] == "prd"  # still waiting for you
    assert any(a["currentVersion"].startswith("v2") and "revised after feedback" in a["markdownContent"] for a in snap["artifacts"] if a["id"] == "art-prd")
    assert not any("Task:" in str(r.messages) for r in client.team_llm.requests)  # still nothing built
    assert command(client, type="prd.accept", artifactId="art-prd").json()["accepted"] is True
    wait_for(client, lambda s: s["phaseId"] == "build", what="the build phase", timeout=60)
    run = client.app.state.hub.get(WORKSPACE)
    run.engine.agile.desk.mode = "approve"  # the rest of this run is not under test
    for pending in run.questions.pending.values():
        pass


def test_what_you_say_during_the_build_reaches_the_team(client):
    command(client, type="sprint.start", brief=BRIEF)
    drive(client, lambda s: s["phaseId"] == "prd" and any(q["question"]["kind"] == "documents" for q in open_questions(s)), what="the documents")
    command(client, type="prd.accept", artifactId="art-prd")
    wait_for(client, lambda s: s["phaseId"] == "build", what="the build", timeout=60)
    told = command(client, type="sme.directive.submit", meetId="meet-directives", directive="Please keep every function short.")
    assert told.json()["accepted"] is True
    assert command(client, type="agent.task.reassign", agentId="agent-01", task="Add a docstring to every module.").json()["accepted"] is True
    snap = drive(client, lambda s: s["phaseId"] == "ship", what="the end", timeout=420)
    prompts = " ".join(str(r.messages) for r in client.team_llm.requests)
    assert "Please keep every function short." in prompts  # the developers were given it (as a standing instruction in their tasks)
    texts = [m["text"] for m in snap["messages"]]
    assert any("SME DIRECTIVE" in t or "keep every function short" in t for t in texts)
    audit = (client.tmp / "output").rglob("a2a-audit.jsonl")
    assert any("briefing" in p.read_text(encoding="utf-8") for p in audit)  # delivered over A2A like every other conversation
