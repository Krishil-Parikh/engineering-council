"""The patch envelope: parsing and applying (opencode: packages/util/src/patch.ts)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Union

from harness.util import bom as Bom


class ParseError(Exception):
    """A patch that cannot be parsed; str() is the message shown to the model."""


class BoundaryError(ParseError):
    def __init__(self, boundary: str) -> None:
        self.boundary = boundary
        super().__init__(f"The {boundary} line of the patch must be '{'*** Begin Patch' if boundary == 'first' else '*** End Patch'}'")


class InvalidHunkError(ParseError):
    def __init__(self, line: str, line_number: int, reason: Optional[str] = None) -> None:
        self.line, self.line_number, self.reason = line, line_number, reason
        if reason:
            msg = f"Invalid hunk at line {line_number}: {reason}"
        else:
            msg = (
                f"Invalid hunk at line {line_number}: '{line}' is not a valid hunk header. "
                "Valid hunk headers: '*** Add File: {path}', '*** Delete File: {path}', '*** Update File: {path}'"
            )
        super().__init__(msg)


@dataclass
class Chunk:
    old_lines: list[str] = field(default_factory=list)
    new_lines: list[str] = field(default_factory=list)
    change_context: Optional[str] = None
    end_of_file: bool = False


@dataclass
class Add:
    path: str
    contents: str
    type: str = "add"


@dataclass
class Delete:
    path: str
    type: str = "delete"


@dataclass
class Update:
    path: str
    chunks: list[Chunk]
    move_path: Optional[str] = None
    type: str = "update"


Hunk = Union[Add, Delete, Update]


@dataclass
class FileUpdate:
    content: str
    bom: bool


_HEREDOC = re.compile(r"^(?:cat\s+)?<<(['\"]?)(\w+)\1\s*\n([\s\S]*?)\n\2\s*$")


def _strip_heredoc(text: str) -> str:
    m = _HEREDOC.match(text)
    return m.group(3) if m else text


def _is_boundary(line: str) -> bool:
    return line == "*** End Patch" or line.startswith(("*** Add File: ", "*** Delete File: ", "*** Update File: "))


def _at(lines: list[str], i: int) -> Optional[str]:
    return lines[i] if 0 <= i < len(lines) else None


def parse(patch_text: str) -> list[Hunk]:
    """Raises ParseError."""
    lines = [l[:-1] if l.endswith("\r") else l for l in _strip_heredoc(patch_text.strip()).split("\n")]
    begin = 0 if lines[0].strip() == "*** Begin Patch" else -1
    end = len(lines) - 1 if lines[-1].strip() == "*** End Patch" else -1
    if begin == -1:
        raise BoundaryError("first")
    if end == -1 or begin >= end:
        raise BoundaryError("last")
    hunks: list[Hunk] = []
    index = begin + 1
    while index < end:
        header = lines[index].strip()
        if index == begin + 1 and header.startswith("*** Environment ID:") and header[len("*** Environment ID:") :].strip():
            index += 1
            continue
        if header.startswith("*** Add File: "):
            path = header[len("*** Add File: ") :].strip()
            contents, index = _parse_add(lines, index + 1, end, path)
            hunks.append(Add(path, contents))
            continue
        if header.startswith("*** Delete File: "):
            path = header[len("*** Delete File: ") :].strip()
            nxt = _at(lines, index + 1)
            nxt = nxt.strip() if nxt is not None else None
            if index + 1 < end and nxt is not None and not _is_boundary(nxt):
                if nxt.startswith("*** "):
                    raise InvalidHunkError(nxt, index + 2)
                raise InvalidHunkError(nxt, index + 2, f"Unexpected line after Delete File '{path}': '{nxt}'. Delete hunks do not contain body lines")
            hunks.append(Delete(path))
            index += 1
            continue
        if header.startswith("*** Update File: "):
            path = header[len("*** Update File: ") :].strip()
            nxt = index + 1
            move_path: Optional[str] = None
            while (cur := _at(lines, nxt)) is not None and cur.rstrip() == "*** End of File":
                nxt += 1
            move = _at(lines, nxt)
            move = move.rstrip() if move is not None else None
            if move is not None and (move == "*** Move to:" or move.startswith("*** Move to: ")):
                move_path = move[len("*** Move to: ") :].strip()
                if not move_path:
                    raise InvalidHunkError(lines[nxt].strip(), nxt + 1, f"Move destination for '{path}' must not be empty")
                nxt += 1
            chunks, index = _parse_update(lines, nxt, end, path, index)
            hunks.append(Update(path, chunks, move_path))
            continue
        raise InvalidHunkError(header, index + 1)
    return hunks


def derive(path: str, chunks: list[Chunk], original: str) -> FileUpdate:
    """Raises ValueError when a chunk cannot be located."""
    source = Bom.split(original)
    lines = source.text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for start, remove, insert in reversed(_compute_replacements(lines, path, chunks)):
        lines[start : start + remove] = insert
    if not lines or lines[-1] != "":
        lines.append("")
    nxt = Bom.split("\n".join(lines))
    return FileUpdate(nxt.text, source.bom or nxt.bom)


def join_bom(text: str, bom: bool) -> str:
    return Bom.join(text, bom)


def _parse_add(lines: list[str], start: int, end: int, path: str) -> tuple[str, int]:
    content: list[str] = []
    index = start
    while index < end and not _is_boundary(lines[index].strip()):
        if not lines[index].startswith("+"):
            line = lines[index].strip()
            raise InvalidHunkError(line, index + 1, f"Invalid Add File line for '{path}': expected a line starting with '+', got '{line}'")
        content.append(lines[index][1:])
        index += 1
    return "\n".join(content), index


_UNEXPECTED = "Unexpected line found in update hunk: '{}'. Every line should start with ' ' (context line), '+' (added line), or '-' (removed line)"


def _parse_update(lines: list[str], start: int, end: int, path: str, hunk: int) -> tuple[list[Chunk], int]:
    chunks: list[Chunk] = []
    index = start
    after_eof = False
    while index < end:
        line = lines[index]
        update_line = line.rstrip()
        if after_eof:
            if update_line == "":
                index += 1
                continue
            if update_line == "@@" or update_line.startswith("@@ "):
                after_eof = False
            elif _is_boundary(update_line):
                break
            else:
                raise InvalidHunkError(line, index + 1, f"Expected update hunk to start with a @@ context marker, got: '{line}'")
        if update_line == "*** End of File":
            chunk = chunks[-1] if chunks else None
            if chunk and not chunk.old_lines and not chunk.new_lines:
                raise InvalidHunkError(update_line, index + 1, "Update hunk does not contain any lines")
            if chunk:
                chunk.end_of_file = True
                after_eof = True
            index += 1
            continue
        if _is_boundary(update_line):
            break
        if update_line == "@@" or update_line.startswith("@@ "):
            prev = chunks[-1] if chunks else None
            if prev and not prev.old_lines and not prev.new_lines:
                raise InvalidHunkError(line, index + 1, _UNEXPECTED.format(line))
            chunks.append(Chunk(change_context=None if update_line == "@@" else update_line[3:]))
            index += 1
            continue
        if not chunks:
            chunks.append(Chunk())
        chunk = chunks[-1]
        if line == "":
            chunk.old_lines.append("")
            chunk.new_lines.append("")
        elif line.startswith(" "):
            chunk.old_lines.append(line[1:])
            chunk.new_lines.append(line[1:])
        elif line.startswith("-"):
            chunk.old_lines.append(line[1:])
        elif line.startswith("+"):
            chunk.new_lines.append(line[1:])
        else:
            populated = bool(chunk.old_lines or chunk.new_lines)
            raise InvalidHunkError(
                line, index + 1,
                f"Expected update hunk to start with a @@ context marker, got: '{line}'" if populated else _UNEXPECTED.format(line),
            )
        index += 1
    if not chunks:
        raise InvalidHunkError(lines[hunk].strip(), hunk + 1, f"Update file hunk for path '{path}' is empty")
    last = chunks[-1]
    if not last.old_lines and not last.new_lines:
        line = lines[index].strip() if index < len(lines) else ""
        raise InvalidHunkError(line, index + 1, "Update hunk does not contain any lines" if line == "*** End Patch" else _UNEXPECTED.format(line))
    return chunks, index


def _compute_replacements(lines: list[str], path: str, chunks: list[Chunk]) -> list[tuple[int, int, list[str]]]:
    replacements: list[tuple[int, int, list[str]]] = []
    line_index = 0
    for chunk in chunks:
        if chunk.change_context:
            ctx = _seek(lines, [chunk.change_context], line_index)
            if ctx == -1:
                raise ValueError(f"Failed to find context '{chunk.change_context}' in {path}")
            line_index = ctx + 1
        if not chunk.old_lines:
            replacements.append((len(lines), 0, chunk.new_lines))
            continue
        old, new = chunk.old_lines, chunk.new_lines
        found = _seek(lines, old, line_index, chunk.end_of_file)
        if found == -1 and old[-1] == "":
            old = old[:-1]
            if new and new[-1] == "":
                new = new[:-1]
            found = _seek(lines, old, line_index, chunk.end_of_file)
        if found == -1 and all(l == "" for l in chunk.old_lines):
            n = len(chunk.old_lines)
            raise ValueError(f"Failed to find {'an expected blank line' if n == 1 else f'{n} consecutive blank lines'} in {path}")
        if found == -1:
            raise ValueError(f"Failed to find expected lines in {path}:\n" + "\n".join(chunk.old_lines))
        replacements.append((found, len(old), new))
        line_index = found + len(old)
    return sorted(replacements, key=lambda r: r[0])


_NORM = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"', "”": '"', "„": '"', "‟": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", " ": " ", " ": " ", "　": " ",
})
# JS String.trim strips Unicode whitespace; Python's str.strip does the same set closely enough for source text.
_COMPARES: list[Callable[[str, str], bool]] = [
    lambda a, b: a == b,
    lambda a, b: a.rstrip() == b.rstrip(),
    lambda a, b: a.strip() == b.strip(),
    lambda a, b: a.strip().translate(_NORM) == b.strip().translate(_NORM),
]


def _matches(lines: list[str], pattern: list[str], offset: int, compare: Callable[[str, str], bool]) -> bool:
    return all(compare(lines[offset + i], p) for i, p in enumerate(pattern))


def _seek(lines: list[str], pattern: list[str], start: int, eof: bool = False) -> int:
    if not pattern:
        return -1
    if eof:
        offset = len(lines) - len(pattern)
        if offset < start:
            return -1
        return offset if any(_matches(lines, pattern, offset, c) for c in _COMPARES) else -1
    for compare in _COMPARES:
        for offset in range(start, len(lines) - len(pattern) + 1):
            if _matches(lines, pattern, offset, compare):
                return offset
    return -1
