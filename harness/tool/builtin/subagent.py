"""The subagent tool (opencode: tool/plugin/subagent.ts, session/subagent-job.ts, session/subagent-completion.ts).

Spawns (or continues) a child session under a named agent. Foreground calls block the parent until the child is idle and return its last
text reply; background calls return at once and a synthetic message is delivered to the parent when the child finishes.

`deps.extras` supplies "sessions" (SessionService), "agents" (AgentRegistry), "jobs" (JobService); optional "subagent_depth" (default 1)
and "models_available" (callable returning dicts with provider_id, id, variants) to validate a `model` override."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from pydantic import BaseModel, Field

from harness.agent import Agent, AgentRegistry
from harness.job import Info as JobInfo
from harness.job import JobService
from harness.permission import evaluate
from harness.schema import message as M
from harness.session.service import SessionNotFoundError, SessionService
from harness.tool.builtin.deps import ToolDeps
from harness.tool.info import ToolContext, ToolError, ToolInfo, ToolResult

NAME = "subagent"
NO_TEXT = "Subagent completed without a text response."

DESCRIPTION = "\n".join([
    "Spawns an agent in a child session to work on the specified task.",
    "The output includes a sessionID you can pass back later to continue that specific conversation with the subagent.",
    "New child sessions start with fresh context, so include all relevant context and instructions when you don't pass a sessionID.",
    "Foreground (default) runs the subagent to completion and returns its final response.",
    "Background mode (background=true) launches it asynchronously and returns immediately; you are notified when it finishes.",
    "Use background only for independent work that can run while you continue elsewhere.",
])


class Input(BaseModel):
    agent: str = Field(description="The type of specialized agent to use for this task. If the user asks for a subagent by a name that is not one of the available subagents, they most likely mean a model: pick a suitable agent and pass the name through the model parameter instead.")
    description: str = Field(description="A short 3-5 word label for the task, displayed to the user")
    prompt: str = Field(description="The task for the subagent to perform")
    model: Optional[str] = Field(default=None, description='NEVER set this unless the user explicitly asks for a particular model or variant. The value is written as "providerID/modelID", or "providerID/modelID#variant" to include a variant. Do not guess the ID.')
    sessionID: Optional[str] = Field(default=None, description="Continue a specific previous subagent conversation by passing its sessionID. Calls without a sessionID start a new conversation.")
    background: Optional[bool] = Field(default=None, description="Run the subagent in the background and return immediately. You will be notified when it completes. DO NOT sleep, poll, or proactively check on its progress.")


def background_result(session_id: str) -> dict[str, Any]:
    return {
        "sessionID": session_id, "status": "running",
        "output": "\n".join([
            f"The subagent is working in the background (sessionID: {session_id}). You will be notified automatically when it finishes.",
            "DO NOT sleep, poll for progress, ask the subagent for status, or duplicate this subagent's work; avoid working with the same files or topics it is using.",
            "Work on non-overlapping tasks, or briefly tell the user what you launched and end your response.",
        ]),
    }


def completion_text(message: Optional[M.Info]) -> str:
    if not isinstance(message, M.Assistant):
        return NO_TEXT
    return "\n\n".join(p.text for p in message.content if isinstance(p, M.AssistantText) and p.text) or NO_TEXT


def parse_model(value: str) -> M.ModelRef:
    """providerID/modelID or providerID/modelID#variant."""
    body, _, variant = value.partition("#")
    provider, slash, model_id = body.partition("/")
    if not slash or not provider or not model_id or (_ and not variant):
        raise ValueError(value)
    return M.ModelRef(provider_id=provider, id=model_id, variant=variant or None)


def with_available_subagents(base: str, agents: AgentRegistry, selected: Optional[Agent]) -> str:
    """The tool description for a request: the base text plus the subagents the selected agent may call."""
    if selected is None:
        return base
    available = sorted(
        (a for a in agents.list() if a.mode != "primary" and not a.hidden and evaluate(NAME, a.id, selected.permissions).effect != "deny"),
        key=lambda a: a.id,
    )
    if not available:
        return base
    return "\n".join([base, "", "Available subagents:", *[f"- {a.id}: {a.description or 'This subagent should only be called when explicitly requested.'}" for a in available]])


