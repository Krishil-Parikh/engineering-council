"""The edit tool (opencode: tool/plugin/edit.ts).

Replaces exact text. Matching is done against the LF view that `read` shows the model and offsets are mapped back to the source,
so CRLF and mixed line endings neither block a match nor leak into untouched regions. If there is no exact match it retries
ignoring typographic quote/dash/space variants (a one-to-one character mapping, so offsets survive), then trailing whitespace on
each line. A replacement keeps the line endings of the region it replaces."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from typing import Callable, Optional

from pydantic import BaseModel, Field

from harness import file_mutation as FM
from harness.file_access import resolve_path
from harness.tool.builtin.deps import ToolDeps
from harness.tool.file_diff import file_diff
from harness.tool.info import ToolContext, ToolError, ToolInfo, ToolOptions, ToolResult
from harness.util import bom as Bom

NAME = "edit"
CRLF = "\r\n"

DESCRIPTION = (
    "Edit the contents of a file by finding and replacing exact text. When editing text from Read output, preserve the exact indentation "
    "(tabs or spaces) and omit the line-number prefix, such as `1: `. Never include the prefix in oldString or newString. Write line breaks as \\n; "
    "the file's existing CRLF or LF line endings are matched and preserved. To change line endings themselves, make oldString and newString differ only "
    "in \\r; that edit applies to the exact bytes. If there is no exact match, the edit retries while ignoring typographic quote, dash, and space "
    "variants, then trailing whitespace on each line. The edit fails if oldString is not found. By default, oldString must identify a UNIQUE location. "
    "Multiple matches FAIL unless replaceAll is true. Add more surrounding context to disambiguate, or set replaceAll to true to replace every "
    "occurrence. Use replaceAll when the change should apply to every occurrence, such as renaming a variable."
)


class Input(BaseModel):
    path: str = Field(description="File to edit")
    oldString: str = Field(description="Exact text to find and replace")
    newString: str = Field(description="Text to replace oldString with (must differ from oldString)")
    replaceAll: Optional[bool] = Field(default=None, description="Whether to replace every occurrence of oldString. When false, oldString must match exactly once. Defaults to false.")


@dataclass
class Match:
    start: int
    end: int


_NORMALIZE = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"', "”": '"', "„": '"', "‟": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", "　": " ",
})


def normalize_for_match(value: str) -> str:
    return value.translate(_NORMALIZE)


def find_occurrences(content: str, search: str) -> list[Match]:
    out: list[Match] = []
    if not search:
        return out
    offset = 0
    while (i := content.find(search, offset)) != -1:
        out.append(Match(i, i + len(search)))
        offset = i + len(search)
    return out


def find_line_occurrences(content: str, search: str) -> list[Match]:
    """Whole-line matches that ignore trailing whitespace (and typographic variants)."""
    trailing_newline = search.endswith("\n")
    expected = search.split("\n")
    if trailing_newline:
        expected.pop()
    lines = []
    for m in re.finditer(r"[^\n]*(?:\n|$)", content):
        if m.group(0) == "":
            continue
        newline = m.group(0).endswith("\n")
        text = m.group(0)[:-1] if newline else m.group(0)
        lines.append({"start": m.start(), "end": m.start() + len(m.group(0)), "text": text, "content_end": m.start() + len(text) - (1 if text.endswith("\r") else 0), "newline": newline})
    candidates: list[Match] = []
    for index in range(len(lines)):
        actual = lines[index : index + len(expected)]
        if len(actual) != len(expected):
            continue
        if not all(normalize_for_match(a["text"].rstrip()) == normalize_for_match(e.rstrip()) for a, e in zip(actual, expected)):
            continue
        last = actual[-1]
        if trailing_newline and not last["newline"]:
            continue
        candidates.append(Match(lines[index]["start"], last["end"] if trailing_newline else last["content_end"]))
    result: list[Match] = []
    for c in candidates:
        if any(m.end > c.start and m.start < c.end for m in result):
            continue
        result.append(c)
    return result


def line_ending(text: str, fallback: str) -> str:
    """The dominant line ending in text, or fallback when there is none."""
    crlf_count = text.count(CRLF)
    lf_count = text.count("\n") - crlf_count
    if crlf_count == lf_count:
        return fallback
    return CRLF if crlf_count > lf_count else "\n"


def align_lines(before: list[str], after: list[str]) -> list[Optional[int]]:
    """For each line of `after`, the index of the `before` line it keeps (longest common subsequence) or, between kept lines, the line it takes the place of."""
    width = len(after) + 1
    table = [0] * ((len(before) + 1) * width)
    for i in range(len(before) - 1, -1, -1):
        for j in range(len(after) - 1, -1, -1):
            table[i * width + j] = table[(i + 1) * width + j + 1] + 1 if before[i] == after[j] else max(table[(i + 1) * width + j], table[i * width + j + 1])
    result: list[Optional[int]] = [None] * len(after)
    gap_before: list[int] = []
    gap_after: list[int] = []

    def flush() -> None:
        for k, j in enumerate(gap_after):
            result[j] = gap_before[k] if k < len(gap_before) else None
        gap_before.clear()
        gap_after.clear()

    i = j = 0
    while i < len(before) and j < len(after):
        if before[i] == after[j]:
            flush()
            result[j] = i
            i += 1
            j += 1
            continue
        if table[(i + 1) * width + j] >= table[i * width + j + 1]:
            gap_before.append(i)
            i += 1
        else:
            gap_after.append(j)
            j += 1
    while i < len(before):
        gap_before.append(i)
        i += 1
    while j < len(after):
        gap_after.append(j)
        j += 1
    flush()
    return result


def with_region_endings(region: str, replacement: str, fallback: str) -> str:
    """Joins the replacement's lines with line endings taken from the matched source region: a replacement line that keeps a region line reuses
    that line's ending; a line that changes in place reuses the ending of the line it replaces; only lines beyond those take `fallback`."""
    before = re.split(r"\r?\n", region)
    endings = re.findall(r"\r?\n", region)
    after = replacement.split("\n")
    key = lambda line: normalize_for_match(line.rstrip())  # noqa: E731
    source = align_lines([key(l) for l in before], [key(l) for l in after])
    parts = []
    for index, line in enumerate(after):
        if index == len(after) - 1:
            parts.append(line)
        else:
            src = source[index]
            parts.append(line + (endings[src] if src is not None and src < len(endings) else fallback))
    return "".join(parts)


