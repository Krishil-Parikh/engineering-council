"""Writes the agile documents into the repository: on the integration branch, in the integrator's clone, while coding is paused.

Nobody else writes to docs/agile, so these commits never conflict with the developers' work; developers pick them up when their next
feature branches from the integration branch. Each write is one commit, pushed through the git brain like every other git step."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from meetings.storage import write_text

if TYPE_CHECKING:
    from team.engine import TeamEngine

INTEGRATOR = "integrator"


class AgileDocs:
    def __init__(self, engine: "TeamEngine") -> None:
        self.engine = engine
        self.written: list[str] = []  # every path written, in order (for the report and the tests)

    async def write(self, files: dict[str, str], message: str) -> bool:
        """Writes the files (paths relative to the repository root) and commits them to the integration branch. False when nothing changed."""
        eng = self.engine
        async with eng.merge_lock:
            await eng.git(INTEGRATOR, f"check out the integration branch {eng.integration}", eng.repo.checkout_branch, INTEGRATOR, eng.integration, branch=eng.integration)
            sandbox = eng.repo.sandbox_path(INTEGRATOR)
            for path, text in files.items():
                write_text(sandbox / path, text)
                self.written.append(path)
            if not await eng.git(INTEGRATOR, "commit the agile documents", eng.repo.commit_all, INTEGRATOR, message):
                return False
            await eng.git(INTEGRATOR, f"publish {eng.integration} with the agile documents", eng.repo.push, INTEGRATOR, eng.integration, branch=eng.integration)
        eng._emit("agile-docs", files=sorted(files), message=message)
        return True

    def read(self, path: str) -> str:
        try:
            return (self.engine.repo.sandbox_path(INTEGRATOR) / path).read_text(encoding="utf-8")
        except OSError:
            return ""

    @staticmethod
    def stamp() -> str:
        return time.strftime("%Y-%m-%d %H:%M")