def deliver(sessions: SessionService, jobs: JobService, info: JobInfo, recovery: dict[str, Any], resume: bool = True) -> None:
    if info.status == "running":
        return
    text = (info.output or NO_TEXT) if info.status == "completed" else (info.error or "Subagent failed") if info.status == "error" else "Subagent cancelled"
    sessions.synthetic(
        recovery["parentSessionID"],
        f'<subagent sessionID="{recovery["childSessionID"]}" state="{info.status}" description="{recovery["description"]}">\n{text}\n</subagent>',
        description=recovery["description"],
        metadata={"source": "subagent", "childID": recovery["childSessionID"], "agent": recovery["agent"], "state": info.status},
        resume=resume,
    )
    if info.notification_id:
        jobs.complete_background(info.notification_id)


class SubagentJobs:
    """Runs a child session as a background job and tells the parent when it finishes (opencode: session/subagent-job.ts)."""

    def __init__(self, sessions: SessionService, jobs: JobService) -> None:
        self.sessions, self.jobs = sessions, jobs
        self._watching: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    async def start(self, recovery: dict[str, Any]) -> JobInfo:
        child = recovery["childSessionID"]

        async def run() -> str:
            await self.sessions.resume(child)
            latest = next((m for m in self.sessions.messages(child, "desc", 20) if isinstance(m, M.Assistant) and m.time.completed is not None and m.error is None), None)
            return completion_text(latest)

        return await self.jobs.start(child, "subagent", run, title=recovery["description"], metadata={}, recovery=recovery)

    def background(self, recovery: dict[str, Any], job: Optional[JobInfo] = None) -> Optional[JobInfo]:
        """Moves the job to the background and watches for its end."""
        info = self.jobs.background(recovery["childSessionID"])
        if info:
            self.notify(recovery, info.started_at)
        return info

    def notify(self, recovery: dict[str, Any], started_at: int) -> None:
        """One observer per job generation, including continuations of the same child."""
        key = f"{recovery['childSessionID']}:{started_at}"
        if key in self._watching:
            return
        self._watching.add(key)

        async def watch() -> None:
            try:
                waited = await self.jobs.wait(recovery["childSessionID"])
                if waited.info:
                    deliver(self.sessions, self.jobs, waited.info, recovery)
            finally:
                self._watching.discard(key)

        task = asyncio.ensure_future(watch())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


