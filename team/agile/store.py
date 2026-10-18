"""Saves the agile state after every change, so a stopped run resumes in the same sprint, on the same day."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Optional

from team.agile.model import AgileState


class AgileStore:
    def __init__(self, path: Path, run_id: str = "", on_change: Optional[Callable[[AgileState], None]] = None) -> None:
        self.path = Path(path)
        self.on_change = on_change
        self.state = self._load(run_id)

    def _load(self, run_id: str) -> AgileState:
        if self.path.exists():
            try:
                state = AgileState.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
                if not run_id or state.run_id == run_id:
                    return state
            except (OSError, ValueError, TypeError):
                pass  # an unreadable or foreign file starts a fresh record
        return AgileState(run_id=run_id)

    @property
    def resumed(self) -> bool:
        return bool(self.state.sprints or self.state.tasks)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state.to_dict(), indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
        if self.on_change is not None:
            self.on_change(self.state)
