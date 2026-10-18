"""apply_patch: edit several files in one call using opencode's stripped-down patch envelope."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.legacy.tools.base import Tool, ToolContext, ToolFailure
from harness.legacy.tools.files import read_text, unified, write_text
from harness.legacy.types import ToolResult

DESCRIPTION = """Edit files with a patch. Use it when one change spans several files or several places.

*** Begin Patch
[ one or more file sections ]
*** End Patch

Each section starts with one of:
*** Add File: <path> - create a file; every following line starts with +
*** Delete File: <path> - remove a file; nothing follows
*** Update File: <path> - change a file in place; optionally followed by *** Move to: <new path>

Inside an Update section, each change hunk starts with @@ (optionally followed by a line such as a function or class header
for context), then lines starting with ' ' (unchanged context), '-' (removed) or '+' (added). Show about 3 lines of context
above and below each change, and enough to make the location unique. Paths are relative to the working directory.

Example:
*** Begin Patch
*** Add File: hello.txt
+Hello world
*** Update File: src/app.py
@@ def greet():
-print("Hi")
+print("Hello, world!")
*** Delete File: obsolete.txt
*** End Patch"""


@dataclass
class Hunk:
    context: str = ""
    lines: list[tuple[str, str]] = field(default_factory=list)  # (' ' | '-' | '+', text)
    eof: bool = False


@dataclass
class FileOp:
    kind: str  # add | delete | update
    path: str
    move_to: str = ""
    content: list[str] = field(default_factory=list)
    hunks: list[Hunk] = field(default_factory=list)


def parse_patch(text: str) -> list[FileOp]:
    lines = text.strip("\n").split("\n")
    if not lines or lines[0].strip() != "*** Begin Patch":
        raise ToolFailure("Patch must start with '*** Begin Patch'.")
    if lines[-1].strip() != "*** End Patch":
        raise ToolFailure("Patch must end with '*** End Patch'.")
    ops: list[FileOp] = []
    i = 1
    while i < len(lines) - 1:
        line = lines[i]
        if line.startswith("*** Add File: "):
            op = FileOp("add", line[len("*** Add File: "):].strip())
            i += 1
            while i < len(lines) - 1 and not lines[i].startswith("*** "):
                if not lines[i].startswith("+"):
                    raise ToolFailure(f"In Add File {op.path}, every line must start with '+': {lines[i][:60]!r}")
                op.content.append(lines[i][1:])
                i += 1
            ops.append(op)
        elif line.startswith("*** Delete File: "):
            ops.append(FileOp("delete", line[len("*** Delete File: "):].strip()))
            i += 1
        elif line.startswith("*** Update File: "):
            op = FileOp("update", line[len("*** Update File: "):].strip())
            i += 1
            if i < len(lines) - 1 and lines[i].startswith("*** Move to: "):
                op.move_to = lines[i][len("*** Move to: "):].strip()
                i += 1
            hunk: Hunk | None = None
            while i < len(lines) - 1 and not (lines[i].startswith("*** ") and not lines[i].startswith("*** End of File")):
                cur = lines[i]
                if cur.startswith("@@"):
                    hunk = Hunk(context=cur[2:].strip())
                    op.hunks.append(hunk)
                elif cur.startswith("*** End of File"):
                    if hunk:
                        hunk.eof = True
                elif cur[:1] in (" ", "-", "+") or cur == "":
                    if hunk is None:
                        hunk = Hunk()
                        op.hunks.append(hunk)
                    hunk.lines.append((cur[:1] or " ", cur[1:]))
                else:
                    raise ToolFailure(f"Unexpected line in Update File {op.path}: {cur[:60]!r}")
                i += 1
            ops.append(op)
        elif line.strip() == "":
            i += 1
        else:
            raise ToolFailure(f"Unexpected line in patch: {line[:60]!r}")
    if not ops:
        raise ToolFailure("The patch contains no file operations.")
    return ops


def _seek(hay: list[str], needle: list[str], start: int, eof: bool) -> int:
    """Index where needle occurs in hay at or after start; exact, then trailing-space, then fully stripped comparison."""
    if not needle:
        return len(hay) if eof else start
    last = len(hay) - len(needle)
    candidates = range(max(0, last) if eof else start, last + 1)
    for norm in (lambda s: s, lambda s: s.rstrip(), lambda s: s.strip()):
        for k in candidates:
            if all(norm(hay[k + j]) == norm(needle[j]) for j in range(len(needle))):
                return k
    return -1


def apply_hunks(original: str, hunks: list[Hunk], path: str) -> str:
    text = original.replace("\r\n", "\n")
    lines = text.split("\n")
    trailing = lines and lines[-1] == ""
    if trailing:
        lines.pop()
    pos = 0
    for h in hunks:
        if h.context:
            ctx_at = _seek(lines, [h.context], pos, False)
            if ctx_at != -1:
                pos = ctx_at + 1
        old = [t for k, t in h.lines if k in (" ", "-")]
        new = [t for k, t in h.lines if k in (" ", "+")]
        at = _seek(lines, old, pos, h.eof)
        if at == -1:
            raise ToolFailure(f"Could not find the expected lines in {path}:\n" + "\n".join(old[:6]))
        lines[at : at + len(old)] = new
        pos = at + len(new)
    out = "\n".join(lines) + ("\n" if trailing or not original else "")
    return out.replace("\n", "\r\n") if "\r\n" in original else out


class PatchTool(Tool):
    name = "patch"
    permission = "edit"
    parameters = {
        "type": "object",
        "properties": {"patch": {"type": "string", "description": "The full patch text, from *** Begin Patch to *** End Patch"}},
        "required": ["patch"],
    }

    def description(self, ctx: Any = None) -> str:
        return DESCRIPTION

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        ops = parse_patch(args["patch"])
        planned: list[tuple[FileOp, Path, str | None, str | None, Path | None]] = []  # op, path, old, new, dest
        for op in ops:
            path = ctx.workspace.resolve(op.path, ctx.cwd)
            await ctx.authorize_path(path)
            if op.kind == "add":
                if path.exists():
                    raise ToolFailure(f"Cannot add {op.path}: it already exists.")
                planned.append((op, path, None, "\n".join(op.content) + "\n", None))
            elif op.kind == "delete":
                if not path.exists():
                    raise ToolFailure(f"Cannot delete {op.path}: it does not exist.")
                ctx.file_time.assert_fresh(path)
                planned.append((op, path, read_text(path)[0], None, None))
            else:
                if not path.exists():
                    raise ToolFailure(f"Cannot update {op.path}: it does not exist.")
                ctx.file_time.assert_fresh(path)
                old, _ = read_text(path)
                dest = ctx.workspace.resolve(op.move_to, ctx.cwd) if op.move_to else None
                if dest:
                    await ctx.authorize_path(dest)
                planned.append((op, path, old, apply_hunks(old, op.hunks, op.path), dest))
        diff = "".join(unified(old or "", new or "", ctx.workspace.display(p)) for _, p, old, new, _ in planned)
        await ctx.permit("edit", [ctx.workspace.display(p) for _, p, *_ in planned], metadata={"diff": diff})
        report: list[str] = []
        for op, path, old, new, dest in planned:  # everything parsed and matched above, so applying is all-or-nothing in practice
            if op.kind == "add":
                write_text(path, new or "")
                ctx.file_time.record(path)
                report.append(f"A {ctx.workspace.display(path)}")
            elif op.kind == "delete":
                path.unlink()
                report.append(f"D {ctx.workspace.display(path)}")
            else:
                target = dest or path
                write_text(target, new or "")
                if dest and dest != path:
                    path.unlink()
                ctx.file_time.record(target)
                report.append(f"M {ctx.workspace.display(path)}" + (f" -> {ctx.workspace.display(target)}" if dest else ""))
        return ToolResult("Patch applied:\n" + "\n".join(report), title=f"{len(ops)} file(s)", metadata={"diff": diff})
