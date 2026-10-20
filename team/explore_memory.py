"""Turns what the pod learned by reading the repository at kickoff into the team's memory, so the project and agent memories start with the meeting."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Callable, Optional

from memory.models import default_model
from memory.team import TeamMemory


def memory_root(meeting_dir: Path) -> Path:
    """Where the build keeps its memory (TeamEngine puts it under <meeting>/team): the same folder, so nothing is rebuilt later."""
    return Path(meeting_dir) / "team" / "memory"


def make_hook(api_key: Optional[str] = None, model: Optional[str] = None, on_memory: Optional[Callable[[TeamMemory], None]] = None, memory_model: Any = None):
    """A hook for run_meeting(on_explored=...). `on_memory` is told about the open memory as soon as it exists, so a screen can show it filling."""

    async def hook(found: Any, meeting_dir: Path) -> None:
        mem = TeamMemory(memory_root(meeting_dir), memory_model if memory_model is not None else default_model(api_key or os.environ.get("GEMINI_API_KEY"), model or os.environ.get("GEMINI_MODEL")))
        if on_memory is not None:
            on_memory(mem)
        data = found.model_dump()
        files = await asyncio.to_thread(mem.ingest_exploration, data)  # the notes the developers wrote
        root = Path(found.root)
        if root.is_dir():
            await asyncio.to_thread(mem.ingest_codemap, root)  # and the exact structure of the code (imports), which needs no model
        hook.last = files  # type: ignore[attr-defined]

    hook.last = {}  # type: ignore[attr-defined]
    return hook
