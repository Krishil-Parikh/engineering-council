"""The agent loop. One `run` takes a user message and keeps calling the model and executing its tool calls until it answers in plain
text. Around that loop: retries with backoff, context compaction, a step limit, loop detection, background job notifications,
subagents and filesystem snapshots (undo)."""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from harness.legacy import agents as agent_defs
from harness.legacy.agents import BASE_RULES, Agent, prompt_text
from harness.legacy.compaction import Compactor
from harness.legacy.config import HarnessConfig, load_config
from harness.legacy.jobs import Job, JobManager
from harness.legacy.permission import Asker, Permissions, Rule, Ruleset, evaluate, wildcard
from harness.legacy.session import Session
from harness.legacy.snapshot import Snapshots
from harness.legacy.tools import builtin_tools
from harness.legacy.tools.base import FileTime, Tool, ToolContext, ToolFailure, truncate_result, validate_args
from harness.legacy.tools.shell import pick_shell
from harness.legacy.types import ChatModel, Event, Message, ModelError, ModelReply, Observer, ToolCall, ToolResult
from harness.legacy.workspace import Workspace

SHRINK_STEPS = (0.7, 0.5, 0.35)
MAX_MODEL_RETRIES = 10
MAX_LENGTH_CONTINUATIONS = 3
MAX_EMPTY_REPLIES = 2
DOOM_REPEATS = 3
TRUNCATION_HINT = "Use grep, or read with offset and limit, on that file to look at the part you need. Do not run the command again just to see more."


class HarnessError(Exception):
    """The run could not continue (the model is unreachable, the key is wrong, ...). The session is saved and can be resumed."""


@dataclass
class RunResult:
    text: str
    session_id: str
    steps: int = 0
    stopped: str = "completed"  # completed | max_steps | repeated_calls
    usage: dict[str, int] = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})


def tool_visible(action: str, rules: Ruleset) -> bool:
    """Hide a tool from the model when the rules deny every use of it (the model should not try what it can never do)."""
    if evaluate(action, "*", rules).effect != "deny":
        return True
    return any(r.action != "*" and wildcard(action, r.action) and r.effect != "deny" for r in rules)


