"""Markdown files with YAML frontmatter (opencode: packages/core/src/config/markdown.ts, which uses gray-matter)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

import yaml

_FRONT = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.DOTALL)


@dataclass
class Parsed:
    data: dict[str, Any]
    content: str


def sanitize(content: str) -> str:
    """Other coding agents accept unquoted colons in frontmatter values. Retry those values as YAML block scalars so existing files keep working."""
    m = re.match(r"^---\r?\n([\s\S]*?)\r?\n---", content)
    if not m:
        return content
    frontmatter = m.group(1)
    result: list[str] = []
    for line in re.split(r"\r?\n", frontmatter):
        if line.strip().startswith("#") or line.strip() == "" or re.match(r"^\s+", line):
            result.append(line)
            continue
        entry = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)$", line)
        if not entry:
            result.append(line)
            continue
        value = entry.group(2).strip()
        if value in ("", ">", "|") or value.startswith(('"', "'")) or ":" not in value:
            result.append(line)
            continue
        result += [f"{entry.group(1)}: |-", f"  {value}"]
    return content.replace(frontmatter, "\n".join(result), 1)


def _parse(content: str) -> Parsed:
    m = _FRONT.match(content)
    if not m:
        return Parsed({}, content)
    data = yaml.safe_load(m.group(1))
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("frontmatter is not a mapping")
    return Parsed(data, content[m.end():])


def parse(content: str) -> Parsed:
    try:
        return _parse(content)
    except (yaml.YAMLError, ValueError):
        return _parse(sanitize(content))


def parse_option(content: str) -> Optional[Parsed]:
    try:
        return parse(content)
    except (yaml.YAMLError, ValueError):
        return None
