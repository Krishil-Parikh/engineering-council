"""File persistence: atomic writes, stable JSON, checkpoints, revision backups."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TypeVar

from pydantic import BaseModel, ValidationError

from engineering_council.models import MeetingState

T = TypeVar("T", bound=BaseModel)

DOC_NAMES = ("PRD.md", "Technical_Approach.md", "Design.md")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_text(path: Path, text: str) -> None:
    """Write via a temp file then replace, so a crash never leaves a half-written artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def write_json(path: Path, data: BaseModel | dict | list) -> None:
    payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def read_model(path: Path, model: type[T]) -> Optional[T]:
    """Load a checkpoint. A missing or corrupt file means 'stage not done'."""
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return None


class MeetingStore:
    """One meeting's output directory plus its meeting.json state."""

    def __init__(self, root: Path, model_name: str = "") -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.state = read_model(root / "meeting.json", MeetingState) or MeetingState(
            started_at=now_iso(), model=model_name
        )
        self.state.model = model_name or self.state.model

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def save(self, rel: str, data: BaseModel | dict | list) -> None:
        write_json(self.path(rel), data)

    def load(self, rel: str, model: type[T]) -> Optional[T]:
        return read_model(self.path(rel), model)

    def save_text(self, rel: str, text: str) -> None:
        write_text(self.path(rel), text)

    def begin(self, stage: str) -> None:
        self.state.stage, self.state.status = stage, "running"
        self._flush()

    def complete(self, stage: str) -> None:
        if stage not in self.state.completed_stages:
            self.state.completed_stages.append(stage)
        self._flush()

    def warn(self, message: str) -> None:
        if message not in self.state.warnings:
            self.state.warnings.append(message)
        self._flush()

    def finish(self, status: str, error: str = "") -> None:
        self.state.status, self.state.error = status, error  # type: ignore[assignment]
        self._flush()

    def _flush(self) -> None:
        self.state.updated_at = now_iso()
        write_json(self.path("meeting.json"), self.state)

    def backup_documents(self) -> Optional[Path]:
        """Copy current documents to revisions/<timestamp>/ before they are overwritten."""
        existing = [n for n in (*DOC_NAMES, "specification.json", "decisions.json") if self.path(n).exists()]
        if not existing:
            return None
        dest = self.path("revisions", datetime.now().strftime("%Y%m%d-%H%M%S"))
        dest.mkdir(parents=True, exist_ok=True)
        for name in existing:
            shutil.copy2(self.path(name), dest / name)
        return dest
