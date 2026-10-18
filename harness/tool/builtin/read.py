"""The read tool (opencode: tool/plugin/read.ts and tool/read-filesystem.ts)."""

from __future__ import annotations

import base64
import mimetypes
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel, Field

from harness.file_access import Target
from harness.schema.message import FileContent, TextContent
from harness.tool.builtin.deps import ToolDeps
from harness.tool.info import ToolContext, ToolError, ToolInfo, ToolResult
from harness.util import fs

NAME = "read"
MAX_READ_LINES = 2_000
MAX_READ_BYTES = 50 * 1024
MAX_MEDIA_INGEST_BYTES = 20 * 1024 * 1024
MAX_LINE_LENGTH = 2_000
MAX_LINE_SUFFIX = f"... (line truncated to {MAX_LINE_LENGTH} chars)"
MEDIA_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}
FILENAME = "AGENTS.md"

DESCRIPTION = (
    "Read the contents of a file or directory. Supports text files, images, and PDFs. Images and PDFs are presented directly to the model. "
    "Each text line is prefixed by its 1-based line number as <line>: <content>. The prefix is for reference and is not part of the file content. "
    "Directory entries are returned one per line. Use offset and limit to read large files or directories in sections. Prefer one larger read "
    "over many small slices, and use grep to find specific content in large files."
)


class Input(BaseModel):
    path: str = Field(description="File or directory to read")
    offset: Optional[int] = Field(default=None, ge=0, description="The line or directory entry to start reading from (1-based)")
    limit: Optional[int] = Field(default=None, ge=0, description=f"The maximum number of lines or directory entries to read (defaults to and capped at {MAX_READ_LINES})")


class ReadFailure(Exception):
    """A read failed in a way whose message is meant for the model."""


@dataclass
class FileOut:
    type: str  # "file"
    uri: str
    name: str
    content: str
    encoding: str  # utf8 | base64
    mime: str


@dataclass
class TextPage:
    type: str
    content: str
    mime: str
    offset: int
    truncated: bool
    next: Optional[int] = None


@dataclass
class ListPage:
    type: str
    entries: list[dict[str, str]]
    truncated: bool
    next: Optional[int] = None


def detect_media(head: bytes) -> str:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    return ""


def _clamp(line: str) -> str:
    return line[:MAX_LINE_LENGTH] + MAX_LINE_SUFFIX if len(line) > MAX_LINE_LENGTH else line


