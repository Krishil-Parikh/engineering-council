"""The workspace as the browser sees it, built from a log of events.

Everything the gateway tells the browser is an event with a unique id and a version that only goes up. The projection applies each event to a
canonical state (the same upserts the frontend's reducer does), keeps the recent ones for new subscribers, and appends every event to a file. The
snapshot is the state at the current version, and after a restart the state is rebuilt by replaying that file, so a page reload mid-run, or a
gateway restart, shows the same workspace."""

from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

from gateway.models import EVENT_TYPES, PHASES

MAX_PROCESSED_IDS = 500


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"


class Projection:
    def __init__(self, workspace_id: str, log_path: Optional[Path] = None, window: int = 200, max_messages: int = 500) -> None:
        self.workspace_id = workspace_id
        self.window, self.max_messages = window, max_messages
        self.version = 0
        self.phase = "kickoff"
        self.agents: dict[str, dict[str, Any]] = {}
        self.messages: list[dict[str, Any]] = []
        self.skills: dict[str, dict[str, Any]] = {}
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.meets: dict[str, dict[str, Any]] = {}
        self.sprints: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.metrics: dict[str, Any] = {"totalMessagesToday": 0, "totalPRs": 0, "prHistory": []}
        self._recent: deque[dict[str, Any]] = deque(maxlen=max(window, MAX_PROCESSED_IDS))
        self._subscribers: set[asyncio.Queue] = set()
        self._log_path = Path(log_path) if log_path else None
        self.listeners: list[Callable[[dict[str, Any]], None]] = []  # told of every event as it happens (the runner watches the phase this way)
        if self._log_path is not None and self._log_path.exists():
            self._replay()

    # ------------------------------------------------------------------ applying events

    def apply(self, event: dict[str, Any]) -> None:
        """The same upserts the frontend's reducer performs. Agents merge field by field; everything else is replaced by id."""
        kind, payload = event["type"], event["payload"]
        self.version = max(self.version, event["version"])
        if kind == "agent.updated":
            self.agents[payload["id"]] = {**self.agents.get(payload["id"], {}), **payload}
        elif kind == "message.created":
            if not any(m["id"] == payload["id"] for m in self.messages[-self.max_messages:]):
                self.messages.append(payload)
                self.metrics["totalMessagesToday"] = len(self.messages)
        elif kind == "phase.changed":
            self.phase = payload["phaseId"]
        elif kind == "artifact.updated":
            self.artifacts[payload["id"]] = payload
        elif kind == "meet.updated":
            self.meets[payload["id"]] = payload
        elif kind == "metrics.updated":
            self.metrics = payload
        elif kind == "skill.updated":
            self.skills[payload["id"]] = payload
        elif kind == "sprint.updated":
            self.sprints[payload["id"]] = payload
        elif kind == "edge.updated":
            self.edges[payload["id"]] = payload
        elif kind == "workspace.reset":
            # a new project: nothing of the previous one stays (the browser's reducer does the same)
            self.phase = "kickoff"
            self.agents, self.messages, self.skills, self.artifacts, self.meets, self.sprints, self.edges = {}, [], {}, {}, {}, {}, {}
            self.metrics = {"totalMessagesToday": 0, "totalPRs": 0, "prHistory": []}
        self._recent.append(event)

    def emit(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Records a change: gives it the next version, applies it, saves it and tells every subscriber."""
        if kind not in EVENT_TYPES:
            raise ValueError(f"unknown event type {kind!r}")
        if kind == "phase.changed" and payload.get("phaseId") not in PHASES:
            raise ValueError(f"unknown phase {payload.get('phaseId')!r}")
        event = {
            "eventId": f"evt-{self.version + 1}-{uuid.uuid4().hex[:8]}", "workspaceId": self.workspace_id, "occurredAt": now_iso(),
            "version": self.version + 1, "type": kind, "payload": payload,
        }
        self.apply(event)
        if self._log_path is not None:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        for listener in list(self.listeners):
            try:
                listener(event)
            except Exception:  # noqa: BLE001 - a watcher must never break the stream
                pass
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # a client that cannot keep up is dropped; it reconnects and is replayed what it missed
                self._subscribers.discard(queue)
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass
        return event

    def _replay(self) -> None:
        assert self._log_path is not None
        with open(self._log_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        self.apply(json.loads(line))
                    except (ValueError, KeyError):
                        continue  # a half-written last line after a crash

    # ------------------------------------------------------------------ reading

    def snapshot(self) -> dict[str, Any]:
        """The full canonical snapshot at the current version. Messages are capped to the most recent ones (older ones stay in the log file)."""
        data = {
            "workspaceId": self.workspace_id, "version": self.version, "phaseId": self.phase, "agents": list(self.agents.values()),
            "messages": self.messages[-self.max_messages:], "skills": list(self.skills.values()), "artifacts": list(self.artifacts.values()),
            "meets": list(self.meets.values()), "sprints": list(self.sprints.values()), "edges": list(self.edges.values()), "metrics": self.metrics,
            "processedEventIds": [e["eventId"] for e in list(self._recent)[-MAX_PROCESSED_IDS:]],
        }
        return copy.deepcopy(data)

    def recent(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        events = list(self._recent)
        return events[-(limit or self.window):]

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def find_message(self, message_id: str) -> Optional[dict[str, Any]]:
        return next((m for m in reversed(self.messages) if m["id"] == message_id), None)
