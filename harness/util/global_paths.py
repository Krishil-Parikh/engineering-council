"""Where the harness keeps its global files (opencode: @opencode/util/global).

  <root>/AGENTS.md, skills/, agents/, harness.json   user-level configuration and memory (the "config" directory)
  <root>/data      database, snapshots, saved tool output
  <root>/cache     downloaded skills and other cacheable files
  <root>/tmp       scratch space that is pre-approved for external access"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GlobalPaths:
    home: Path  # the user's home directory (project walks stop here when a project lives under it)
    config: Path
    data: Path
    cache: Path
    tmp: Path

    @staticmethod
    def default(root: Path | None = None, home: Path | None = None) -> "GlobalPaths":
        base = Path(root or os.environ.get("HARNESS_HOME") or Path.home() / ".council-harness")
        return GlobalPaths(home=Path(home or Path.home()), config=base, data=base / "data", cache=base / "cache", tmp=base / "tmp")

    def ensure(self) -> "GlobalPaths":
        for p in (self.config, self.data, self.cache, self.tmp):
            p.mkdir(parents=True, exist_ok=True)
        return self
