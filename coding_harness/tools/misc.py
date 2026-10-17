"""webfetch, skill, question, todo and subagent."""

from __future__ import annotations

import asyncio
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any

from coding_harness.tools.base import Tool, ToolContext, ToolFailure
from coding_harness.types import ToolResult

MAX_FETCH_BYTES = 5 * 1024 * 1024


# --------------------------------------------------------------------------- webfetch


class _Html2Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "iframe"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0
        self._href: list[str] = []
        self._pre = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip += 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in ("p", "div", "section", "article", "tr", "br"):
            self.out.append("\n")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag == "pre":
            self._pre += 1
            self.out.append("\n```\n")
        elif tag == "a":
            self._href.append(dict(attrs).get("href") or "")
            self.out.append("[")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "pre" and self._pre:
            self._pre -= 1
            self.out.append("\n```\n")
        elif tag == "a" and self._href:
            self.out.append(f"]({self._href.pop()})")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.out.append(data if self._pre else re.sub(r"\s+", " ", data))


def html_to_text(html: str) -> str:
    p = _Html2Text()
    p.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "".join(p.out)).strip()


class WebFetchTool(Tool):
    name = "webfetch"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The http(s) URL to fetch"},
            "format": {"type": "string", "description": "markdown (default), text or html"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 30, max 120)"},
        },
        "required": ["url"],
    }

    def description(self, ctx: Any = None) -> str:
        return "Fetch a web page or API response and return it as markdown, text or html. Read-only. Use it for documentation and issue pages."

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        url: str = args["url"]
        if not url.startswith(("http://", "https://")):
            raise ToolFailure("URL must start with http:// or https://")
        await ctx.permit("webfetch", [url])
        fmt = args.get("format") or "markdown"
        timeout = min(120, int(args.get("timeout") or 30))

        def fetch() -> tuple[str, str]:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; coding-harness)", "Accept": "text/html,text/plain,application/json,*/*"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - scheme checked above
                    raw = resp.read(MAX_FETCH_BYTES + 1)
                    return raw.decode(resp.headers.get_content_charset() or "utf-8", "replace"), resp.headers.get("Content-Type", "")
            except urllib.error.HTTPError as exc:
                raise ToolFailure(f"Request failed with status {exc.code}") from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise ToolFailure(f"Request failed: {exc}") from None

        body, ctype = await asyncio.to_thread(fetch)
        if len(body) > MAX_FETCH_BYTES:
            raise ToolFailure("Response is larger than 5 MB.")
        text = html_to_text(body) if "html" in ctype.lower() and fmt != "html" else body
        return ToolResult(text, title=url, metadata={"content_type": ctype})


# --------------------------------------------------------------------------- skill


class SkillTool(Tool):
    name = "skill"
    parameters = {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "The name of an available skill"}},
        "required": ["id"],
    }

    def description(self, ctx: Any = None) -> str:
        base = "Load a specialized skill's instructions into the conversation when the task matches its description."
        skills = getattr(ctx, "skills", None)
        if skills:
            return base + "\n\nAvailable skills:\n" + "\n".join(f"- {s.name}: {s.description}" for s in skills.list())
        return base

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        skills = ctx.session.skills
        skill = skills.get(args["id"])
        if not skill:
            names = ", ".join(s.name for s in skills.list()) or "none"
            raise ToolFailure(f"Unknown skill {args['id']!r}. Available: {names}")
        await ctx.permit("skill", [skill.name])
        files = [p.relative_to(skill.directory).as_posix() for p in sorted(skill.directory.rglob("*")) if p.is_file() and p.name != "SKILL.md"][:40]
        body = f'<skill name="{skill.name}" directory="{skill.directory.as_posix()}">\n{skill.body}\n</skill>'
        if files:
            body += "\n\nFiles in the skill directory:\n" + "\n".join(f"- {f}" for f in files)
        return ToolResult(body, title=skill.name, metadata={"directory": str(skill.directory)})


# --------------------------------------------------------------------------- question


class QuestionTool(Tool):
    name = "question"
    parameters = {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "description": "Questions to ask the user",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "The complete question"},
                        "header": {"type": "string", "description": "Very short label (max 30 chars)"},
                        "options": {"type": "array", "description": "Choices: objects with label and description", "items": {"type": "object"}},
                        "multiple": {"type": "boolean", "description": "Allow selecting several choices"},
                    },
                    "required": ["question"],
                },
            }
        },
        "required": ["questions"],
    }

    def description(self, ctx: Any = None) -> str:
        return (
            "Ask the user questions when you need a decision only they can make (preferences, ambiguous requirements, which of "
            "several approaches). Put your recommended option first. Do not ask what the code or documentation already answers."
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if ctx.ask_user is None:
            raise ToolFailure("No one is available to answer questions. Make the most reasonable assumption, state it, and continue.")
        answers = await ctx.ask_user(args["questions"])
        lines = [f'"{q.get("question", "")}" = "{a}"' for q, a in zip(args["questions"], answers)]
        return ToolResult("The user answered:\n" + "\n".join(lines), title="question", metadata={"answers": answers})


# --------------------------------------------------------------------------- todo


class TodoTool(Tool):
    name = "todo"
    parameters = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "The complete, updated todo list",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Brief description of the task"},
                        "status": {"type": "string", "description": "pending, in_progress, completed or cancelled"},
                        "priority": {"type": "string", "description": "high, medium or low"},
                    },
                    "required": ["content", "status"],
                },
            }
        },
        "required": ["todos"],
    }

    def description(self, ctx: Any = None) -> str:
        return (
            "Maintain a todo list for a multi-step task. Send the COMPLETE list each time. Use it for work with three or more steps; keep exactly "
            "one item in_progress and mark items completed as soon as they are done. Skip it for trivial requests."
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        todos = args["todos"]
        for t in todos:
            if t.get("status") not in ("pending", "in_progress", "completed", "cancelled"):
                raise ToolFailure(f"Invalid status {t.get('status')!r}; use pending, in_progress, completed or cancelled.")
        ctx.session.todos = todos
        ctx.session.save_meta()
        open_ = sum(1 for t in todos if t["status"] not in ("completed", "cancelled"))
        return ToolResult(f"{open_} todos remaining\n" + "\n".join(f"[{t['status']}] {t['content']}" for t in todos), title=f"{open_} todos")


# --------------------------------------------------------------------------- subagent


class SubagentTool(Tool):
    name = "subagent"
    parameters = {
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "The type of specialized agent to use for this task"},
            "description": {"type": "string", "description": "A short 3-5 word label for the task"},
            "prompt": {"type": "string", "description": "The task for the subagent. It starts with no context, so include everything it needs."},
            "sessionID": {"type": "string", "description": "Continue a previous subagent conversation by passing its sessionID"},
            "background": {"type": "boolean", "description": "Run it in the background; you are notified when it completes. Do NOT poll."},
        },
        "required": ["agent", "description", "prompt"],
    }

    def description(self, ctx: Any = None) -> str:
        agents = getattr(ctx, "subagents", None) or []
        listing = "\n".join(f"- {a.id}: {a.description}" for a in agents)
        return (
            "Spawn an agent in a child session to work on a task and return its final answer. The output includes a sessionID you can pass "
            "back to continue that conversation. New child sessions start with fresh context, so include all relevant context. Launch several "
            "in one step to run independent tasks in parallel. Use background=true only for independent work.\n\nAvailable agents:\n" + listing
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if ctx.spawn is None:
            raise ToolFailure("This agent cannot start subagents.")
        await ctx.permit("subagent", [args["agent"]])
        out = await ctx.spawn(args["agent"], args["prompt"], args["description"], args.get("sessionID"), bool(args.get("background")), ctx.call_id)
        if out["status"] == "running":
            text = (
                f"The subagent is working in the background (sessionID: {out['sessionID']}). You will be notified automatically when it finishes.\n"
                "DO NOT sleep, poll, ask it for status, or duplicate its work. Work on non-overlapping tasks or end your response."
            )
        else:
            text = f"sessionID: {out['sessionID']}\n\n{out['output']}"
        return ToolResult(text, title=args["description"], metadata={"sessionID": out["sessionID"], "status": out["status"]})
