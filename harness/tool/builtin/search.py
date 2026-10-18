"""The glob and grep tools (opencode: tool/plugin/glob.ts and tool/plugin/grep.ts)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from harness.ripgrep import InvalidPatternError, RipgrepError
from harness.tool.builtin.deps import ToolDeps
from harness.tool.info import ToolContext, ToolError, ToolInfo, ToolResult

DEFAULT_SEARCH_LIMIT = 100
DEFAULT_SEARCH_TIMEOUT_MS = 30_000

GLOB_NAME = "glob"
GLOB_DESCRIPTION = 'Search file paths using a glob pattern (examples: "**/*.ts", "src/**/*.tsx").'
GREP_NAME = "grep"
GREP_DESCRIPTION = (
    "Search file contents using ripgrep's regular expression syntax or literal text matching. Use it to locate specific code, symbols, or text "
    "patterns, and narrow searches with `path` or `include`. Returns matching file paths, line numbers, and line previews."
)


class GlobInput(BaseModel):
    pattern: str = Field(description="Glob pattern to match files against")
    path: Optional[str] = Field(default=None, description="Directory to search. Defaults to the current working directory.")
    hidden: Optional[bool] = Field(default=None, description="Include hidden files and directories (default: false).")
    limit: Optional[int] = Field(default=None, ge=1, description=f"Maximum number of matching files to return (default: {DEFAULT_SEARCH_LIMIT})")


class GrepInput(BaseModel):
    pattern: str = Field(min_length=1, description="Regular expression or literal text to match in file contents.")
    path: Optional[str] = Field(default=None, description="File or directory to search. Defaults to the current working directory.")
    include: Optional[str] = Field(default=None, description='Glob pattern to filter files (for example, "*.js" or "*.{ts,tsx}")')
    literal: Optional[bool] = Field(default=None, description="Treat `pattern` as exact text instead of a regular expression (default: false).")
    caseSensitive: Optional[bool] = Field(default=None, description="Use case-sensitive matching (default: true).")
    limit: Optional[int] = Field(default=None, ge=1, description=f"Maximum number of matching lines to return (default: {DEFAULT_SEARCH_LIMIT})")


def glob_model_content(paths: list[str], truncated: bool = False) -> str:
    lines = ["No files found"] if not paths else list(paths)
    if truncated:
        lines += ["", f"(Results are truncated: showing first {len(paths)} results. Consider using a more specific path or pattern.)"]
    return "\n".join(lines)


def grep_model_content(matches: list[tuple[str, int, str]], truncated: bool = False) -> str:
    """matches: (path, line, text)."""
    lines = ["No matches found"] if not matches else [f"Found {len(matches)} matches"]
    current = ""
    for path, line, text in matches:
        if current != path:
            if current:
                lines.append("")
            current = path
            lines.append(f"{path}:")
        lines.append(f"  Line {line}: {text}")
    if truncated:
        lines += ["", f"(Results are truncated: showing first {len(matches)} results. Consider using a more specific path or pattern.)"]
    return "\n".join(lines)


async def _timed(fn, what: str):
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn), DEFAULT_SEARCH_TIMEOUT_MS / 1000)
    except asyncio.TimeoutError:
        raise ToolError(f"Search timed out after {DEFAULT_SEARCH_TIMEOUT_MS // 1000} seconds. Consider using a more specific path or pattern.") from None


def make_glob(deps: ToolDeps) -> ToolInfo:
    async def execute(inp: GlobInput, ctx: ToolContext) -> ToolResult:
        search_path = None if inp.path in ("undefined", "null") else inp.path
        target = deps.access.resolve(search_path or ".", "directory")
        await deps.access.authorize_external([target], deps.invocation(ctx))
        await deps.assert_permission(ctx, GLOB_NAME, [inp.pattern], save=["*"], metadata={"root": search_path or ".", "path": search_path, "hidden": inp.hidden, "limit": inp.limit})
        p = Path(target.absolute)
        if not p.exists():
            raise ToolError(f"Search path does not exist: {search_path or '.'}")
        if not p.is_dir():
            raise ToolError(f"Search path is not a directory: {search_path or '.'}")
        limit = inp.limit or DEFAULT_SEARCH_LIMIT
        try:
            entries = await _timed(lambda: deps.ripgrep.glob(cwd=target.absolute, pattern=inp.pattern, hidden=bool(inp.hidden), limit=limit + 1), "glob")
        except (RipgrepError, OSError) as exc:
            raise ToolError(f"Unable to find files matching {inp.pattern}", exc) from None
        rel = [os.path.relpath(os.path.join(target.absolute, e.path), deps.location.directory).replace("\\", "/") for e in entries]
        truncated = len(rel) > limit
        shown = rel[:limit]
        absolute = [os.path.abspath(os.path.join(str(deps.location.directory), r)) for r in shown]
        return ToolResult(content=glob_model_content(absolute, truncated), output=[{"path": r, "type": "file"} for r in shown], metadata={"count": len(shown), "truncated": truncated})

    return ToolInfo(GLOB_NAME, GLOB_DESCRIPTION, GlobInput, execute)


def make_grep(deps: ToolDeps) -> ToolInfo:
    async def execute(inp: GrepInput, ctx: ToolContext) -> ToolResult:
        target = deps.access.resolve(inp.path or ".")
        await deps.access.authorize_external([target], deps.invocation(ctx))
        await deps.assert_permission(
            ctx, GREP_NAME, [inp.pattern], save=["*"],
            metadata={"root": ".", "path": inp.path, "include": inp.include, "literal": inp.literal, "caseSensitive": inp.caseSensitive, "limit": inp.limit},
        )
        root = Path(target.absolute)
        if not root.exists():
            raise ToolError(f"Search path does not exist: {inp.path or '.'}")
        cwd = str(root) if root.is_dir() else str(root.parent)
        limit = inp.limit or DEFAULT_SEARCH_LIMIT
        try:
            matches = await _timed(
                lambda: deps.ripgrep.grep(
                    cwd=cwd, pattern=inp.pattern, file=None if root.is_dir() else root.name, include=inp.include, literal=bool(inp.literal),
                    case_sensitive=inp.caseSensitive is not False, limit=limit + 1,
                ),
                "grep",
            )
        except InvalidPatternError as exc:
            raise ToolError(f"Invalid regex pattern: {exc.message}") from None
        except (RipgrepError, OSError) as exc:
            raise ToolError(f"Unable to grep for {inp.pattern}", exc) from None
        truncated = len(matches) > limit
        shown = matches[:limit]
        rows = [(os.path.abspath(os.path.join(cwd, m.entry.path)), m.line, m.text) for m in shown]
        out = [{"path": os.path.relpath(os.path.join(cwd, m.entry.path), deps.location.directory).replace("\\", "/"), "line": m.line, "text": m.text} for m in shown]
        return ToolResult(content=grep_model_content(rows, truncated), output=out, metadata={"matches": len(shown), "truncated": truncated})

    return ToolInfo(GREP_NAME, GREP_DESCRIPTION, GrepInput, execute)
