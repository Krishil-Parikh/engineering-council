"""Wildcard matching for permission rules (opencode: packages/core/src/util/wildcard.ts).

`*` matches anything (including slashes), `?` one character. A trailing " *" also matches the bare command, so "git status *"
matches "git status". Matching is case-insensitive on Windows."""

from __future__ import annotations

import re
import sys

_SPECIAL = re.compile(r"[.+^${}()|\[\]\\]")


def match(text: str, pattern: str) -> bool:
    normalized = text.replace("\\", "/")
    escaped = _SPECIAL.sub(lambda m: "\\" + m.group(0), pattern.replace("\\", "/")).replace("*", ".*").replace("?", ".")
    if escaped.endswith(" .*"):
        escaped = escaped[:-3] + "( .*)?"
    flags = re.DOTALL | (re.IGNORECASE if sys.platform == "win32" else 0)
    return re.fullmatch(escaped, normalized, flags) is not None
