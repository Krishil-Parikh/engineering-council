"""File snapshots in a private "shadow" git repository, so any agent step can be undone without touching the project's own history.
The shadow repo uses the project directory as its work tree and honours the project's .gitignore."""

from __future__ import annotations

import subprocess
from pathlib import Path

from coding_harness.workspace import Workspace

MAX_FILE_BYTES = 2_000_000


class Snapshots:
    def __init__(self, workspace: Workspace, enabled: bool = True) -> None:
        self.ws = workspace
        self.git_dir = workspace.data / "snapshot.git"
        self.enabled = enabled
        self._ready = False

    def _git(self, *args: str, check: bool = False, input_: bytes | None = None) -> subprocess.CompletedProcess:
        cmd = ["git", f"--git-dir={self.git_dir}", f"--work-tree={self.ws.root}", "-c", "core.autocrlf=false", "-c", "core.longpaths=true",
               "-c", "core.quotepath=false", "-c", "user.name=harness", "-c", "user.email=harness@localhost", *args]
        return subprocess.run(cmd, cwd=self.ws.root, capture_output=True, input=input_, timeout=120, check=check)

    def _init(self) -> bool:
        if self._ready:
            return True
        try:
            if not (self.git_dir / "HEAD").exists():
                self.git_dir.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "init", "--bare", str(self.git_dir)], capture_output=True, timeout=30, check=True)
            self._ready = True
        except (OSError, subprocess.SubprocessError):
            self.enabled = False
        return self._ready

    def capture(self) -> str:
        """Content-addressed id of the project's current files ('' when snapshots are unavailable)."""
        if not self.enabled or not self._init():
            return ""
        try:
            self._git("add", "-A", "--ignore-errors")
            out = self._git("write-tree")
            return out.stdout.decode().strip() if out.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    def changed(self, since: str) -> list[tuple[str, str]]:
        """(status, path) for files that differ between `since` and the project's files now. Status is A, M or D."""
        now = self.capture()
        if not since or not now or since == now:
            return []
        out = self._git("diff", "--name-status", "--no-renames", since, now)
        rows = []
        for line in out.stdout.decode("utf-8", "replace").splitlines():
            if "\t" in line:
                status, path = line.split("\t", 1)
                rows.append((status[0], path))
        return rows

    def diff(self, since: str) -> str:
        now = self.capture()
        if not since or not now or since == now:
            return ""
        return self._git("diff", since, now).stdout.decode("utf-8", "replace")

    def restore(self, snapshot: str) -> list[str]:
        """Put the project's files back to how they were at `snapshot`. Returns the paths that were changed."""
        if not snapshot:
            return []
        rows = self.changed(snapshot)
        touched = []
        for status, rel in rows:
            target = self.ws.root / rel
            if status == "A":  # created after the snapshot: remove it
                try:
                    target.unlink(missing_ok=True)
                    touched.append(rel)
                except OSError:
                    pass
        for status, rel in rows:
            if status in ("M", "D"):  # modified or deleted after the snapshot: bring back its version
                self._git("checkout", snapshot, "--", rel)
                touched.append(rel)
        return touched
