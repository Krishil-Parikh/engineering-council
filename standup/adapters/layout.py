"""Where a meeting's files live: <root>/<workspace>/<meeting>/. Ids are checked, and the result is checked to be inside the root, so no id can climb out of it."""

from __future__ import annotations

from pathlib import Path

from standup.errors import StoreError
from standup.events import check_id


def meeting_dir(root: Path, workspace_id: str, meeting_id: str) -> Path:
    check_id(workspace_id, "workspace_id")
    check_id(meeting_id, "meeting_id")
    base = Path(root).resolve()
    target = (base / workspace_id / meeting_id).resolve()
    if base != target and base not in target.parents:
        raise StoreError(f"{target} is outside {base}")
    return target
