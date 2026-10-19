"""Says things to the browser in the frontend's vocabulary: agents, messages, meets, edges. The bridges (meeting and team) use this so that naming,
ids and colours are decided in one place."""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Optional

from gateway.models import Agent, Edge, Meet, Message, Question
from gateway.projection import Projection

SCRUM_MASTER_ID = "agent-sm"
SME_ID = "sme-01"
PALETTE = ["#E60000", "#161616", "#B8860B", "#2E7D6B", "#5B5B5B", "#7B3FA0", "#1F5FA8"]
ROLE_TITLES = {
    "BACKEND": "Backend Developer", "FRONTEND": "Frontend Developer", "DATABASE": "Database Developer", "AIML": "AI/ML Developer",
    "MLOPS": "MLOps Developer", "DEVOPS": "DevOps Developer",
}
SCRUM_KEYS = {"integrator", "scrum-master", "scrum_master", "system", "scrummaster"}
HUMAN_KEYS = {"human", "sme", "you", "user"}


def dev_number(key: str) -> Optional[int]:
    match = re.fullmatch(r"(?i)dev[_-]?(\d+)", key.strip())
    return int(match.group(1)) if match else None


def agent_id(key: str) -> str:
    """DEV_3 -> agent-03; the scrum master (and the integrator who answers for it) -> agent-sm; the human -> sme-01."""
    low = key.strip().lower()
    if low in HUMAN_KEYS:
        return SME_ID
    if low in SCRUM_KEYS:
        return SCRUM_MASTER_ID
    number = dev_number(key)
    if number is not None:
        return f"agent-{number:02d}"
    return "agent-" + re.sub(r"[^a-z0-9]+", "-", low).strip("-")


def agent_name(key: str) -> str:
    low = key.strip().lower()
    if low in HUMAN_KEYS:
        return "SME-01"
    if low in SCRUM_KEYS:
        return "Scrum Master"
    number = dev_number(key)
    return f"DEV_{number}" if number is not None else key.strip()


def clip(text: str, limit: int = 1800) -> str:
    text = str(text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class Narrator:
    def __init__(self, projection: Projection, prefix: str = "") -> None:
        self.p, self.prefix = projection, prefix
        self._lock = threading.Lock()
        self._counter = len(projection.messages)

    # ------------------------------------------------------------------ ids

    def meet_id(self, key: str) -> str:
        return f"meet-{self.prefix}{key}"

    def next_message_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"msg-{self.prefix}{self._counter:05d}"

    # ------------------------------------------------------------------ agents

    def seed(self) -> None:
        """A workspace is never empty: the scrum master and you are always present, so the views have something to show before a run starts."""
        if self.p.agents:
            return
        self.agent("scrum-master", role="Scrum Master", status="idle", avatarColor=PALETTE[1])
        self.agent("human", role="Business SME (you)", status="idle", avatarColor=PALETTE[0])

    def agent(self, key: str, **fields: Any) -> dict[str, Any]:
        aid = agent_id(key)
        existing = self.p.agents.get(aid, {})
        number = dev_number(key)
        payload: dict[str, Any] = {"id": aid, "name": existing.get("name") or agent_name(key), "role": existing.get("role") or "Developer"}
        if "avatarColor" not in existing and "avatarColor" not in fields:
            payload["avatarColor"] = PALETTE[(number or 0) % len(PALETTE)]
        payload.update(fields)
        known = Agent.model_validate({**existing, **payload})  # shape check; explicit nulls in `fields` are kept below to clear values
        out = known.dump()
        for name, value in fields.items():
            if value is None:
                out[name] = None
        return self.p.emit("agent.updated", out)

    # ------------------------------------------------------------------ conversation

    def meet(self, key: str, title: str, status: str = "live", consensus: Optional[float] = None, debate: Optional[float] = None) -> None:
        mid = self.meet_id(key)
        existing = self.p.meets.get(mid, {})
        payload = Meet(
            id=mid, title=title or existing.get("title", mid), status=status,  # type: ignore[arg-type]
            consensusRate=existing.get("consensusRate", 0) if consensus is None else consensus,
            debateIntensity=existing.get("debateIntensity", 0) if debate is None else debate,
        ).dump()
        if existing != payload:
            self.p.emit("meet.updated", payload)

    def say(self, meet_key: str, who: str, text: str, *, kind: Optional[str] = None, question: Optional[Question] = None, answers: Optional[str] = None) -> dict[str, Any]:
        payload = Message(
            id=self.next_message_id(), meetId=self.meet_id(meet_key), senderId=agent_id(who), senderName=agent_name(who), text=clip(text),
            timestamp=time.strftime("%H:%M:%S"), kind=kind, question=question, answersQuestion=answers,  # type: ignore[arg-type]
        ).dump()
        return self.p.emit("message.created", payload)

    def system(self, meet_key: str, text: str) -> dict[str, Any]:
        return self.say(meet_key, "scrum-master", text, kind="system")

    # ------------------------------------------------------------------ the graph

    def edge(self, source: str, target: str, label: str = "", active: bool = False, latency_ms: float = 0) -> None:
        a, b = agent_id(source), agent_id(target)
        eid = f"e-{a}-{b}"
        payload = Edge(id=eid, source=a, target=b, label=label or None, isActive=active, latencyMs=latency_ms).dump()
        if self.p.edges.get(eid) != payload:
            self.p.emit("edge.updated", payload)
