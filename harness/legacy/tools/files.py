"""read, write, edit, glob and grep."""

from __future__ import annotations

import difflib
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from harness.legacy.tools.base import MAX_BYTES, MAX_LINES, FileTime, Tool, ToolContext, ToolFailure
from harness.legacy.types import ToolResult

MAX_LINE_CHARS = 2000
SEARCH_LIMIT = 100
IGNORE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "dist", "build", ".next", ".nuxt", "target", ".gradle", ".idea", "coverage", ".cache", ".turbo",
}


# --------------------------------------------------------------------------- helpers


def read_text(path: Path) -> tuple[str, bool]:
    """(text, had_bom). Raises ToolFailure for binary files."""
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        raise ToolFailure(f"{path.name} looks like a binary file; this tool only handles text.")
    bom = data.startswith(b"\xef\xbb\xbf")
    return data[3:].decode("utf-8", "replace") if bom else data.decode("utf-8", "replace"), bom


def write_text(path: Path, text: str, bom: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" + data) if bom else data)


def unified(old: str, new: str, name: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{name}", f"b/{name}", n=3))


def diff_stats(old: str, new: str) -> tuple[int, int]:
    add = rem = 0
    for line in difflib.ndiff(old.splitlines(), new.splitlines()):
        if line.startswith("+ "):
            add += 1
        elif line.startswith("- "):
            rem += 1
    return add, rem


def similar_names(path: Path) -> list[str]:
    try:
        names = [p.name for p in path.parent.iterdir()]
    except OSError:
        return []
    return difflib.get_close_matches(path.name, names, n=3, cutoff=0.5)


def glob_regex(pattern: str) -> re.Pattern[str]:
    pattern = pattern.replace("\\", "/")
    out, i = "", 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
            continue
        if pattern.startswith("**", i):
            out += ".*"
            i += 2
            continue
        if c == "*":
            out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        elif c == "{":
            j = pattern.find("}", i)
            if j == -1:
                out += re.escape(c)
            else:
                out += "(?:" + "|".join(re.escape(p) for p in pattern[i + 1 : j].split(",")) + ")"
                i = j
        elif c == "[":
            j = pattern.find("]", i)
            if j == -1:
                out += re.escape(c)
            else:
                out += pattern[i : j + 1]
                i = j
        else:
            out += re.escape(c)
        i += 1
    return re.compile(out + r"\Z")


def glob_match(rel: str, pattern: str) -> bool:
    """Patterns without a slash match the file name at any depth, like ripgrep's --glob."""
    rx = glob_regex(pattern)
    return bool(rx.match(rel if "/" in pattern else rel.rsplit("/", 1)[-1]))


def list_files(base: Path, hidden: bool = False) -> list[Path]:
    """Files under base, honouring .gitignore inside a git repository and skipping dependency/build folders otherwise."""
    files: list[Path] = []
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=base, capture_output=True, timeout=30)
        if out.returncode == 0:
            for rel in out.stdout.decode("utf-8", "replace").split("\0"):
                if rel and (base / rel).is_file():
                    files.append(base / rel)
    except (OSError, subprocess.SubprocessError):
        out = None
    if not files and (out is None or out.returncode != 0):
        for dirpath, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            files.extend(Path(dirpath) / n for n in names)
    if not hidden:
        files = [f for f in files if not any(part.startswith(".") for part in f.relative_to(base).parts)]
    return [f for f in files if not any(p in IGNORE_DIRS for p in f.relative_to(base).parts)]


# --------------------------------------------------------------------------- read


class ReadTool(Tool):
    name = "read"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File or directory to read"},
            "offset": {"type": "integer", "description": "The line or directory entry to start reading from (1-based)"},
            "limit": {"type": "integer", "description": f"The maximum number of lines or directory entries to read (defaults to and capped at {MAX_LINES})"},
        },
        "required": ["path"],
    }

    def description(self, ctx: Any = None) -> str:
        return (
            "Read the contents of a file or directory. Each text line is prefixed by its 1-based line number as <line>: <content>; "
            "the prefix is not part of the file. Directory entries are returned one per line. Use offset and limit to read large files "
            "in sections. Prefer one larger read over many small slices, and use grep to find specific content in large files. "
            "Always read a file before you edit or overwrite it."
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = ctx.workspace.resolve(args["path"], ctx.cwd)
        await ctx.authorize_path(path, "directory" if path.is_dir() else "file")
        await ctx.permit("read", [ctx.workspace.display(path)])
        if not path.exists():
            tips = similar_names(path)
            raise ToolFailure(f"File not found: {args['path']}" + (f". Did you mean: {', '.join(str(path.parent / t) for t in tips)}?" if tips else ""))
        offset = max(1, int(args.get("offset") or 1))
        limit = min(MAX_LINES, max(1, int(args.get("limit") or MAX_LINES)))
        if path.is_dir():
            entries = sorted((e.name + ("/" if e.is_dir() else "") for e in path.iterdir()), key=str.lower)
            page = entries[offset - 1 : offset - 1 + limit]
            more = offset - 1 + limit < len(entries)
            tail = f"\n(Showing {len(page)} of {len(entries)} entries. Use offset={offset + limit} to continue.)" if more else f"\n({len(entries)} entries)"
            return ToolResult("\n".join(page) + tail, title=ctx.workspace.display(path), metadata={"kind": "directory"})
        text, _ = read_text(path)
        ctx.file_time.record(path)
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        total = len(lines)
        if offset > max(total, 1):
            raise ToolFailure(f"Offset {offset} is beyond the end of the file ({total} lines).")
        out: list[str] = []
        size, i = 0, offset - 1
        while i < total and len(out) < limit:
            line = lines[i] if len(lines[i]) <= MAX_LINE_CHARS else lines[i][:MAX_LINE_CHARS] + "... (line truncated)"
            size += len(line.encode("utf-8", "ignore")) + 8
            if size > MAX_BYTES:
                break
            out.append(f"{i + 1}: {line}")
            i += 1
        body = "\n".join(out)
        if i < total:
            body += f"\n\n(Showing lines {offset}-{i} of {total}. Use offset={i + 1} to continue.)"
        else:
            body += f"\n\n(End of file - {total} lines)"
        nearby = ctx.session.instructions.nearby(path) if getattr(ctx.session, "instructions", None) else ""
        if nearby:
            body += "\n\n" + nearby
        return ToolResult(body, title=ctx.workspace.display(path), metadata={"kind": "file", "lines": total})


# --------------------------------------------------------------------------- write


class WriteTool(Tool):
    name = "write"
    permission = "edit"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to write (created with its folders if missing)"},
            "content": {"type": "string", "description": "The complete new contents of the file"},
        },
        "required": ["path", "content"],
    }

    def description(self, ctx: Any = None) -> str:
        return (
            "Write a complete file, creating folders as needed. An existing file must have been read first and is replaced entirely. "
            "Prefer the edit tool for changing part of a file. Never create documentation files the user did not ask for."
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = ctx.workspace.resolve(args["path"], ctx.cwd)
        content = args["content"]
        await ctx.authorize_path(path)
        async with ctx.lock_for(path):
            old, bom = "", False
            if path.exists():
                if path.is_dir():
                    raise ToolFailure(f"{args['path']} is a directory.")
                ctx.file_time.assert_fresh(path)
                old, bom = read_text(path)
            await ctx.permit("edit", [ctx.workspace.display(path)], metadata={"diff": unified(old, content, path.name)})
            write_text(path, content, bom)
            ctx.file_time.record(path)
        add, rem = diff_stats(old, content)
        verb = "Overwrote" if old else "Created"
        return ToolResult(f"{verb} {ctx.workspace.display(path)} ({content.count(chr(10)) + 1} lines).", title=ctx.workspace.display(path),
                          metadata={"diff": unified(old, content, path.name), "added": add, "removed": rem, "path": str(path)})


# --------------------------------------------------------------------------- edit

_PUNCT = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"', "”": '"', "„": '"', "‟": '"',
                        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
                        " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", "　": " "})


