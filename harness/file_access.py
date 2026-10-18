"""Resolving paths and approving access outside the project (opencode: packages/core/src/file-access.ts).

A path inside the working directory or the project root is "internal" and is named relative to the working directory. Any
other path is "external": its permission resource is the absolute path, and using it first needs an `external_directory`
approval for the directory it lives in. Reads then need the `read` permission on top of that."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from harness.location import Location
from harness.permission import Permission
from harness.util import fs


def windows_path(value: str) -> str:
    """Accept /c/Users/x and C:/Users/x spellings that shells print on Windows."""
    if os.name != "nt":
        return value
    import re

    m = re.match(r"^/([a-zA-Z])(/.*)?$", value)
    return f"{m.group(1).upper()}:{m.group(2) or '/'}" if m else value


def resolve_path(directory: str | Path, text: str, home: Optional[Path] = None) -> str:
    """Expand a leading ~ and normalize Windows shell paths, then resolve against `directory` lexically."""
    home = home or Path.home()
    normalized = windows_path(text)
    if normalized == "~":
        return os.path.normpath(str(home))
    if normalized.startswith("~/") or (os.name == "nt" and normalized.startswith("~\\")):
        normalized = str(home / normalized[2:])
    return os.path.normpath(os.path.join(str(directory), normalized))


def _slash(value: str) -> str:
    return value.replace("\\", "/")


@dataclass
class ExternalDirectory:
    directory: str
    resource: str
    save: str
    action: str = "external_directory"


@dataclass
class Target:
    absolute: str
    resource: str  # location-relative for internal paths, absolute for external ones
    external_directory: Optional[ExternalDirectory] = None


@dataclass
class Invocation:
    session_id: str
    agent: str
    message_id: str
    id: str  # tool call id


def project_root_of(directory: str) -> Optional[str]:
    from harness.location import git_root

    root = git_root(Path(directory)) if Path(directory).exists() else None
    return str(root) if root else None


class FileAccess:
    def __init__(self, location: Location, permission: Permission, home: Optional[Path] = None) -> None:
        self.location, self.permission, self.home = location, permission, home or Path.home()

    def resolve(self, path: str, kind: Optional[str] = None) -> Target:
        """Resolve a lexical path and its permission resources, without requesting approval. `kind` picks the approval boundary."""
        absolute = resolve_path(self.location.directory, path, self.home)
        worktree = os.path.abspath(str(self.location.project_directory))
        root_of_fs = Path(worktree).parent == Path(worktree)
        internal = fs.contains(self.location.directory, absolute) or (not root_of_fs and fs.contains(worktree, absolute))
        if internal:
            return Target(absolute, _slash(os.path.relpath(absolute, self.location.directory)) if absolute != str(self.location.directory) else ".")
        if kind == "directory":
            is_dir = True
        elif kind == "file":
            is_dir = False
        else:
            is_dir = Path(absolute).is_dir()
        directory = absolute if is_dir else os.path.dirname(absolute)
        return Target(
            absolute, _slash(absolute),
            ExternalDirectory(directory, _slash(os.path.join(directory, "*")), _slash(os.path.join(project_root_of(directory) or directory, "*"))),
        )

    async def authorize_external(self, targets: list[Target], context: Invocation, metadata: Optional[dict[str, Any]] = None) -> None:
        """Approve external directories in one batch, preserving first-seen resource order."""
        seen: dict[str, ExternalDirectory] = {}
        for t in targets:
            if t.external_directory and t.external_directory.resource not in seen:
                seen[t.external_directory.resource] = t.external_directory
        if not seen:
            return
        await self.permission.assert_(
            session_id=context.session_id, action="external_directory", resources=[e.resource for e in seen.values()], save=[e.save for e in seen.values()],
            metadata=metadata, agent=context.agent, source={"type": "tool", "messageID": context.message_id, "id": context.id},
        )

    async def authorize_read(self, file: str, context: Invocation, sibling_of: Optional[Target] = None) -> Target:
        """Resolve a read target and obtain external-directory approval before read approval."""
        target = self.resolve(file, "file" if sibling_of else None)
        sibling = sibling_of is not None and os.path.dirname(target.absolute) == os.path.dirname(sibling_of.absolute)
        # Filename recovery shares the directory approval, but checks the recovered file's own read rules.
        if not sibling:
            await self.authorize_external([target], context)
        await self.permission.assert_(
            session_id=context.session_id, action="read", resources=[target.resource], save=["*"], agent=context.agent,
            source={"type": "tool", "messageID": context.message_id, "id": context.id},
        )
        return target