def make(deps: ToolDeps) -> ToolInfo:
    sessions: SessionService = deps.extras["sessions"]
    agents: AgentRegistry = deps.extras["agents"]
    jobs: JobService = deps.extras["jobs"]
    subagent_jobs: SubagentJobs = deps.extras.setdefault("subagent_jobs", SubagentJobs(sessions, jobs))

    def resolve_model(value: str) -> M.ModelRef:
        try:
            ref = parse_model(value)
        except ValueError:
            raise ToolError(f'Invalid model "{value}". Use "providerID/modelID" or "providerID/modelID#variant".') from None
        catalog = deps.extras.get("models_available")
        if catalog is None:
            return ref
        model = next((m for m in catalog() if m["provider_id"] == ref.provider_id and m["id"] == ref.id), None)
        if model is None:
            raise ToolError(f'Model "{ref.provider_id}/{ref.id}" is not available. Use the models tool to see what is available.')
        variants = [v if isinstance(v, str) else v["id"] for v in model.get("variants", [])]
        if ref.variant is not None and ref.variant not in variants:
            raise ToolError(
                f'Model "{ref.provider_id}/{ref.id}" has no variants. Omit the variant.' if not variants
                else f'Variant "{ref.variant}" is not available for "{ref.provider_id}/{ref.id}". Available: {", ".join(variants)}.'
            )
        return ref

    async def execute(inp: Input, ctx: ToolContext) -> ToolResult:
        try:
            parent = sessions.get(ctx.session_id)
        except SessionNotFoundError:
            raise ToolError(f"Parent session not found: {ctx.session_id}") from None
        depth, current = 0, parent
        while current.parent_id:
            depth += 1
            try:
                current = sessions.get(current.parent_id)
            except SessionNotFoundError:
                raise ToolError(f"Parent session not found: {current.parent_id}") from None
        limit = deps.extras.get("subagent_depth", 1)
        if depth >= limit:
            raise ToolError(f'Subagent depth limit reached ({limit}). Increase "experimental.subagent_depth" to allow nested subagents.')
        agent = agents.resolve(inp.agent)
        if agent is None:
            raise ToolError(f"Unknown agent: {inp.agent}")
        if agent.mode == "primary":
            raise ToolError(f"Agent {inp.agent} cannot run as a subagent")
        try:
            await deps.assert_permission(ctx, NAME, [agent.id], save=[agent.id])
        except Exception as exc:  # noqa: BLE001
            from harness.permission import DeclinedError

            if isinstance(exc, DeclinedError):
                raise
            raise ToolError(f"Subagent denied: {agent.id}", exc) from None

        existing = None
        if inp.sessionID:
            try:
                existing = sessions.get(inp.sessionID)
            except SessionNotFoundError:
                raise ToolError(f"Subagent session not found: {inp.sessionID}") from None
            if existing.parent_id != ctx.session_id:
                raise ToolError(f"Session {existing.id} is not a child of the current session")
        override = resolve_model(inp.model) if inp.model else None
        # Continuing with a different agent switches the child: an explicit model wins over the agent's configured model, which wins over the inherited one.
        if existing is not None:
            switched = existing.agent != agent.id
            model = override or (agent.model if switched else None)
            if switched:
                sessions.switch_agent(existing.id, agent.id)
            if model is not None:
                sessions.switch_model(existing.id, model)
        parent_model = M.ModelRef(**parent.model) if parent.model else None
        child = existing or sessions.create(parent_id=ctx.session_id, title=inp.description, agent=agent.id, model=override or agent.model or parent_model)

        background = inp.background is True
        ctx.progress({"sessionID": child.id, "status": "running"})
        sessions.prompt(child.id, inp.prompt if existing is not None else "\n".join(["You are a subagent spawned by another session.", inp.prompt]))

        recovery = {"kind": "subagent", "parentSessionID": ctx.session_id, "childSessionID": child.id, "agent": agent.name, "description": inp.description}
        await subagent_jobs.start(recovery)
        if background:
            subagent_jobs.background(recovery)
            return _result(background_result(child.id))
        try:
            result = await jobs.block(child.id, ctx.session_id)
        except asyncio.CancelledError:
            await sessions.interrupt(child.id)
            await jobs.cancel(child.id)
            raise
        if result and result.type == "backgrounded":
            subagent_jobs.notify(recovery, result.info.started_at)
            return _result(background_result(child.id))
        # Failure surfaces keep the sessionID visible so the model can continue the child.
        if result and result.info.status == "error":
            raise ToolError(f"Subagent failed (sessionID: {child.id}): {result.info.error or 'unknown error'}")
        if result and result.info.status == "cancelled":
            raise ToolError(f"Subagent cancelled (sessionID: {child.id})")
        return _result({"sessionID": child.id, "status": "completed", "output": (result.info.output if result else None) or NO_TEXT})

    def _result(out: dict[str, Any]) -> ToolResult:
        content = f'<subagent sessionID="{out["sessionID"]}" state="completed">\n{out["output"]}\n</subagent>' if out["status"] == "completed" else out["output"]
        return ToolResult(content=content, output=out, metadata={"sessionID": out["sessionID"], "status": out["status"]})

    return ToolInfo(NAME, DESCRIPTION, Input, execute)


def repair_input(event: dict[str, Any]) -> None:
    """execute.before hook: models sometimes send empty strings for optional fields."""
    if event.get("tool") != NAME or not isinstance(event.get("input"), dict):
        return
    inp = event["input"]
    if inp.get("model") != "" and inp.get("sessionID") != "":
        return
    event["input"] = {k: v for k, v in inp.items() if not (k in ("model", "sessionID") and v == "")}
