"""The harness as one object: everything wired together for a working directory.

    h = Harness("path/to/project", api_key=...)          # or llm=<anything with .stream(request)>
    result = await h.prompt("add a --verbose flag")      # runs the build agent until it is idle
    await h.close()

One Harness owns one Location (a working directory in a project), its SQLite session database, configuration, agents, skills, tools,
permissions, snapshots and worktrees. Child sessions (subagents) live inside the same Harness. For several developers working in parallel,
give each their own Harness on their own directory: they share nothing, so none of them waits for another.

Permissions: a rule that says "ask" needs an answer. With a UI, pass `approve` (called with the pending request; return "once", "always",
"reject", or ("reject", "what to do instead")). Without one the default is to reject, so an unattended agent can never hang on a prompt."""

from __future__ import annotations

import inspect
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

from harness.agent import AgentRegistry, default_registry
from harness.ai.catalog import ModelCatalog
from harness.ai.gemini import GeminiClient
from harness.ai.model import ResolvedModel
from harness.config import service as cfg
from harness.db.database import Database
from harness.file_access import FileAccess
from harness.form import FormService
from harness.instruction_discovery import InstructionDiscovery
from harness.job import JobService
from harness.location import Location
from harness.permission import Permission, PermissionSaved
from harness.ripgrep import Ripgrep
from harness.schema import message as M
from harness.schema.permission import Request, Ruleset
from harness.session import compaction as C
from harness.session.context import SessionContext
from harness.session.instructions import SessionInstructions
from harness.session.runner.runner import SessionRunner
from harness.session.service import SessionService
from harness.session.store import SessionInfo, SessionStore
from harness.shell.service import ShellService
from harness.skill import SkillCatalog
from harness.skill_loader import SkillLoader
from harness.snapshot import Snapshots
from harness.tool.builtin import edit, harness_tools, question, read, search, shell, skill, subagent, write
from harness.tool.builtin.deps import ToolDeps
from harness.tool.output import ToolOutput
from harness.tool.registry import ToolRegistry
from harness.util.global_paths import GlobalPaths
from harness.worktree import WorktreeManager

DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_PROVIDER = "google"

Reply = Union[str, tuple[str, Optional[str]]]
Approver = Callable[[Request], Union[Reply, Awaitable[Reply]]]


@dataclass
class RunResult:
    session_id: str
    outcome: str  # succeeded | failed | interrupted
    steps: int
    text: str  # the last assistant text of the run
    error: Optional[str] = None


def last_text(messages: list[M.Info]) -> str:
    for m in reversed(messages):
        if isinstance(m, M.Assistant):
            text = "\n\n".join(p.text for p in m.content if isinstance(p, M.AssistantText) and p.text)
            if text:
                return text
    return ""