def match_view(source: str, old_string: str, new_string: str) -> tuple[list[Match], Callable[[Match], str]]:
    view = source.replace(CRLF, "\n")
    removed = [m.start() - index for index, m in enumerate(re.finditer(r"\r\n", source))]
    file_ending = line_ending(source, "\n")
    search = old_string.replace(CRLF, "\n")
    replacement = new_string.replace(CRLF, "\n")
    exact = find_occurrences(view, search)
    # These one-to-one mappings preserve offsets into the LF view.
    unicode = [] if exact else find_occurrences(normalize_for_match(view), normalize_for_match(search))
    trailing = [] if exact or unicode else find_line_occurrences(view, search)
    chosen = exact or unicode or trailing
    matches = [Match(m.start + bisect.bisect_left(removed, m.start), m.end + bisect.bisect_left(removed, m.end)) for m in chosen]

    def replace(match: Match) -> str:
        region = source[match.start : match.end]
        return with_region_endings(region, replacement, line_ending(region, file_ending))

    return matches, replace


def make(deps: ToolDeps) -> ToolInfo:
    async def execute(inp: Input, ctx: ToolContext) -> ToolResult:
        if inp.oldString == inp.newString:
            raise ToolError("No changes to apply: oldString and newString are identical.")
        if inp.oldString == "":
            raise ToolError("oldString must not be empty. Use write to create or overwrite a file.")
        target = deps.access.resolve(inp.path, "file")
        await deps.access.authorize_external([target], deps.invocation(ctx))
        async with FM.with_lock([resolve_path(deps.location.directory, inp.path)]):
            try:
                original = FM.read_text(target.absolute)
            except FileNotFoundError:
                raise ToolError(f"File not found: {inp.path}") from None
            except FM.FileKindError as exc:
                raise ToolError(f"Path is a directory, not a file: {inp.path}" if exc.actual == "directory" else f"Unable to edit {inp.path}", exc) from None
            deps.file_time.check(ctx.session_id, target.absolute, target.resource)
            source = original.text
            # Strings that differ only in \r ask to change line endings themselves, so they apply to the exact bytes.
            # Every other edit matches the LF view Read shows the model and keeps the file's endings.
            endings_only = inp.oldString.replace("\r", "") == inp.newString.replace("\r", "")
            if endings_only:
                matches, replace = find_occurrences(source, inp.oldString), (lambda _m: inp.newString)
            else:
                matches, replace = match_view(source, inp.oldString, inp.newString)
            replacements = len(matches)
            chosen = matches if inp.replaceAll else matches[:1]
            replaced = source
            for m in reversed(chosen):
                replaced = replaced[: m.start] + replace(m) + replaced[m.end :]
            preview = file_diff(target.resource, source, replaced) if replacements > 0 and (replacements == 1 or inp.replaceAll) else None
            await deps.assert_permission(ctx, "edit", [target.resource], save=["*"], metadata={"files": [preview.to_json()]} if preview else None)
            if replacements == 0:
                raise ToolError(f"Could not find oldString in {inp.path}. It must match exactly, including whitespace and indentation.")
            if replacements > 1 and not inp.replaceAll:
                raise ToolError(
                    f"Found {replacements} matches for oldString, but expected exactly one. Add more surrounding context to make oldString unique, "
                    "or set replaceAll to true to replace every occurrence."
                )
            if replaced == source:
                raise ToolError(
                    f"No changes to apply: {inp.path} already has those line endings." if endings_only
                    else f"No changes to apply: the edit leaves {inp.path} unchanged. Line endings follow the file; to change them, write \\r explicitly in oldString or newString."
                )
            keep_bom = original.bom or replaced.startswith("﻿")
            result = FM.write(target.absolute, target.resource, Bom.join(replaced, keep_bom))
            deps.file_time.record(ctx.session_id, target.absolute)
            final = FM.read_text(target.absolute).text
        diff = file_diff(result.resource, source, final)
        return ToolResult(
            content=f"Edited {diff.file} ({replacements} replacement{'' if replacements == 1 else 's'})",
            output={"files": [diff.to_json()], "replacements": replacements}, metadata={"files": [diff.to_json()]},
        )

    return ToolInfo(NAME, DESCRIPTION, Input, execute, ToolOptions(permission="edit"))
