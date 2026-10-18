"""Skills (opencode: packages/core/src/skill.ts and packages/schema/src/skill.ts).

A skill is a Markdown file with frontmatter (`name`, `description`) holding specialised instructions the model loads on demand
through the skill tool. The model sees the list of available skills (id, name, description) as an instruction source; the
content is only added to the conversation when the model, or the user, activates one."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from harness.permission import evaluate
from harness.schema.permission import Ruleset
from harness.util import fs


@dataclass
class SkillInfo:
    id: str
    name: str
    path: Path
    content: str
    description: Optional[str] = None
    autoinvoke: Optional[bool] = None


def available(skills: list[SkillInfo], permissions: Ruleset) -> list[SkillInfo]:
    """Skills the permissions do not deny."""
    return [s for s in skills if evaluate("skill", s.id, permissions).effect != "deny"]


def to_model_output(skill: SkillInfo, files: list[str]) -> str:
    directory = skill.path.parent
    return "\n".join([
        f'<skill_content name="{skill.name}">',
        f"# Skill: {skill.name}",
        "",
        skill.content.strip(),
        "",
        f"Base directory for this skill: {directory}",
        "Relative paths in this skill (e.g., scripts/, reference/) are relative to this base directory.",
        "Note: file list is sampled.",
        "",
        "<skill_files>",
        *[f"<file>{f}</file>" for f in files],
        "</skill_files>",
        "</skill_content>",
    ])


def prepare(skill: SkillInfo) -> dict[str, str]:
    """What the skill tool returns: the skill content plus (up to 10) other files in the skill's folder."""
    directory = skill.path.parent
    files: list[str] = []
    if skill.path.name == "SKILL.md":
        files = sorted(f for f in fs.scan("**/*", directory, absolute=True, include="file", dot=True) if os.path.basename(f) != "SKILL.md")[:10]
    return {"directory": str(directory), "output": to_model_output(skill, files)}


class SkillCatalog:
    """The set of known skills, keyed by id (a later registration with the same id replaces an earlier one)."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillInfo] = {}
        self._providers: list = []

    def add_provider(self, provider) -> None:
        """A provider is a callable returning a list of SkillInfo; providers are applied in registration order."""
        self._providers.append(provider)

    def reload(self) -> None:
        self._skills = {}
        for provider in self._providers:
            for skill in provider():
                self._skills[skill.id] = skill

    def list(self) -> list[SkillInfo]:
        if not self._skills and self._providers:
            self.reload()
        return list(self._skills.values())

    def get(self, skill_id: str) -> Optional[SkillInfo]:
        return next((s for s in self.list() if s.id == skill_id), None)
