"""Background work (shell commands, subagents). The agent is told when a job finishes instead of polling for it."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    id: str
    kind: str  # shell | subagent
    title: str
    file: str = ""
    status: str = "running"  # running | completed | error | cancelled
    exit: int | None = None
    started: float = field(default_factory=time.time)
    process: Any = None
    task: asyncio.Task | None = None


def kill_tree(proc: Any) -> None:
    """Stop a process and everything it started."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError, subprocess.SubprocessError):
        try:
            proc.kill()
        except (OSError, ProcessLookupError):
            pass


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._notes: list[str] = []
        self._changed = asyncio.Event()
        self._n = 0

    def next_id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}_{self._n}"

    def add(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job

    def running(self) -> list[Job]:
        return [j for j in self.jobs.values() if j.status == "running"]

    def finish(self, job: Job, status: str, note: str, exit_code: int | None = None) -> None:
        if job.status != "running":
            return
        job.status, job.exit = status, exit_code
        self._notes.append(note)
        self._changed.set()

    def drain(self) -> list[str]:
        notes, self._notes = self._notes, []
        self._changed.clear()
        return notes

    async def wait_for_news(self, timeout: float | None = None) -> bool:
        """Wait until some job finishes. False if nothing is running or the wait timed out."""
        if self._notes:
            return True
        if not self.running():
            return False
        try:
            await asyncio.wait_for(self._changed.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def cancel_all(self) -> None:
        for job in self.running():
            if job.process is not None:
                kill_tree(job.process)
            if job.task is not None:
                job.task.cancel()
            job.status = "cancelled"
