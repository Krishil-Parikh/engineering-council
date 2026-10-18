"""Where a session works (opencode: packages/core/src/location.ts): a directory inside a project."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from harness.util import fs


def git_root(start: Path) -> Optional[Path]:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return fs.resolve(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


@dataclass
class Location:
    directory: Path  # where the session works
    project_directory: Path  # the project root (git root, or the directory itself outside git)
    vcs: Optional[str]  # "git" or None
    workspace_id: Optional[str] = None

    @property
    def project_id(self) -> str:
        return hashlib.sha1(str(self.project_directory).lower().encode()).hexdigest()[:16]

    @staticmethod
    def of(directory: str | Path) -> "Location":
        d = fs.resolve(directory)
        d.mkdir(parents=True, exist_ok=True)
        root = git_root(d)
        return Location(directory=d, project_directory=root or d, vcs="git" if root else None)
