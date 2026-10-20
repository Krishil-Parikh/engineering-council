"""The files a person can open: transcript.txt and the JSON summaries. All of them are projections of the events and can be rebuilt at any time."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from standup.adapters.layout import meeting_dir
from standup.events import MeetingEvent
from standup.state import MeetingState
from standup.transcript import render_event, render_transcript

JSON_TRIGGERS = frozenset({
    "meeting_created", "meeting_started", "meeting_paused", "meeting_resumed", "meeting_ended", "meeting_timed_out", "meeting_cancelled", "participant_joined", "participant_left",
    "skill_selected", "role_assigned", "question", "clarification_requested", "clarification_answered", "decision_proposed", "decision_accepted", "decision_rejected",
    "decision_deferred", "action_item_created", "action_item_updated", "human_takeover", "autopilot_enabled", "summary_generated", "risk_raised", "dependency_identified",
    "document_review_started", "document_approved", "document_changes_requested", "sme_approval_requested", "sme_approved", "sme_rejected",
})


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=lambda o: o.model_dump(mode="json") if hasattr(o, "model_dump") else str(o)))


def write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_plain(data), indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def projections(state: MeetingState) -> dict[str, Any]:
    return {
        "decisions.json": list(state.decisions.values()),
        "questions.json": list(state.questions.values()),
        "action-items.json": list(state.actions.values()),
        "participants.json": list(state.participants.values()),
        "metadata.json": {
            "meeting": state.meeting, "last_sequence": state.last_sequence, "risks": list(state.risks.values()), "dependencies": list(state.dependencies.values()),
            "documents": list(state.reviews.values()), "approvals": list(state.approvals.values()), "summary": state.summary,
        },
    }


class FileProjections:
    """Implements MeetingWriter: appends each event to transcript.txt and keeps the JSON summaries current."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def write(self, event: MeetingEvent, state: MeetingState) -> None:
        folder = meeting_dir(self.root, event.workspace_id, event.meeting_id)
        folder.mkdir(parents=True, exist_ok=True)
        line = render_event(event, state)
        if line is not None:
            with open(folder / "transcript.txt", "a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
        if event.event_type in JSON_TRIGGERS:
            for filename, data in projections(state).items():
                write_json(folder / filename, data)

    def rebuild(self, workspace_id: str, meeting_id: str, events: list[MeetingEvent]) -> None:
        folder = meeting_dir(self.root, workspace_id, meeting_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "transcript.txt").write_text(render_transcript(events), encoding="utf-8", newline="\n")
        state = MeetingState()
        state.apply_all(events)
        for filename, data in projections(state).items():
            write_json(folder / filename, data)