def _norm(s: str) -> str:
    return s.translate(_PUNCT).rstrip()


def _line_spans(content: str) -> list[tuple[int, int, str]]:
    spans, pos = [], 0
    for raw in content.split("\n"):
        end = pos + len(raw)
        spans.append((pos, end, raw.rstrip("\r")))
        pos = end + 1
    return spans


def find_matches(content: str, search: str) -> list[tuple[int, int]]:
    """Exact matches first; if none, whole-line matches that ignore trailing whitespace, curly quotes, dashes and odd spaces."""
    found, i = [], 0
    while search and (i := content.find(search, i)) != -1:
        found.append((i, i + len(search)))
        i += len(search)
    if found:
        return found
    want = search.split("\n")
    trailing_nl = search.endswith("\n")
    if trailing_nl:
        want.pop()
    spans = _line_spans(content)
    out: list[tuple[int, int]] = []
    for idx in range(len(spans) - len(want) + 1):
        if all(_norm(spans[idx + k][2]) == _norm(want[k]) for k in range(len(want))):
            start, end = spans[idx][0], spans[idx + len(want) - 1][1]
            if trailing_nl:
                end = min(len(content), end + 1)
            if not out or start >= out[-1][1]:
                out.append((start, end))
    return out


class EditTool(Tool):
    name = "edit"
    permission = "edit"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to edit"},
            "oldString": {"type": "string", "description": "Exact text to find and replace"},
            "newString": {"type": "string", "description": "Text to replace oldString with (must differ from oldString)"},
            "replaceAll": {"type": "boolean", "description": "Replace every occurrence of oldString. When false, oldString must match exactly once. Defaults to false."},
        },
        "required": ["path", "oldString", "newString"],
    }

    def description(self, ctx: Any = None) -> str:
        return (
            "Replace exact text in an existing file. Read the file first. oldString must match once (include enough surrounding lines "
            "to make it unique) unless replaceAll is true. Keep indentation exactly as it is in the file. To create a new file use write."
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = ctx.workspace.resolve(args["path"], ctx.cwd)
        old, new = args["oldString"], args["newString"]
        if old == new:
            raise ToolFailure("oldString and newString are identical; nothing to change.")
        await ctx.authorize_path(path)
        async with ctx.lock_for(path):
            if not path.exists():
                if old == "":
                    await ctx.permit("edit", [ctx.workspace.display(path)])
                    write_text(path, new)
                    ctx.file_time.record(path)
                    return ToolResult(f"Created {ctx.workspace.display(path)}.", title=ctx.workspace.display(path), metadata={"diff": unified("", new, path.name)})
                raise ToolFailure(f"File not found: {args['path']}")
            if path.is_dir():
                raise ToolFailure(f"{args['path']} is a directory.")
            if old == "":
                raise ToolFailure("oldString is empty; use the write tool to replace a whole file.")
            ctx.file_time.assert_fresh(path)
            content, bom = read_text(path)
            crlf = content.count("\r\n") > content.count("\n") - content.count("\r\n")
            target = content.replace("\r\n", "\n") if crlf else content
            matches = find_matches(target, old.replace("\r\n", "\n"))
            if not matches:
                raise ToolFailure("Could not find oldString in the file. It must match exactly, including whitespace, indentation and line endings. Read the file again and copy the text.")
            if len(matches) > 1 and not args.get("replaceAll"):
                raise ToolFailure(f"Found {len(matches)} matches for oldString. Include more surrounding lines to make it unique, or set replaceAll to true.")
            replacement = new.replace("\r\n", "\n")
            updated, last = [], 0
            for s, e in matches:
                updated += [target[last:s], replacement]
                last = e
            updated.append(target[last:])
            result = "".join(updated)
            if crlf:
                result = result.replace("\n", "\r\n")
            diff = unified(content, result, path.name)
            await ctx.permit("edit", [ctx.workspace.display(path)], metadata={"diff": diff})
            write_text(path, result, bom)
            ctx.file_time.record(path)
        add, rem = diff_stats(content, result)
        return ToolResult(f"Edited {ctx.workspace.display(path)}: {len(matches)} replacement(s), +{add} -{rem} lines.", title=ctx.workspace.display(path),
                          metadata={"diff": diff, "replacements": len(matches), "added": add, "removed": rem, "path": str(path)})


# --------------------------------------------------------------------------- glob / grep


class GlobTool(Tool):
    name = "glob"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern to match files against, e.g. '**/*.py' or 'src/**/*.{ts,tsx}'"},
            "path": {"type": "string", "description": "Directory to search. Defaults to the current working directory."},
            "hidden": {"type": "boolean", "description": "Include hidden files and directories (default: false)."},
            "limit": {"type": "integer", "description": f"Maximum number of files to return (default: {SEARCH_LIMIT})"},
        },
        "required": ["pattern"],
    }

    def description(self, ctx: Any = None) -> str:
        return "Find files by glob pattern. Respects .gitignore. Results are newest first. Use this to locate files by name."

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        base = ctx.workspace.resolve(args.get("path") or ".", ctx.cwd)
        await ctx.authorize_path(base, "directory")
        await ctx.permit("glob", [args["pattern"]])
        if not base.is_dir():
            raise ToolFailure(f"Not a directory: {args.get('path')}")
        limit = int(args.get("limit") or SEARCH_LIMIT)
        hits = [f for f in list_files(base, bool(args.get("hidden"))) if glob_match(f.relative_to(base).as_posix(), args["pattern"])]
        hits.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        shown = [ctx.workspace.display(f) for f in hits[:limit]]
        text = "\n".join(shown) if shown else "No files found"
        if len(hits) > limit:
            text += f"\n\n(Results are truncated: showing first {limit} of {len(hits)}. Use a more specific path or pattern.)"
        return ToolResult(text, title=args["pattern"], metadata={"count": len(hits)})


