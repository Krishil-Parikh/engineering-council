"""Parsing one skill file (opencode: packages/core/src/config/plugin/skill-file.ts)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from harness.config import markdown
from harness.skill import SkillInfo


@dataclass
class Parsed:
    skill: SkillInfo


@dataclass
class Skipped:
    reason: str  # "markdown" | "frontmatter"
    issue: Optional[str] = None


def _boolean(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return True if value == 1 else False if value == 0 else None
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in ("true", "yes", "on", "1"):
        return True
    if v in ("false", "no", "off", "0"):
        return False
    return None


def _metadata_boolean(metadata: Any, key: str) -> Optional[bool]:
    if not isinstance(metadata, dict):
        return None
    return _boolean(metadata.get(key))


def parse(directory: str | Path, filepath: str | Path, content: str) -> Union[Parsed, Skipped]:
    md = markdown.parse_option(content)
    if md is None:
        return Skipped("markdown")
    data = md.data
    for key in ("name", "description"):
        if key in data and not isinstance(data[key], str):
            return Skipped("frontmatter", f"{key} must be a string")
    fp, d = Path(filepath), Path(directory)
    skill_id = fp.stem if fp.parent == d and fp.name != "SKILL.md" else fp.parent.name
    # opencode/autoinvoke is the native switch; `disable-model-invocation` is the Claude Code spelling of the same idea.
    native = _metadata_boolean(data.get("metadata"), "opencode/autoinvoke")
    disabled = _boolean(data.get("disable-model-invocation"))
    autoinvoke = native if native is not None else (False if disabled else None)
    return Parsed(SkillInfo(
        id=skill_id, name=data.get("name") or skill_id, path=fp, content=md.content,
        description=data.get("description"), autoinvoke=autoinvoke,
    ))
