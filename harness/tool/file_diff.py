"""File diffs shown in permission prompts and tool results (opencode: tool/plugin/file-diff.ts, using jsdiff)."""

from __future__ import annotations

import difflib
from dataclasses import asdict, dataclass
from typing import Literal


@dataclass
class FileDiff:
    file: str
    patch: str
    additions: int
    deletions: int
    status: Literal["added", "deleted", "modified"] = "modified"

    def to_json(self) -> dict:
        return asdict(self)


def create_two_files_patch(name: str, before: str, after: str) -> str:
    """The format of jsdiff's createTwoFilesPatch: an Index header, then a unified diff with 4 lines of context... (jsdiff uses 4)."""
    lines = list(difflib.unified_diff(before.splitlines(True), after.splitlines(True), name, name, n=4, lineterm="\n"))
    body = "".join(ln if ln.endswith("\n") else ln + "\n\\ No newline at end of file\n" for ln in lines)
    return f"Index: {name}\n{'=' * 67}\n{body}"


def file_diff(file: str, before: str, after: str, status: Literal["added", "deleted", "modified"] = "modified") -> FileDiff:
    additions = deletions = 0
    sm = difflib.SequenceMatcher(None, before.splitlines(True), after.splitlines(True), autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            deletions += i2 - i1
        if tag in ("replace", "insert"):
            additions += j2 - j1
    return FileDiff(file, create_two_files_patch(file, before, after), additions, deletions, status)
