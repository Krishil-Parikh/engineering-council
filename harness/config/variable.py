"""`{env:VAR}` and `{file:path}` substitution in config text (opencode: packages/core/src/config/variable.ts)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional


def strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments (outside strings) and trailing commas, so the result is plain JSON."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        else:
            out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def parse_jsonc(text: str):
    """Returns the parsed value or raises ValueError on malformed JSON/JSONC."""
    return json.loads(strip_jsonc(text))


def _valid(text: str) -> bool:
    try:
        parse_jsonc(text)
        return True
    except ValueError:
        return False


def substitute(text: str, *, path: Optional[Path] = None, directory: Optional[Path] = None, env: Optional[dict[str, str]] = None) -> str:
    """Apply {env:VAR} and {file:path}. Values are escaped for JSON only when the raw substitution would break the JSON
    (for example Windows paths), so configs that parse today keep their meaning."""
    base = (path.parent if path else directory) or Path.cwd()

    def env_sub(escape: bool, t: str) -> str:
        def rep(m: re.Match[str]) -> str:
            value = (env or {}).get(m.group(1)) or os.environ.get(m.group(1)) or ""
            return json.dumps(value)[1:-1] if escape else value

        return re.sub(r"\{env:([^}]+)\}", rep, t)

    def file_sub(t: str, escape: bool) -> str:
        out, cursor = "", 0
        for m in re.finditer(r"\{file:[^}]+\}", t):
            out += t[cursor : m.start()]
            line_start = t.rfind("\n", 0, m.start()) + 1
            if t[line_start : m.start()].lstrip().startswith("//"):
                out += m.group(0)  # a commented-out reference is left alone
                cursor = m.end()
                continue
            ref = m.group(0)[len("{file:") : -1]
            p = Path(os.path.expanduser(ref))
            p = p if p.is_absolute() else base / p
            try:
                content = p.read_text(encoding="utf-8").strip()
            except OSError:
                content = ""
            out += json.dumps(content)[1:-1] if escape else content
            cursor = m.end()
        return out + t[cursor:]

    raw = file_sub(env_sub(False, text), False)
    if "{env:" in text and not _valid(raw):
        return file_sub(env_sub(True, text), True)
    return raw