def _mime(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _list_page(directory: str, page_offset: Optional[int], page_limit: Optional[int]) -> ListPage:
    offset = page_offset or 1
    limit = min(page_limit or MAX_READ_LINES, MAX_READ_LINES)
    items = []
    for entry in os.scandir(directory):
        if entry.is_symlink():
            kind = "symlink"  # listed unresolved, including broken and escaping links
        elif entry.is_dir():
            kind = "directory"
        elif entry.is_file():
            kind = "file"
        else:
            continue
        items.append({"path": entry.name + ("/" if kind == "directory" else ""), "type": kind})
    items.sort(key=lambda e: (e["type"] != "directory", e["path"].lower()))
    selected = items[offset - 1 : offset - 1 + limit]
    truncated = offset - 1 + len(selected) < len(items)
    return ListPage("list-page", selected, truncated, offset + len(selected) if truncated else None)


def read_target(absolute: str, resource: str, offset: Optional[int] = None, limit: Optional[int] = None) -> Union[FileOut, TextPage, ListPage]:
    p = Path(absolute)
    if p.is_dir():
        return _list_page(absolute, offset, limit)
    if not p.exists():
        raise FileNotFoundError(absolute)
    data = p.read_bytes()
    media = detect_media(data[:16])
    if media in MEDIA_MIMES:
        if len(data) > MAX_MEDIA_INGEST_BYTES:
            raise ReadFailure(f"Media exceeds {MAX_MEDIA_INGEST_BYTES} byte ingestion limit: {resource}")
        return FileOut("file", p.as_uri(), p.name, base64.b64encode(data).decode(), "base64", media)
    paged = len(data) > MAX_READ_BYTES or offset is not None or limit is not None
    if not paged:
        if b"\x00" in data:
            raise ReadFailure(f"Cannot read binary file: {resource}")
        return FileOut("file", p.as_uri(), p.name, "\n".join(_clamp(l) for l in data.decode("utf-8", "replace").split("\n")), "utf8", _mime(absolute))
    # paged text
    start = offset or 1
    cap = min(limit or MAX_READ_LINES, MAX_READ_LINES)
    split = data.decode("utf-8", "replace").split("\n")
    available = [l[:-1] if l.endswith("\r") else l for l in (split[:-1] if split and split[-1] == "" else split)]
    entries: list[str] = []
    size = 0
    nxt: Optional[int] = None
    for index, value in enumerate(available[start - 1 :]):
        line_no = start + index
        if len(entries) >= cap or size >= MAX_READ_BYTES:
            nxt = line_no
            break
        text = _clamp(value)
        line_size = len(text.encode("utf-8")) + (1 if entries else 0)
        if size + line_size > MAX_READ_BYTES:
            nxt = line_no
            break
        entries.append(text)
        size += line_size
    if nxt is None and len(entries) >= cap and start - 1 + len(entries) < len(available):
        nxt = start + len(entries)
    consumed_lines = len(available) if nxt is None else nxt - 1
    consumed = data
    if consumed_lines:
        count, pos = 0, 0
        while count < consumed_lines and (i := data.find(b"\n", pos)) != -1:
            count += 1
            pos = i + 1
        consumed = data[:pos] if count == consumed_lines else data
    else:
        consumed = b""
    if b"\x00" in consumed:
        raise ReadFailure(f"Cannot read binary file: {resource}")
    if not entries and start != 1:
        n = len(available)
        raise ReadFailure(f"Offset {start} is out of range for this file ({n} {'line' if n == 1 else 'lines'})")
    return TextPage("text-page", "\n".join(entries), _mime(absolute), start, nxt is not None, nxt)


def to_model_content(path: str, offset: Optional[int], out: Union[FileOut, TextPage, ListPage]) -> Union[str, list]:
    if isinstance(out, FileOut) and out.encoding == "base64":
        return [
            TextContent(text="PDF read successfully" if out.mime == "application/pdf" else "Image read successfully"),
            FileContent(uri=f"data:{out.mime};base64,{out.content}", mime=out.mime, name=path),
        ]
    if isinstance(out, ListPage):
        start = offset or 1
        content = [f"Read directory {path}, 0 entries" if not out.entries else f"Read directory {path}, entries {start}-{start + len(out.entries) - 1}"]
        content += [e["path"] for e in out.entries]
        if out.truncated and out.next is not None:
            content.append(f"[Output truncated. Continue reading with offset: {out.next}]")
        return "\n".join(content)
    start = out.offset if isinstance(out, TextPage) else 1
    text = out.content[:-1] if isinstance(out, FileOut) and out.content.endswith("\n") else out.content  # a page's trailing newline is a selected blank line
    lines = [] if out.content == "" else text.split("\n")
    content = [f"Read file {path}, 0 lines" if not lines else f"Read file {path}, lines {start}-{start + len(lines) - 1}"]
    content += [f"{start + i}: {l}" for i, l in enumerate(lines)]
    if isinstance(out, TextPage) and out.truncated and out.next is not None:
        content.append(f"[Output truncated. Continue reading with offset: {out.next}]")
    return "\n".join(content)


def _canonical(name: str) -> str:
    return unicodedata.normalize("NFC", name).replace(" ", " ").replace(" ", " ").replace("‘", "'").replace("’", "'")


def alternate_path(absolute: str) -> Optional[str]:
    """A file in the same folder whose name differs only in unicode normalization, non-breaking spaces or curly quotes."""
    base = _canonical(os.path.basename(absolute))
    try:
        matches = [e.name for e in os.scandir(os.path.dirname(absolute)) if e.is_file() and _canonical(e.name) == base]
    except OSError:
        return None
    return os.path.join(os.path.dirname(absolute), matches[0]) if len(matches) == 1 else None


def missing(input_path: str, absolute: str) -> ToolError:
    base = os.path.basename(input_path).lower()
    try:
        suggestions = [os.path.join(os.path.dirname(input_path), e) for e in os.listdir(os.path.dirname(absolute)) if (e.lower() in base or base in e.lower())][:3]
    except OSError:
        suggestions = []
    msg = f"File not found: {input_path}"
    return ToolError(msg if not suggestions else f"{msg}\n\nDid you mean one of these?\n" + "\n".join(suggestions))


def make(deps: ToolDeps) -> ToolInfo:
    async def execute(inp: Input, ctx: ToolContext) -> ToolResult:
        requested = await deps.access.authorize_read(inp.path, deps.invocation(ctx))
        shown_path, target = inp.path, requested
        try:
            out = read_target(target.absolute, target.resource, inp.offset, inp.limit)
        except FileNotFoundError:
            alt = alternate_path(requested.absolute)
            if not alt:
                raise missing(inp.path, requested.absolute) from None
            target = await deps.access.authorize_read(alt, deps.invocation(ctx), sibling_of=requested)
            try:
                out = read_target(target.absolute, target.resource, inp.offset, inp.limit)
            except FileNotFoundError:
                raise missing(inp.path, requested.absolute) from None
            if isinstance(out, ListPage):
                raise missing(inp.path, requested.absolute)
            shown_path = os.path.join(os.path.dirname(inp.path), os.path.basename(alt))
        except ReadFailure as exc:
            raise ToolError(str(exc)) from None
        except OSError as exc:
            raise ToolError(f"Unable to read {inp.path}", exc) from None

        # After a successful read, discover nearby AGENTS.md walking up to the Location root (exclusive) and inject them as durable
        # synthetic instructions. For a directory listing the walk starts at the directory itself; for a file at its dirname.
        # External reads are skipped, and discovery failures never fail the read.
        try:
            if target.external_directory is None:
                resolved = str(fs.resolve(target.absolute))
                root = str(fs.resolve(deps.location.directory))
                start = resolved if isinstance(out, ListPage) else os.path.dirname(resolved)
                found = fs.up([FILENAME], start, root, type="file")
                candidates = [str(fs.resolve(f)) for f in found]
                candidates = [f for f in candidates if not fs.contains(os.path.dirname(f), root) and f != resolved]
                if candidates:
                    deps.instructions.load(ctx.session_id, candidates)
        except Exception:  # noqa: BLE001
            pass
        return ToolResult(content=to_model_content(shown_path, inp.offset, out), output=out, metadata={"truncated": False if isinstance(out, FileOut) else out.truncated})

    return ToolInfo(NAME, DESCRIPTION, Input, execute)
