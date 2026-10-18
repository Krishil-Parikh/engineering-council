"""Where the agents work: the project root, the working directory and the harness's own data directory."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path


def harness_home() -> Path:
    return Path(os.environ.get("HARNESS_HOME") or Path.home() / ".council-harness")


def git_root(start: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(out.stdout.strip()).resolve() if out.returncode == 0 and out.stdout.strip() else None


class Workspace:
    def __init__(self, directory: str | Path, home: Path | None = None) -> None:
        self.cwd = Path(directory).resolve()
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.root = git_root(self.cwd) or self.cwd
        self.is_git = git_root(self.cwd) is not None
        self.home = (home or harness_home()).resolve()
        key = hashlib.sha1(str(self.root).lower().encode()).hexdigest()[:12]
        self.data = self.home / "projects" / f"{self.root.name}-{key}"
        self.data.mkdir(parents=True, exist_ok=True)
        self.tmp = self.data / "tmp"
        self.tmp.mkdir(exist_ok=True)

    # ---- paths
    def resolve(self, path: str | Path, base: Path | None = None) -> Path:
        p = Path(os.path.expanduser(str(path)))
        if not p.is_absolute():
            p = (base or self.cwd) / p
        return Path(os.path.normpath(p))

    def inside(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
            return True
        except ValueError:
            pass
        try:
            path.resolve().relative_to(self.tmp.resolve())
            return True
        except ValueError:
            return False

    def display(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    @property
    def sessions_dir(self) -> Path:
        d = self.data / "sessions"
        d.mkdir(exist_ok=True)
        return d

    @property
    def output_dir(self) -> Path:
        d = self.data / "tool-output"
        d.mkdir(exist_ok=True)
        return d


def system_tmp() -> Path:
    return Path(tempfile.gettempdir())