class Harness:
    def __init__(
        self, directory: str | Path, *, llm: Any = None, api_key: Optional[str] = None, model: Optional[str] = None,
        data_root: Optional[Path] = None, home: Optional[Path] = None, db_path: Optional[str | Path] = None,
        approve: Optional[Approver] = None, snapshots: bool = True, catalog: Optional[ModelCatalog] = None,
        on_event: Optional[Callable[[str, dict[str, Any]], None]] = None, compaction: Optional[C.Settings] = None,
    ) -> None:
        self.on_event = on_event or (lambda kind, data: None)
        self.approve = approve
        self.model_id = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
        self.location = Location.of(directory)
        self.paths = GlobalPaths.default(root=data_root, home=home).ensure()
        self.db = Database(db_path if db_path is not None else self.paths.data / "sessions" / f"{self.location.project_id}.db")
        self.store = SessionStore(self.db)
        self.config = cfg.Config(self.location, self.paths)
        self.catalog = catalog or ModelCatalog()
        self.llm = llm if llm is not None else GeminiClient(api_key or os.environ["GEMINI_API_KEY"], self.model_id)
        plan_directory = str(self.location.project_directory / ".harness" / "plans")
        self.agents: AgentRegistry = default_registry(self.config, self.paths.home, plan_directory)
        self.skills = SkillCatalog()
        self.skills.add_provider(SkillLoader(self.config, self.paths, self.location.directory).load)
        self._pending_tasks: set = set()

        self.permission = Permission(PermissionSaved(self.db, self.location.project_id), self._rules_for, observer=self._permission_event)
        self.access = FileAccess(self.location, self.permission, home=self.paths.home)
        self.forms = FormService(on_event=lambda kind, data: self.on_event(f"form.{kind}", data))
        self.jobs = JobService()
        self.shell = ShellService(self.paths.data / "shell" / self.location.project_id, str(self.location.directory), on_event=lambda k, d: self.on_event(f"shell.{k}", d))
        self.worktrees = WorktreeManager(self.db, self.location, self.paths, on_event=lambda k, d: self.on_event(f"worktree.{k}", d)) if self.location.vcs == "git" else None
        self.snapshots = Snapshots(self.location, self.paths, enabled=snapshots)

        self.registry = ToolRegistry()
        self.tool_output = ToolOutput(self.paths.data / "tool-output")
        self.runner = SessionRunner(
            store=self.store, llm=self.llm, compaction=C.Compaction(self.store, self.llm, settings=compaction or C.Settings()), tool_output=self.tool_output,
            context=SessionContext(
                self.store, self.location, self.paths, InstructionDiscovery(self.location, self.paths, self.config), self.skills,
                resolve_agent=self._resolve_agent, resolve_model=self._resolve_model, tools_for=self.registry.snapshot,
            ),
            snapshots=self.snapshots, observer=self.on_event,
        )
        self.sessions = SessionService(self.store, self.runner, str(self.location.directory))
        self.deps = ToolDeps(
            self.location, self.permission, self.access, self.store, SessionInstructions(self.store, self.location), Ripgrep(),
            extras={
                "shell": self.shell, "jobs": self.jobs, "sessions": self.sessions, "agents": self.agents, "forms": self.forms, "skills": self.skills,
                "worktrees": self.worktrees, "model_catalog": self.catalog, "models_available": self.catalog.available,
                "synthetic": lambda sid, text, description, metadata: self.sessions.synthetic(sid, text, description, metadata),
            },
        )
        self._register_tools()

    # ------------------------------------------------------------------ wiring

    def _register_tools(self) -> None:
        for make in (read.make, edit.make, write.make, search.make_glob, search.make_grep, shell.make, subagent.make, question.make, skill.make):
            self.registry.add(make(self.deps))
        if self.worktrees is not None:
            for tool in harness_tools.make_all(self.deps):
                self.registry.add(tool)
        else:  # without a git repository only the session tools make sense
            for tool in harness_tools.make_all(self.deps):
                if tool.name.startswith("session_") or tool.name == "models":
                    self.registry.add(tool)
        self.registry.before.append(subagent.repair_input)
        selected = self.agents.resolve()
        self.registry.update("subagent", lambda t: setattr(t, "description", subagent.with_available_subagents(t.description, self.agents, selected)))

    def _rules_for(self, session_id: str, agent: Optional[str]) -> Ruleset:
        info = self.agents.resolve(agent) if agent else None
        session = self.store.get(session_id)
        return [*(info.permissions if info else []), *(session.permission_rules() if session else [])]

    def _resolve_agent(self, name: Optional[str]):
        return self.agents.resolver()(name)

    def _resolve_model(self, session: SessionInfo) -> ResolvedModel:
        ref = M.ModelRef(**session.model) if session.model else None
        agent = self.agents.resolve(session.agent)
        ref = ref or (agent.model if agent and agent.model else None) or M.ModelRef(provider_id=DEFAULT_PROVIDER, id=self.model_id)
        return self.catalog.resolve(ref)

    def _permission_event(self, kind: str, data: dict[str, Any]) -> None:
        self.on_event(kind, data)
        if kind == "permission.asked":
            import asyncio

            task = asyncio.ensure_future(self._answer(data["request"]))
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)

    async def _answer(self, request: Request) -> None:
        reply: Reply = "reject"
        if self.approve is not None:
            result = self.approve(request)
            reply = await result if inspect.isawaitable(result) else result
        choice, message = (reply, None) if isinstance(reply, str) else reply
        try:
            self.permission.reply(request.id, choice, message)
        except Exception:  # noqa: BLE001 - already answered (for example by a batch rejection)
            pass

    # ------------------------------------------------------------------ use

    def new_session(self, agent: Optional[str] = None, title: Optional[str] = None, model: Optional[str] = None) -> SessionInfo:
        chosen = agent or self.agents.select()[0]
        ref = M.ModelRef(provider_id=DEFAULT_PROVIDER, id=model or self.model_id)
        return self.sessions.create(title=title, agent=chosen, model=ref)

    async def prompt(self, text: str, session_id: Optional[str] = None, agent: Optional[str] = None) -> RunResult:
        """Adds a user message and runs the session until it is idle. A new session is started when none is given."""
        info = self.sessions.get(session_id) if session_id else self.new_session(agent)
        if agent and info.agent != agent:
            self.sessions.switch_agent(info.id, agent)
        self.sessions.prompt(info.id, text)
        drained = await self.sessions.resume(info.id)
        return RunResult(info.id, drained.outcome, drained.steps, last_text(self.sessions.messages(info.id)), drained.error.message if drained.error else None)

    async def close(self) -> None:
        await self.sessions.close()
        await self.shell.close()
        self.forms.close()
        for task in list(self._pending_tasks):
            task.cancel()
        self.db.close()