class GrepTool(Tool):
    name = "grep"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regular expression or literal text to match in file contents."},
            "path": {"type": "string", "description": "File or directory to search. Defaults to the current working directory."},
            "include": {"type": "string", "description": 'Glob pattern to filter files (for example "*.js" or "*.{ts,tsx}")'},
            "literal": {"type": "boolean", "description": "Treat pattern as exact text instead of a regular expression (default: false)."},
            "caseSensitive": {"type": "boolean", "description": "Use case-sensitive matching (default: true)."},
            "limit": {"type": "integer", "description": f"Maximum number of matching lines to return (default: {SEARCH_LIMIT})"},
        },
        "required": ["pattern"],
    }

    def description(self, ctx: Any = None) -> str:
        return "Search file contents with a regular expression. Respects .gitignore. Returns file, line number and the matching line. Use glob to find files by name."

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        target = ctx.workspace.resolve(args.get("path") or ".", ctx.cwd)
        await ctx.authorize_path(target, "directory" if target.is_dir() else "file")
        await ctx.permit("grep", [args["pattern"]])
        if not target.exists():
            raise ToolFailure(f"Path not found: {args.get('path')}")
        pat = re.escape(args["pattern"]) if args.get("literal") else args["pattern"]
        try:
            rx = re.compile(pat, 0 if args.get("caseSensitive", True) else re.IGNORECASE)
        except re.error as exc:
            raise ToolFailure(f"Invalid regular expression: {exc}") from None
        limit = int(args.get("limit") or SEARCH_LIMIT)
        files = [target] if target.is_file() else list_files(target)
        if args.get("include"):
            base = target if target.is_dir() else target.parent
            files = [f for f in files if glob_match(f.relative_to(base).as_posix(), args["include"])]
        lines: list[str] = []
        count, current, truncated = 0, "", False
        for f in files:
            try:
                if f.stat().st_size > 2_000_000:
                    continue
                text, _ = read_text(f)
            except (OSError, ToolFailure):
                continue
            for n, line in enumerate(text.split("\n"), 1):
                if rx.search(line):
                    if count >= limit:
                        truncated = True
                        break
                    name = ctx.workspace.display(f)
                    if name != current:
                        if current:
                            lines.append("")
                        lines.append(f"{name}:")
                        current = name
                    lines.append(f"  Line {n}: {line.strip()[:400]}")
                    count += 1
            if truncated:
                break
        if not count:
            return ToolResult("No matches found", title=args["pattern"], metadata={"count": 0})
        head = f"Found {count} matches"
        tail = f"\n\n(Results are truncated: showing first {count} matches. Use a more specific path or pattern.)" if truncated else ""
        return ToolResult(head + "\n" + "\n".join(lines) + tail, title=args["pattern"], metadata={"count": count})
