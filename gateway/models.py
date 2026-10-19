"""The frontend contract as Python types (mirrors frontend/agentic-scrum-control-plane/src/domain/types.ts and commands.ts).

Field names are camelCase on purpose: they are the JSON the browser reads. Optional fields are left out of the JSON when unset, except where an
explicit null is meant to clear a value on the client (see `Projection.apply`)."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict

PHASES = ("kickoff", "brainstorm", "prd", "build", "review", "ship")
PhaseId = Literal["kickoff", "brainstorm", "prd", "build", "review", "ship"]
AgentStatus = Literal["idle", "active", "speaking", "blocked", "complete"]

EVENT_TYPES = (
    "agent.updated", "message.created", "phase.changed", "artifact.updated", "meet.updated", "metrics.updated", "skill.updated", "sprint.updated",
    "edge.updated",
)
COMMAND_TYPES = (
    "sprint.start", "phase.advance", "agent.task.reassign", "message.create", "sme.directive.submit", "prd.accept", "debate.inject", "consensus.force",
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")

    def dump(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class Agent(_Model):
    id: str
    name: str
    role: str
    status: AgentStatus = "idle"
    activeTask: Optional[str] = None
    confidenceScore: Optional[float] = None
    claimedSkill: Optional[str] = None
    activeBranch: Optional[str] = None
    contextUsagePercent: Optional[float] = None
    avatarColor: Optional[str] = None


class Question(_Model):
    """Something waiting for the human, shown as an SME question card in the transcript (an additive field on messages)."""

    id: str
    context: str
    kind: Literal["meeting", "approval", "documents"] = "meeting"
    options: list[str] = []
    recommended: Optional[str] = None


class Message(_Model):
    id: str
    meetId: str
    senderId: str
    senderName: str
    text: str
    timestamp: str
    kind: Optional[Literal["question", "system", "answer"]] = None
    question: Optional[Question] = None
    answersQuestion: Optional[str] = None


class Skill(_Model):
    id: str
    name: str
    instructions: Optional[str] = None
    claimedCount: int = 0


class ArtifactVersion(_Model):
    version: str
    timestamp: str
    author: str
    summary: str
    diffAdditions: list[str] = []
    diffDeletions: list[str] = []
    acceptedBy: list[str] = []


class Artifact(_Model):
    id: str
    title: str
    filename: str
    status: Literal["approved", "in_review", "draft"]
    currentVersion: str
    acceptedCount: int
    totalRequired: int
    versions: Optional[list[ArtifactVersion]] = None
    markdownContent: Optional[str] = None
    acceptedBy: Optional[list[str]] = None


class Meet(_Model):
    id: str
    title: str
    status: Literal["live", "completed", "scheduled"]
    consensusRate: float = 0
    debateIntensity: float = 0


class Sprint(_Model):
    id: str
    number: str
    title: str
    phase: str
    progress: float
    status: Literal["active", "completed"]


class Edge(_Model):
    id: str
    source: str
    target: str
    label: Optional[str] = None
    isActive: bool = False
    latencyMs: float = 0


class PrPoint(_Model):
    time: str
    prs: int


class Metrics(_Model):
    totalMessagesToday: int = 0
    totalPRs: int = 0
    prHistory: list[PrPoint] = []


class Snapshot(_Model):
    workspaceId: str
    version: int
    phaseId: PhaseId
    agents: list[Agent]
    messages: list[Message]
    skills: list[Skill]
    artifacts: list[Artifact]
    meets: list[Meet]
    sprints: list[Sprint]
    edges: list[Edge]
    metrics: Metrics
    processedEventIds: list[str]


class Event(_Model):
    eventId: str
    workspaceId: str
    occurredAt: str
    version: int
    type: Literal[
        "agent.updated", "message.created", "phase.changed", "artifact.updated", "meet.updated", "metrics.updated", "skill.updated", "sprint.updated",
        "edge.updated",
    ]
    payload: dict[str, Any]


class CommandResult(_Model):
    accepted: bool
    commandId: str
    note: Optional[str] = None


def validate_command(command: Any) -> Optional[str]:
    """The same rules the browser applies before it posts (commands.ts `validateWorkspaceCommand`). Returns an error message, or None when valid."""
    if not isinstance(command, dict):
        return "Command must be an object"
    kind = command.get("type")
    if kind not in COMMAND_TYPES:
        return f"Unknown command type: {kind}"
    if not isinstance(command.get("workspaceId"), str) or not command["workspaceId"]:
        return "workspaceId is required"

    def text(key: str) -> bool:
        value = command.get(key)
        return isinstance(value, str) and bool(value.strip())

    if kind == "sprint.start":
        if not text("brief"):
            return "brief is required"
        constraints = command.get("constraints")
        if constraints is not None and not (isinstance(constraints, list) and all(isinstance(c, str) for c in constraints)):
            return "constraints must be a list of strings"
        return None
    if kind == "phase.advance":
        return None if command.get("phaseId") in PHASES else "phaseId is required"
    if kind == "agent.task.reassign":
        if not command.get("agentId"):
            return "agentId is required"
        return None if text("task") else "task is required"
    if kind == "message.create":
        message = command.get("message")
        if not isinstance(message, dict) or not str(message.get("text", "")).strip():
            return "message.text is required"
        if not message.get("meetId"):
            return "message.meetId is required"
        return None if message.get("senderId") else "message.senderId is required"
    if kind == "sme.directive.submit":
        if not command.get("meetId"):
            return "meetId is required"
        return None if text("directive") else "directive is required"
    if kind == "prd.accept":
        return None if command.get("artifactId") else "artifactId is required"
    if kind == "debate.inject":
        if not command.get("meetId"):
            return "meetId is required"
        return None if text("text") else "text is required"
    if kind == "consensus.force":
        return None if command.get("meetId") else "meetId is required"
    return None