class Runner:
    def __init__(
        self, workspace: Workspace, model: ChatModel, *, config: HarnessConfig | None = None, asker: Asker | None = None,
        ask_user: Callable[[list[dict[str, Any]]], Awaitable[list[str]]] | None = None, observer: Observer | None = None,
        agents: dict[str, Agent] | None = None, tools: list[Tool] | None = None, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.ws = workspace
        self.model = model
        self.cfg = config or load_config(workspace)
        self.observer = observer
        self.ask_user = ask_user
        self.sleep = sleep
        self.agents = {**agent_defs.default_agents(), **(agents or {})}
        self.tools: dict[str, Tool] = {t.name: t for t in (tools or builtin_tools())}
        self.permissions = Permissions(asker, store=workspace.data / "permissions.json")
        self.snapshots = Snapshots(workspace, self.cfg.snapshots)
        self.compactor = Compactor(model, window=self.cfg.context_window, keep=self.cfg.compaction_keep, auto=self.cfg.auto_compact, max_output=self.cfg.max_output_tokens)
        self.file_time = FileTime()
        self.sessions: dict[str, Session] = {}
        self._jobs: dict[str, JobManager] = {}
        self._depth: dict[str, int] = {}
        self._recent_calls: dict[str, list[str]] = {}
        self._last_input: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._identity: dict[str, str] | None = None

    # ------------------------------------------------------------------ plumbing
    def emit(self, session: Session | None, kind: str, data: dict[str, Any] | None = None) -> None:
        if self.observer:
            try:
                self.observer(Event(kind, {**(data or {}), **({"session": session.id, "agent": session.agent} if session else {})}))
            except Exception:  # a UI bug must never break a run
                pass

    def agent(self, agent_id: str) -> Agent:
        a = self.agents.get(agent_id)
        if a is None:
            raise HarnessError(f"Unknown agent {agent_id!r}. Available: {', '.join(self.agents)}")
        over = self.cfg.agent_overrides.get(agent_id)
        if over:
            a = Agent(**{**a.__dict__, **{k: v for k, v in over.items() if k in ("steps", "system", "temperature", "description")}})
            if "permission" in over:
                from harness.legacy.config import _rules

                a.permissions = [*a.permissions, *_rules(over["permission"])]
        return a

    def rules_for(self, agent: Agent) -> Ruleset:
        return [*BASE_RULES, *agent.permissions, *self.cfg.rules]

    def jobs_for(self, session: Session) -> JobManager:
        return self._jobs.setdefault(session.id, JobManager())

    def new_session(self, agent: str | None = None, parent: Session | None = None, title: str = "", cwd: Path | None = None) -> Session:
        s = Session(self.ws, agent or self.cfg.default_agent, parent_id=parent.id if parent else None, title=title, cwd=cwd)
        self.sessions[s.id] = s
        self._depth[s.id] = (self._depth.get(parent.id, 0) + 1) if parent else 0
        return s

    def resume_session(self, session_id: str) -> Session:
        s = self.sessions.get(session_id) or Session.load(self.ws, session_id)
        self.sessions[s.id] = s
        self._depth.setdefault(s.id, 0)
        return s

    def visible_tools(self, agent: Agent) -> list[Tool]:
        rules = self.rules_for(agent)
        return [t for t in self.tools.values() if (agent.tools is None or t.name in agent.tools) and tool_visible(t.permission or t.name, rules)]

    def tool_specs(self, agent: Agent, session: Session):
        subagents = [a for a in self.agents.values() if a.mode == "subagent" and not a.hidden and evaluate("subagent", a.id, self.rules_for(agent)).effect != "deny"]
        ctx = SimpleNamespace(subagents=subagents, skills=session.skills)
        return [t.spec(ctx) for t in self.visible_tools(agent)]

    # ------------------------------------------------------------------ prompts
    def system_prompt(self, agent: Agent, session: Session) -> str:
        argv, shell_name = pick_shell()
        env = "\n".join([
            "<env>",
            f"  Working directory: {session.cwd.as_posix()}",
            f"  Project root: {self.ws.root.as_posix()}",
            f"  Is directory a git repo: {'yes' if self.ws.is_git else 'no'}",
            f"  Platform: {sys.platform}",
            f"  Shell: {shell_name}",
            f"  Today's date: {date.today().strftime('%a %b %d %Y')}",
            f"  Scratch directory (pre-approved for temporary files): {self.ws.tmp.as_posix()}",
            "</env>",
        ])
        skills = session.skills.list()
        skill_text = ("Skills you can load with the skill tool:\n" + "\n".join(f"- {s.name}: {s.description}" for s in skills)) if skills else ""
        return "\n\n".join(p for p in [prompt_text("system.txt"), agent.system, env, session.instructions.system_block(), skill_text] if p)

    # ------------------------------------------------------------------ public API
    async def run(self, session: Session, text: str, agent_id: str | None = None) -> RunResult:
        agent = self.agent(agent_id or session.agent)
        session.agent = agent.id
        self._repair(session)
        user = session.add(Message(session.next_message_id(), "user", text, agent=agent.id, snapshot=self.snapshots.capture()))
        if not session.system_cache or getattr(session, 'system_agent', '') != agent.id:
            session.system_cache = self.system_prompt(agent, session)
            session.system_agent = agent.id
        self.emit(session, "message", {"role": "user", "text": text, "id": user.id})
        return await self._loop(session, agent)

    def undo(self, session: Session) -> list[str]:
        """Roll the project's files and the conversation back to just before the last user message."""
        idx = next((i for i in range(len(session.messages) - 1, -1, -1) if session.messages[i].role == "user" and not session.messages[i].synthetic), None)
        if idx is None:
            return []
        touched = self.snapshots.restore(session.messages[idx].snapshot)
        del session.messages[idx:]
        session.rewrite()
        session.save_meta()
        return touched

    async def compact(self, session: Session) -> bool:
        return await self.compactor.compact(session, emit=lambda e: self.emit(session, e.kind, e.data))

    async def close(self) -> None:
        for jm in self._jobs.values():
            await jm.cancel_all()

    # ------------------------------------------------------------------ the loop
    def _repair(self, session: Session) -> None:
        """A run that was interrupted may leave tool calls without results; the model API rejects that, so close them."""
        answered = {m.tool_call_id for m in session.messages if m.role == "tool"}
        fixed = False
        out: list[Message] = []
        for m in session.messages:
            out.append(m)
            if m.role == "assistant":
                for c in m.tool_calls:
                    if c.id not in answered:
                        out.append(Message(session.next_message_id(), "tool", "Tool execution was interrupted before it finished.", tool_call_id=c.id, tool_name=c.name, is_error=True, synthetic=True))
                        fixed = True
        if fixed:
            session.messages = out
            session.rewrite()

    def _view(self, session: Session) -> list[Message]:
        return session.active()

    async def _loop(self, session: Session, agent: Agent) -> RunResult:
        jobs = self.jobs_for(session)
        result = RunResult("", session.id)
        steps = length_cont = empty = strikes = 0
        while True:
            notes = jobs.drain()
            if notes:
                session.add(Message(session.next_message_id(), "user", "<system-reminder>\n" + "\n\n".join(notes) + "\n</system-reminder>", synthetic=True))
            upd = session.instructions.updates()
            if upd:
                session.add(Message(session.next_message_id(), "user", "<system-reminder>\n" + upd + "\n</system-reminder>", synthetic=True))
            steps += 1
            result.steps = steps
            final = steps > agent.steps
            await self.compactor.maybe_compact(session, session.system_cache, self._last_input.get(session.id), lambda e: self.emit(session, e.kind, e.data))
            messages = self._view(session)
            if final:
                messages = [*messages, Message("max_steps", "user", prompt_text("max_steps.txt"), synthetic=True)]
            specs = [] if final else self.tool_specs(agent, session)
            self.emit(session, "step", {"n": steps, "tools": len(specs)})
            reply = await self._complete(session, agent, messages, specs, "none" if final else "auto")
            result.usage["input_tokens"] += reply.usage.get("input_tokens", 0)
            result.usage["output_tokens"] += reply.usage.get("output_tokens", 0)
            if reply.usage.get("input_tokens"):
                self._last_input[session.id] = reply.usage["input_tokens"]
            calls = [] if final else reply.tool_calls
            msg = session.add(Message(session.next_message_id(), "assistant", reply.text, calls, raw=reply.raw if not final else None, usage=reply.usage, agent=agent.id,
                                  kind="partial" if reply.finish == "length" and not calls and length_cont < MAX_LENGTH_CONTINUATIONS else ""))
            self.emit(session, "message", {"role": "assistant", "text": reply.text, "id": msg.id, "tool_calls": len(calls)})
            if final:
                result.stopped = "max_steps"
                break
            if calls:
                empty = 0
                results = await asyncio.gather(*(self._run_tool(session, agent, c, jobs) for c in calls))
                for r in results:
                    session.add(r)
                if self._doom(session, calls):
                    strikes += 1
                    if strikes >= 3:
                        result.stopped = "repeated_calls"
                        session.add(Message(session.next_message_id(), "assistant", "I stopped because I kept repeating the same tool calls without making progress.", agent=agent.id))
                        break
                continue
            if reply.finish == "length" and length_cont < MAX_LENGTH_CONTINUATIONS:
                length_cont += 1
                session.add(Message(session.next_message_id(), "user", "<system-reminder>Your last reply was cut off by the output limit. Continue from where you stopped, in smaller pieces, and do not repeat what you already wrote.</system-reminder>", synthetic=True))
                continue
            if not reply.text.strip() and empty < MAX_EMPTY_REPLIES:
                empty += 1
                session.add(Message(session.next_message_id(), "user", "<system-reminder>Your last response was empty. Continue the task with a tool call, or give your final answer.</system-reminder>", synthetic=True))
                continue
            if jobs.running():
                self.emit(session, "note", {"text": "waiting for background work to finish"})
                if await jobs.wait_for_news(timeout=3600):
                    continue
            break
        session.save_meta()
        result.text = self._final_text(session)
        return result

    @staticmethod
    def _final_text(session: Session) -> str:
        """The last answer of the turn, including earlier pieces if it was cut off by the output limit and continued."""
        texts: list[str] = []
        for m in reversed(session.messages):
            if m.role == "user" and not m.synthetic:
                break
            if m.role == "assistant" and m.text.strip() and not m.tool_calls:
                if not texts or m.kind == "partial":
                    texts.append(m.text.strip())
                else:
                    break
        return "\n\n".join(reversed(texts))

    def _doom(self, session: Session, calls: list[ToolCall]) -> bool:
        """True when the model has issued the very same call (same tool, same arguments) several times in a row."""
        recent = self._recent_calls.setdefault(session.id, [])
        for c in calls:
            recent.append(c.name + json.dumps(c.args, sort_keys=True, default=str))
        del recent[:-DOOM_REPEATS * 2]
        return len(recent) >= DOOM_REPEATS and len(set(recent[-DOOM_REPEATS:])) == 1

    # ------------------------------------------------------------------ model call with retry
    async def _complete(self, session: Session, agent: Agent, messages: list[Message], specs, tool_choice: str) -> ModelReply:
        attempt = overflows = 0
        while True:
            try:
                return await self.model.complete(
                    system=session.system_cache, messages=messages, tools=specs, tool_choice=tool_choice,
                    on_event=lambda e: self.emit(session, e.kind, e.data), stage=f"{agent.id}:{session.id}", max_output_tokens=self.cfg.max_output_tokens,
                )
            except ModelError as exc:
                if exc.kind == "overflow":
                    if overflows < len(SHRINK_STEPS) and await self.compactor.compact(session, emit=lambda e: self.emit(session, e.kind, e.data), shrink=SHRINK_STEPS[overflows]):
                        messages = self._view(session)
                        overflows += 1
                        continue
                    raise HarnessError(f"The conversation is too long for the model and could not be compacted: {exc}") from None
                if exc.kind in ("rate_limit", "transient") and attempt < MAX_MODEL_RETRIES:
                    attempt += 1
                    delay = min(2.0 * 2 ** (attempt - 1), 10.0) * (0.8 + random.random() * 0.4)
                    if exc.retry_after:
                        delay = max(delay, min(exc.retry_after + 1, 900))
                    self.emit(session, "retry", {"attempt": attempt, "delay": round(delay, 1), "reason": exc.kind, "error": str(exc)[:200]})
                    await self.sleep(delay)
                    continue
                raise HarnessError(f"Model call failed ({exc.kind}): {exc}") from None

    # ------------------------------------------------------------------ tools
    async def _run_tool(self, session: Session, agent: Agent, call: ToolCall, jobs: JobManager) -> Message:
        def reply(res: ToolResult) -> Message:
            return Message(session.next_message_id(), "tool", res.output, tool_call_id=call.id, tool_name=call.name, is_error=res.is_error)

        tool = self.tools.get(call.name)
        visible = {t.name for t in self.visible_tools(agent)}
        if tool is None or call.name not in visible:
            return reply(ToolResult(f"Unknown tool {call.name!r}. Available tools: {', '.join(sorted(visible))}", is_error=True))
        recent = self._recent_calls.get(session.id, [])
        sig = call.name + json.dumps(call.args, sort_keys=True, default=str)
        if len(recent) >= DOOM_REPEATS - 1 and all(r == sig for r in recent[-(DOOM_REPEATS - 1):]):
            try:
                await self.permissions.assert_("doom_loop", [call.name], self.rules_for(agent), metadata={"args": call.args})
            except Exception:
                return reply(ToolResult(
                    f"You have made the identical {call.name} call {DOOM_REPEATS} times in a row. It will not give a different result. "
                    "Change your approach: re-read the real state of the files, try a different tool or arguments, or stop and explain what is blocking you.",
                    is_error=True))
        try:
            args = validate_args(call.args, tool.parameters)
        except ToolFailure as exc:
            return reply(ToolResult(f"{exc}. Expected arguments: {json.dumps(tool.parameters.get('properties', {}))[:600]}", is_error=True))
        ctx = ToolContext(
            session_id=session.id, agent=agent.id, call_id=call.id, workspace=self.ws, cwd=session.cwd, permissions=self.permissions,
            rules=self.rules_for(agent), file_time=self.file_time, jobs=jobs, session=session,
            spawn=lambda *a: self._spawn(session, agent, *a), ask_user=self.ask_user,
            emit=lambda kind, data: self.emit(session, kind, data), path_locks=self._locks, env=self._git_env(),
        )
        self.emit(session, "tool_start", {"id": call.id, "tool": call.name, "args": call.args})
        try:
            res = await tool.run(args, ctx)
        except ToolFailure as exc:
            res = ToolResult(str(exc), is_error=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a crashing tool must not end the run; the model gets to see what happened
            res = ToolResult(f"The {call.name} tool crashed: {type(exc).__name__}: {exc}", is_error=True)
        res = truncate_result(res, self.ws.output_dir, TRUNCATION_HINT)
        self.emit(session, "tool_end", {"id": call.id, "tool": call.name, "title": res.title, "error": res.is_error, "output": res.output[:2000], "metadata": {k: v for k, v in res.metadata.items() if k != "diff"}, "diff": res.metadata.get("diff", "")})
        return reply(res)

    def _git_env(self) -> dict[str, str]:
        """Commit identity for commands the agent runs, only when the machine has none configured (never rewrites git config)."""
        if self._identity is None:
            import subprocess

            def have(key: str) -> bool:
                try:
                    return bool(subprocess.run(["git", "config", key], cwd=self.ws.cwd, capture_output=True, text=True, timeout=10).stdout.strip())
                except (OSError, subprocess.SubprocessError):
                    return False

            self._identity = {} if have("user.name") and have("user.email") else {
                "GIT_AUTHOR_NAME": self.cfg.git_name, "GIT_COMMITTER_NAME": self.cfg.git_name,
                "GIT_AUTHOR_EMAIL": self.cfg.git_email, "GIT_COMMITTER_EMAIL": self.cfg.git_email,
            }
        return self._identity

    # ------------------------------------------------------------------ subagents
    async def _spawn(self, parent: Session, parent_agent: Agent, agent_id: str, prompt: str, description: str, session_id: str | None, background: bool, call_id: str) -> dict[str, Any]:
        depth = self._depth.get(parent.id, 0) + 1
        if depth > self.cfg.max_subagent_depth:
            raise ToolFailure(f"Subagents may only be nested {self.cfg.max_subagent_depth} deep.")
        if agent_id not in self.agents:
            raise ToolFailure(f"Unknown agent {agent_id!r}. Available: {', '.join(a.id for a in self.agents.values() if a.mode == 'subagent' and not a.hidden)}")
        child = None
        if session_id:
            try:
                child = self.resume_session(session_id)
            except (OSError, ValueError, KeyError):
                raise ToolFailure(f"No subagent session {session_id!r} to continue.") from None
        child = child or self.new_session(agent_id, parent, description, parent.cwd)
        self.emit(parent, "subagent_start", {"agent": agent_id, "session": child.id, "description": description})
        if background:
            jobs = self.jobs_for(parent)
            job = jobs.add(Job(jobs.next_id("agent"), "subagent", description))

            async def work() -> None:
                try:
                    res = await self.run(child, prompt, agent_id)
                    jobs.finish(job, "completed", f"Subagent `{description}` (sessionID: {child.id}) finished.\n\n{res.text or '(no text)'}")
                except asyncio.CancelledError:
                    jobs.finish(job, "cancelled", f"Subagent `{description}` was cancelled.")
                    raise
                except Exception as exc:  # noqa: BLE001
                    jobs.finish(job, "error", f"Subagent `{description}` failed: {exc}")

            job.task = asyncio.create_task(work())
            return {"sessionID": child.id, "status": "running", "output": ""}
        res = await self.run(child, prompt, agent_id)
        self.emit(parent, "subagent_end", {"agent": agent_id, "session": child.id})
        return {"sessionID": child.id, "status": "completed", "output": res.text or "(the subagent returned no text)"}
