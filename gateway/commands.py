"""What each of the frontend's eight commands does in the backend. Every one goes through a public call the terminal interface also uses: starting a run,
answering a question, the agile desk (note, interrupt and say, release), and the engine's A2A briefing."""

from __future__ import annotations

import uuid
from typing import Any

from gateway.models import CommandResult
from gateway.narrator import SME_ID
from gateway.runner import Conflict, WorkspaceRun

HUMAN_SENDERS = {SME_ID, "human", "sme", "sme-01"}


def result(accepted: bool, note: str = "") -> CommandResult:
    return CommandResult(accepted=accepted, commandId=f"cmd-{uuid.uuid4().hex[:12]}", note=note or None)


async def execute(run: WorkspaceRun, command: dict[str, Any]) -> CommandResult:
    kind = command["type"]
    n = run.narrator
    if kind == "sprint.start":
        await run.start(command["brief"], command.get("title"), command.get("repo"), command.get("constraints"))
        return result(True)

    if kind == "sme.directive.submit":
        text = command["directive"].strip()
        if run.questions.answer(text, command.get("questionId")) is not None:
            return result(True, "answered")
        return await direct(run, text, "SME DIRECTIVE")

    if kind == "prd.accept":
        item = run.questions.find(kind="documents")
        if item is None:
            return result(False, "There are no documents waiting for your approval.")
        run.questions.answer("Approve", item.id)
        return result(True)

    if kind == "message.create":
        message = command["message"]
        if message.get("senderId") not in HUMAN_SENDERS:
            return result(False, "Only you can post messages here; the agents speak for themselves.")
        return await direct(run, message["text"].strip(), None, meet_key=meet_key(run, message.get("meetId")))

    if kind == "debate.inject":
        return await direct(run, command["text"].strip(), "Challenge for the team", meet_key=meet_key(run, command.get("meetId")), team_kind="note")

    if kind == "consensus.force":
        item = run.questions.find(kind="approval")
        if item is None:
            return result(False, "No decision is waiting for your approval.")
        run.questions.answer("Approve", item.id)
        return result(True)

    if kind == "agent.task.reassign":
        dev = run.agent_to_dev(command["agentId"])
        if dev is None:
            return result(False, "That agent is not on the team (yet).")
        text = command["task"].strip()
        n.say("directives", "human", f"To {dev}: {text}")
        await run.engine.brief(dev, f"Message from the human: {text}", sender="human")
        return result(True, f"delivered to {dev}")

    if kind == "phase.advance":
        return advance(run, command["phaseId"])

    raise Conflict(f"Unhandled command {kind}")


def meet_key(run: WorkspaceRun, meet_id: str | None) -> str:
    """The key (without the 'meet-' prefix and run prefix) of a meet id the browser sent; unknown ones go to your directions."""
    prefix = f"meet-{run.narrator.prefix}"
    if meet_id and meet_id.startswith(prefix):
        return meet_id[len(prefix):]
    return "directives"


async def direct(run: WorkspaceRun, text: str, label: str | None, meet_key: str = "directives", team_kind: str | None = None) -> CommandResult:
    """Something you said that is not the answer to a question: it goes to the team the way a note or an interruption does in the terminal."""
    run.narrator.say(meet_key, "human", f"{label}: {text}" if label else text)
    full = f"{label}: {text}" if label and label != "SME DIRECTIVE" else text
    if run.desk is None:
        if not run.active:
            return result(False, "Start a sprint first; there is no team to tell yet.")
        run.queued_notes.append(full)  # the team is not built yet (the meeting is still running); it is told when it starts
        return result(True, "queued until the team starts")
    run.spawn(run.say_to_team(full, team_kind))
    return result(True)


def advance(run: WorkspaceRun, phase: str) -> CommandResult:
    """A request to change phase. The backend decides the phase by what is really happening, so this only agrees when the request matches reality."""
    current = run.p.phase
    if phase == current:
        return result(True, "already there")
    if phase == "kickoff" and run.state in ("idle", "done", "failed", "stopped"):
        run.set_phase("kickoff")
        return result(True)
    if phase == "build" and run.document_accepted:
        run.set_phase("build")
        return result(True)
    if phase == "ship" and run.state == "done":
        run.set_phase("ship")
        return result(True)
    raise Conflict(f"The workspace is in {current} and cannot move to {phase} yet; the team moves it on when the work is really there.")
