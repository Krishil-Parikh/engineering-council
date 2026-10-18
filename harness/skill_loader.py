"""Loading skills from disk (opencode: config/plugin/skill.ts and config/plugin/compatibility.ts).

Sources, lowest priority first (a later skill with the same id replaces an earlier one):
  - `skills/` folders of ~/.claude, ~/.agents and the project's .claude/.agents directories (Claude Code compatibility)
  - `skill/` and `skills/` folders of every config directory (the global config dir and project .harness dirs)
  - directories or URLs listed under `skills` in a config document
Each source is scanned for `*.md` files directly inside it and `**/SKILL.md` files below it."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from harness.config import service as cfg
from harness.skill import SkillInfo
from harness.skill_file import Parsed, parse
from harness.util import fs
from harness.util.global_paths import GlobalPaths

log = logging.getLogger("harness.skill")
PATTERN = "{*.md,**/SKILL.md}"


def load_directory(directory: Path) -> list[SkillInfo]:
    skills: list[SkillInfo] = []
    for filepath in sorted(fs.scan(PATTERN, directory, absolute=True, include="file", dot=True)):
        content = fs.read_text_safe(filepath)
        if not content:
            continue
        parsed = parse(directory, filepath, content)
        if isinstance(parsed, Parsed):
            skills.append(parsed.skill)
        else:
            log.debug("skill file skipped: %s (%s)", filepath, parsed.reason)
    return skills


class SkillLoader:
    def __init__(self, config: cfg.Config, paths: GlobalPaths, location_directory: Path) -> None:
        self.config, self.paths, self.directory = config, paths, Path(location_directory)

    def _config_sources(self, entries: list[cfg.Entry]) -> list[Path]:
        out: list[Path] = []

        def add(p: Path) -> None:
            if p not in out:
                out.append(p)

        for entry in entries:
            if isinstance(entry, cfg.Directory):
                add(entry.path / "skill")
                add(entry.path / "skills")
        for entry in entries:
            if isinstance(entry, cfg.Document):
                for item in entry.info.get("skills") or []:
                    if item.startswith(("http://", "https://")):
                        log.info("remote skill sources are not fetched: %s", item)  # skill URL discovery is not ported
                        continue
                    expanded = Path(os.path.expanduser(item)) if item.startswith("~/") else Path(item)
                    add(expanded if expanded.is_absolute() else self.directory / expanded)
        return out

    def load(self) -> list[SkillInfo]:
        loaded: dict[str, SkillInfo] = {}
        compat = self.config.compatibility()
        for root in [*compat["claude"], *compat["agents"]]:
            d = root / "skills"
            if d.is_dir():
                for s in load_directory(d):
                    loaded[s.id] = s
        for source in self._config_sources(self.config.entries()):
            if source.is_dir():
                for s in load_directory(source):
                    loaded[s.id] = s
        return list(loaded.values())
