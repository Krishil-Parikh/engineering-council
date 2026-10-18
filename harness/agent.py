"""Agents (opencode: packages/core/src/agent.ts, plugin/agent.ts, plugin/plan.ts and config/plugin/agent.ts).

An agent is a named configuration: a system prompt (replacing the default one when set), a mode, a step limit, a model, and
a permission ruleset. The registry is rebuilt by replaying *transforms* in registration order, so later sources (the plan
plugin, then configuration files) override earlier ones without the earlier ones knowing about them."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Optional

from harness.config import markdown
from harness.config import service as cfg
from harness.schema.message import ModelRef
from harness.schema.permission import Rule, Ruleset
from harness.session.compaction import AgentInfo as RunAgent
from harness.util import fs

log = logging.getLogger("harness.agent")

DEFAULT_ID = "build"


@dataclass
class Agent:
    id: str
    name: str
    mode: str = "primary"  # primary | subagent | all
    hidden: bool = False
    system: Optional[str] = None
    description: Optional[str] = None
    model: Optional[ModelRef] = None
    color: Optional[str] = None
    steps: Optional[int] = None
    request: dict[str, Any] = field(default_factory=lambda: {"settings": {}, "headers": {}, "body": {}})
    permissions: Ruleset = field(default_factory=list)

    @staticmethod
    def default(agent_id: str) -> "Agent":
        return Agent(
            id=agent_id, name=agent_id,
            permissions=[
                Rule("*", "*", "allow"),
                Rule("read", "*.env", "ask"),
                Rule("read", "*.env.*", "ask"),
                Rule("read", "*.env.example", "allow"),
            ],
        )


class Editor:
    """What a transform may do to the agents."""

    def __init__(self, data: "_Data") -> None:
        self._d = data

    def list(self) -> list[Agent]:
        return list(self._d.agents.values())

    def get(self, agent_id: str) -> Optional[Agent]:
        return self._d.agents.get(agent_id)

    def default(self, agent_id: Optional[str]) -> None:
        self._d.default = agent_id

    def update(self, agent_id: str, fn: Callable[[Agent], None]) -> None:
        current = self._d.agents.get(agent_id)
        if current is None:
            current = self._d.agents[agent_id] = Agent.default(agent_id)
        fn(current)
        current.id = agent_id

    def remove(self, agent_id: str) -> None:
        self._d.agents.pop(agent_id, None)


@dataclass
class _Data:
    agents: dict[str, Agent] = field(default_factory=dict)
    default: Optional[str] = None


Transform = Callable[[Editor], None]


def selectable(agent: Optional[Agent]) -> Optional[Agent]:
    return agent if agent is not None and agent.mode != "subagent" and not agent.hidden else None


class AgentRegistry:
    def __init__(self) -> None:
        self._transforms: list[Transform] = []
        self._data = _Data()
        self._built = False

    def transform(self, fn: Transform) -> None:
        self._transforms.append(fn)
        self._built = False

    def reload(self) -> None:
        data = _Data()
        editor = Editor(data)
        for fn in self._transforms:
            fn(editor)
        self._data, self._built = data, True

    def _ensure(self) -> _Data:
        if not self._built:
            self.reload()
        return self._data

    def get(self, agent_id: str) -> Optional[Agent]:
        return self._ensure().agents.get(agent_id)

    def _selected_default(self) -> Optional[Agent]:
        d = self._ensure()
        configured = selectable(d.agents.get(d.default)) if d.default else None
        if configured:
            return configured
        build = selectable(d.agents.get(DEFAULT_ID))
        if build:
            return build
        return next((a for a in (selectable(x) for x in d.agents.values()) if a), None)

    def resolve(self, agent_id: Optional[str] = None) -> Optional[Agent]:
        if agent_id is not None:
            return self._ensure().agents.get(agent_id)
        return self._selected_default()

    def select(self, agent_id: Optional[str] = None) -> tuple[str, Optional[Agent]]:
        if agent_id is not None:
            return agent_id, self._ensure().agents.get(agent_id)
        info = self._selected_default()
        return (info.id if info else DEFAULT_ID), info

    def list(self) -> list[Agent]:
        agents = list(self._ensure().agents.values())
        sel = self._selected_default()
        return [sel, *[a for a in agents if a.id != sel.id]] if sel else agents

    def resolver(self) -> Callable[[Optional[str]], Optional[tuple[RunAgent, Ruleset]]]:
        """Adapter for SessionContext: (name) -> (what the runner needs, the agent's rules)."""

        def resolve(name: Optional[str]) -> Optional[tuple[RunAgent, Ruleset]]:
            a = self.resolve(name)
            return None if a is None else (RunAgent(a.id, a.system, a.steps), a.permissions)

        return resolve


# --------------------------------------------------------------------------- built-in agents

PROMPT_EXPLORE = """You are a file search specialist. You excel at thoroughly navigating and exploring codebases.

Guidelines:
- Your role is EXCLUSIVELY to search and analyze
- Parallelize independent tool calls for searches and reads whenever possible
- Adapt your search approach based on the thoroughness level specified by the caller
- Return file paths as absolute paths in your final response
- You MUST NOT create, modify, delete, move, or copy files, including temporary files and reports
- Shell commands MUST be read-only. NEVER run commands that write files or change system state

Complete the user's search request efficiently and report your findings clearly."""

PROMPT_TITLE = """You are a title generator. You output ONLY a thread title. Nothing else.

<task>
Generate a brief title that would help the user find this conversation later.

Follow all rules in <rules>
Use the <examples> so you know what a good title looks like.
Your output must be:
- A single line
- <=50 characters
- No explanations
</task>

<rules>
- you MUST use the same language as the user message you are summarizing
- Title must be grammatically correct and read naturally - no word salad
- Never include tool names in the title (e.g. "read tool", "bash tool", "edit tool")
- Focus on the main topic or question the user needs to retrieve
- Vary your phrasing - avoid repetitive patterns like always starting with "Analyzing"
- When a file is mentioned, focus on WHAT the user wants to do WITH the file, not just that they shared it
- Keep exact: technical terms, numbers, filenames, HTTP codes
- Remove: the, this, my, a, an
- Never assume tech stack
- Never use tools
- NEVER respond to questions, just generate a title for the conversation
- The title should NEVER include "summarizing" or "generating" when generating a title
- DO NOT SAY YOU CANNOT GENERATE A TITLE OR COMPLAIN ABOUT THE INPUT
- Always output something meaningful, even if the input is minimal.
- If the user message is short or conversational (e.g. "hello", "lol", "what's up", "hey"):
  -> create a title that reflects the user's tone or intent (such as Greeting, Quick check-in, Light chat, Intro message, etc.)
</rules>

<examples>
"debug 500 errors in production" -> Debugging production 500 errors
"refactor user service" -> Refactoring user service
"why is app.js failing" -> app.js failure investigation
"implement rate limiting" -> Rate limiting implementation
"how do I connect postgres to my API" -> Postgres API connection
"best practices for React hooks" -> React hooks best practices
"@src/credential.ts can you add refresh token support" -> Credential refresh token support
"@utils/parser.ts this is broken" -> Parser bug fix
"look at @config.json" -> Config review
"@App.tsx add dark mode toggle" -> Dark mode toggle in App
</examples>"""

PROMPT_SUMMARY = """Summarize what was done in this conversation. Write like a pull request description.

Rules:
- 2-3 sentences max
- Describe the changes made, not the process
- Do not mention running tests, builds, or other validation steps
- Do not explain what the user asked for
- Write in first person (I added..., I fixed...)
- Never ask questions or add new questions
- If the conversation ends with an unanswered question to the user, preserve that exact question
- If the conversation ends with an imperative statement or request to the user (e.g. "Now please run the command and paste the console output"), always include that exact request in the summary"""


def builtin_agents(editor: Editor) -> None:
    def build(a: Agent) -> None:
        a.name, a.description, a.mode = "Build", "The default agent. Executes tools based on configured permissions.", "primary"
        a.permissions.append(Rule("question", "*", "allow"))

    def general(a: Agent) -> None:
        a.name, a.mode = "General", "subagent"
        a.description = "General-purpose agent for researching complex questions and executing multi-step tasks. Use this agent to execute multiple units of work in parallel."
        a.permissions += [Rule("question", "*", "deny"), Rule("subagent", "*", "deny")]

    def explore(a: Agent) -> None:
        a.name, a.mode, a.system = "Explore", "subagent", PROMPT_EXPLORE
        a.description = (
            'Fast agent specialized for exploring codebases. Use this when you need to quickly find files by patterns (eg. "src/components/**/*.tsx"), '
            'search code for keywords (eg. "API endpoints"), or answer questions about the codebase (eg. "how do API endpoints work?"). When calling this agent, '
            'specify the desired thoroughness level: "quick" for basic searches, "medium" for moderate exploration, or "very thorough" for comprehensive analysis '
            "across multiple locations and naming conventions."
        )
        a.permissions += [
            Rule("*", "*", "deny"), Rule("shell", "*", "allow"), Rule("grep", "*", "allow"), Rule("glob", "*", "allow"), Rule("read", "*", "allow"),
            Rule("read", "*.env", "ask"), Rule("read", "*.env.*", "ask"), Rule("read", "*.env.example", "allow"),
            Rule("subagent", "*", "deny"), Rule("external_directory", "*", "allow"),
        ]

    def compaction(a: Agent) -> None:
        a.name, a.mode, a.hidden = "Compaction", "primary", True

    def title(a: Agent) -> None:
        a.name, a.mode, a.hidden, a.system = "Title", "primary", True, PROMPT_TITLE
        a.permissions.append(Rule("*", "*", "deny"))

    def summary(a: Agent) -> None:
        a.name, a.mode, a.hidden, a.system = "Summary", "primary", True, PROMPT_SUMMARY
        a.permissions.append(Rule("*", "*", "deny"))

    for agent_id, fn in (("build", build), ("general", general), ("explore", explore), ("compaction", compaction), ("title", title), ("summary", summary)):
        editor.update(agent_id, fn)


# --------------------------------------------------------------------------- plan mode

PLAN_ID = "plan"
PLAN_LEAVE = """<system-reminder>
You are NO LONGER in Plan mode. The previous Plan restrictions no longer apply. Any Plan mode instructions from earlier in this conversation are no longer active.
</system-reminder>"""


def plan_enter_reminder(directory: str) -> str:
    return f"""<system-reminder>
You are in Plan mode. Discuss the plan with the user directly in the conversation. Do not create or update plan files unless the user explicitly asks you to; when they do, write them only in:
{directory}

Do not modify any other files or ask a subagent to do so.

You remain in Plan mode until the user switches agents. If the user asks you to implement changes, do not do so. Tell them they need to switch agents.
</system-reminder>"""


def plan_agent(plan_directory: str) -> Transform:
    def transform(editor: Editor) -> None:
        def plan(a: Agent) -> None:
            a.name, a.mode = "Plan", "primary"
            a.description = "Read-only agent for exploring the codebase and planning work before implementation."
            a.permissions += [
                Rule("question", "*", "allow"), Rule("edit", "*", "deny"), Rule("edit", os.path.join(plan_directory, "*").replace("\\", "/"), "allow"),
            ]

        editor.update(PLAN_ID, plan)

    return transform


def plan_context_hook(plan_directory: str) -> Callable[[dict[str, Any]], None]:
    """Session `context` hook: keeps the Plan-mode reminder present exactly while the plan agent is active.

    Compaction and reverts can strip reminders while the agent stays put, so this reconciles on every request, placing the reminder
    just before the user's latest prompt (near the tail so the cached prefix stays warm)."""
    enter = plan_enter_reminder(plan_directory)

    def last_reminder(messages: list[Any]) -> Optional[str]:
        found = None
        for m in messages:
            if m.role == "user" and len(m.content) == 1 and getattr(m.content[0], "type", None) == "text":
                if m.content[0].text in (enter, PLAN_LEAVE):
                    found = m.content[0].text
        return found

    def hook(event: dict[str, Any]) -> None:
        from harness.ai import types as T

        messages = event["messages"]
        reminder = last_reminder(messages)
        missing = event["agent"] == PLAN_ID and reminder != enter
        stale = event["agent"] != PLAN_ID and reminder == enter
        text = enter if missing else PLAN_LEAVE if stale else None
        if text is None:
            return
        at = len(messages) - 1 if messages and messages[-1].role == "user" else len(messages)
        messages.insert(at, T.Message.user(text))
        event["synthetic"](text)  # persisted so the reminder is stable on later requests

    return hook


def plan_tool_hook(plan_directory: str) -> Callable[[dict[str, Any]], None]:
    """`tool.execute.after`: a blocked edit by the plan agent explains where plan files may go."""

    def hook(event: dict[str, Any]) -> None:
        from harness.permission import BlockedError
        from harness.tool.info import ToolError

        if event.get("agent") != PLAN_ID or event.get("status") != "error":
            return
        if event["tool"] not in ("edit", "write", "patch"):
            return
        if not isinstance(getattr(event["error"], "error", None), BlockedError):
            return
        event["error"] = ToolError(f"Cannot use {event['tool']} to modify files outside the Plan directory: {plan_directory}")

    return hook


# --------------------------------------------------------------------------- configuration

SOURCE_DIRECTORIES = ("agent", "agents", "mode", "modes")
_LEGACY_SOURCES = (("{agent,agents}/**/*.md", False), ("{mode,modes}/*.md", True))


def expand_home(resource: str, home: Path) -> str:
    if resource in ("~", "$HOME"):
        return str(home)
    for prefix in ("~/", "$HOME/", "$HOME\\"):
        if resource.startswith(prefix):
            return (home / resource[len(prefix):]).as_posix()
    return resource


_PATH_ACTIONS = {"external_directory", "read", "edit"}


def expand_permissions(rules: Ruleset, home: Path) -> Ruleset:
    # Only resources that tools resolve as filesystem paths are expanded; shell resources are raw command text.
    return [replace(r, resource=expand_home(r.resource, home)) if r.action in _PATH_ACTIONS else r for r in rules]


def parse_permissions(raw: Any) -> Ruleset:
    """Accepts a rule list [{action, resource, effect}] or the object syntax {"bash": {"git *": "allow"}, "edit": "deny"}."""
    out: Ruleset = []
    if isinstance(raw, list):
        for r in raw:
            if isinstance(r, dict) and {"action", "effect"} <= r.keys():
                out.append(Rule(r["action"], r.get("resource", "*"), r["effect"]))
    elif isinstance(raw, dict):
        for action, value in raw.items():
            if isinstance(value, str):
                out.append(Rule(action, "*", value))  # type: ignore[arg-type]
            elif isinstance(value, dict):
                out += [Rule(action, pattern, effect) for pattern, effect in value.items()]  # type: ignore[arg-type]
    return out


def _agent_documents(entries: list[cfg.Entry]) -> list[cfg.Document]:
    """Config documents, plus a document per Markdown agent file found in agent(s)/ and mode(s)/ of every config directory."""
    docs: list[cfg.Document] = []
    for entry in entries:
        if isinstance(entry, cfg.Document):
            docs.append(entry)
            continue
        for pattern, primary in _LEGACY_SOURCES:
            for filepath in sorted(fs.scan(pattern, entry.path, absolute=True, include="file", dot=True)):
                content = fs.read_text_safe(filepath)
                md = markdown.parse_option(content) if content else None
                if md is None:
                    continue
                name = re.sub(r"\.md$", "", re.sub(r"^(agent|agents|mode|modes)/", "", Path(os.path.relpath(filepath, entry.path)).as_posix()))
                info = {**md.data, "system": md.content.strip()}
                if "prompt" in info:  # the older spelling of the system prompt
                    info["system"] = info.pop("prompt") or info["system"]
                if primary:
                    info["mode"] = "primary"
                docs.append(cfg.Document({"agents": {name: info}}, Path(filepath)))
    return docs


def _model_ref(value: Any) -> Optional[ModelRef]:
    if isinstance(value, dict):
        return ModelRef(provider_id=value.get("providerID") or value.get("provider_id") or value.get("provider", ""), id=value.get("model") or value.get("id", ""), variant=value.get("variant"))
    if isinstance(value, str) and "/" in value:
        provider, _, rest = value.partition("/")
        model, _, variant = rest.partition("#")
        return ModelRef(provider_id=provider, id=model, variant=variant or None)
    return None


def config_agents(config: cfg.Config, home: Path) -> Transform:
    """Apply configuration: global permissions go onto every agent, then each configured agent is created or modified."""

    def transform(editor: Editor) -> None:
        documents = _agent_documents(config.entries())
        permissions = expand_permissions(
            [r for d in documents for r in [*parse_permissions(d.info.get("permissions")), *parse_permissions(d.info.get("permission"))]], home
        )
        configured_default = cfg.latest(documents, "default_agent")
        if configured_default is not None:
            editor.default(configured_default)
        for current in editor.list():
            editor.update(current.id, lambda a: a.permissions.extend(permissions))
        for d in documents:
            for agent_id, item in {**(d.info.get("agent") or {}), **(d.info.get("agents") or {})}.items():
                if not isinstance(item, dict):
                    continue
                if item.get("disabled"):
                    editor.remove(agent_id)
                    continue
                exists = editor.get(agent_id) is not None

                def apply(a: Agent, item: dict[str, Any] = item, exists: bool = exists) -> None:
                    if not exists:
                        a.permissions.extend(permissions)
                    if (m := _model_ref(item.get("model"))) is not None:
                        a.model = m
                    req = item.get("request")
                    if isinstance(req, dict):
                        a.request["headers"].update(req.get("headers") or {})
                        a.request["body"].update(req.get("body") or {})
                    for src, attr in (("system", "system"), ("description", "description"), ("mode", "mode"), ("hidden", "hidden"), ("color", "color"), ("steps", "steps")):
                        if item.get(src) is not None:
                            setattr(a, attr, item[src])
                    rules = [*parse_permissions(item.get("permissions")), *parse_permissions(item.get("permission"))]
                    if rules:
                        a.permissions.extend(expand_permissions(rules, home))

                editor.update(agent_id, apply)

    return transform


def default_registry(config: Optional[cfg.Config], home: Path, plan_directory: str) -> AgentRegistry:
    """Built-ins, then plan mode, then configuration (so configuration can override anything before it)."""
    reg = AgentRegistry()
    reg.transform(builtin_agents)
    reg.transform(plan_agent(plan_directory))
    if config is not None:
        reg.transform(config_agents(config, home))
    return reg
