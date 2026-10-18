"""Tools for managing the harness itself: sessions, worktrees and the model list (opencode: tool/plugin/opencode.ts, namespace "opencode").

They register under the namespace "harness", so the model sees harness_session_rename, harness_session_move, harness_worktree_create,
harness_worktree_list, harness_worktree_remove and harness_models. `deps.extras` supplies "sessions" (SessionService), "worktrees"
(WorktreeManager) and "model_catalog" (ModelCatalog)."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from pydantic import BaseModel, Field

from harness import worktree as W
from harness.git import GitError
from harness.session.service import SessionNotFoundError
from harness.tool.builtin.deps import ToolDeps
from harness.tool.info import ToolContext, ToolError, ToolInfo, ToolOptions, ToolResult

NAMESPACE = "harness"
WORKTREE_HINT = (
    "When you create a worktree outside the current working directory and intend to use it as your primary working directory, "
    "consider calling the harness_session_move tool to make the worktree the session's working directory."
)


class RenameInput(BaseModel):
    sessionID: Optional[str] = Field(default=None, description="Omit to rename the current session.")
    title: str = Field(min_length=1, description="New session title.")


class MoveInput(BaseModel):
    sessionID: Optional[str] = Field(default=None, description="Omit to move the current session.")
    directory: str = Field(min_length=1, description="Destination directory, relative to the target session's directory or absolute. Supports ~.")


class WorktreeCreateInput(BaseModel):
    name: str = Field(min_length=1, description="Worktree name.")


class WorktreeRemoveInput(BaseModel):
    directory: str = Field(min_length=1, description="Absolute path of the worktree to remove.")
    force: Optional[bool] = Field(default=None, description="Discard modified and untracked files. Only set this when the user has confirmed forced removal.")


class ListInput(BaseModel):
    pass


class ModelsInput(BaseModel):
    query: Optional[str] = Field(default=None, description="Text to search for in model names and IDs.")
    provider: Optional[str] = Field(default=None, description="Provider ID or name to filter by. Try your own provider first.")
    all: Optional[bool] = Field(default=None, description="Include older versions of each model family. By default only the newest version is listed.")
    limit: Optional[int] = Field(default=None, ge=1, le=100, description="Maximum number of models to return. Defaults to 20.")
    offset: Optional[int] = Field(default=None, ge=0, description="Number of models to skip, for paging through results.")


def remove_failure(directory: str, exc: Exception) -> str:
    """Worktree errors carry no model-facing message, and Git's own text suggests forcing removal."""
    if isinstance(exc, W.DirectoryUnavailableError):
        return f"Unable to remove worktree {directory}: the directory does not exist or is not a directory."
    if isinstance(exc, W.InvalidDirectoryError):
        return f"Unable to remove {directory}: it is not a worktree of this project. Use worktree_list to see the project's worktrees."
    if isinstance(exc, W.StrategyUnavailableError):
        return f"Unable to remove worktree {directory}: its worktree strategy {exc.strategy} is not available."
    if isinstance(exc, W.OperationError) and exc.force_required:
        return f"Unable to remove worktree {directory}: it has modified or untracked files."
    return f"Unable to remove worktree {directory}."


def make_all(deps: ToolDeps) -> list[ToolInfo]:
    def ns(permission: Optional[str] = None) -> ToolOptions:
        return ToolOptions(namespace=NAMESPACE, permission=permission)

    async def rename(inp: RenameInput, ctx: ToolContext) -> ToolResult:
        session_id = inp.sessionID or ctx.session_id
        title = inp.title.strip()
        if not title:
            raise ToolError("Session title must not be empty")
        try:
            deps.extras["sessions"].rename(session_id, title)
        except SessionNotFoundError as exc:
            raise ToolError(f"Unable to rename session {session_id}", exc) from None
        return ToolResult(content=f"Renamed session {session_id} to {title}.", output={"sessionID": session_id, "title": title})

    async def move(inp: MoveInput, ctx: ToolContext) -> ToolResult:
        session_id = inp.sessionID or ctx.session_id
        try:
            target = deps.extras["sessions"].move(session_id, inp.directory)
        except (SessionNotFoundError, OSError) as exc:
            raise ToolError(f"Unable to move session to {inp.directory}: {exc}", exc) from None
        return ToolResult(content=f"Moved session {session_id} to {target}.", output={"sessionID": session_id, "directory": target})

    async def worktree_create(inp: WorktreeCreateInput, ctx: ToolContext) -> ToolResult:
        try:
            out = await asyncio.to_thread(deps.extras["worktrees"].create, name=inp.name.strip())
        except (W.WorktreeServiceError, GitError) as exc:
            raise ToolError(f"Unable to create worktree {inp.name}: {getattr(exc, 'message', None) or exc}", exc) from None
        return ToolResult(content=f"Created worktree in {out['directory']}.", output=out)

    async def worktree_list(inp: ListInput, ctx: ToolContext) -> ToolResult:
        worktrees = [{"directory": w.directory, **({"strategy": w.strategy} if w.strategy else {})} for w in deps.extras["worktrees"].list()]
        return ToolResult(content=None, output={"worktrees": worktrees})

    async def worktree_remove(inp: WorktreeRemoveInput, ctx: ToolContext) -> ToolResult:
        # Removing a worktree deletes files, so it requires the same approval as editing them.
        try:
            target = deps.access.resolve(inp.directory, "directory")
            await deps.assert_permission(ctx, "edit", [target.resource], save=["*"])
            try:
                await asyncio.to_thread(deps.extras["worktrees"].remove, target.absolute, inp.force or False)
            except (W.WorktreeServiceError, GitError) as exc:
                raise ToolError(remove_failure(target.absolute, exc if isinstance(exc, W.WorktreeServiceError) else W.OperationError(str(exc)))) from None
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001
            from harness.permission import CorrectedError, DeclinedError

            if isinstance(exc, (DeclinedError, CorrectedError)):
                raise
            raise ToolError(f"Unable to remove worktree {inp.directory}", exc) from None
        return ToolResult(content=f"Removed worktree {target.absolute}.", output={"directory": target.absolute, "removed": True})

    async def models(inp: ModelsInput, ctx: ToolContext) -> ToolResult:
        catalog = deps.extras["model_catalog"]
        offset, limit = inp.offset or 0, inp.limit or 20
        session = deps.store.get(ctx.session_id)
        own = (session.model or {}).get("provider_id") if session else None
        terms = (inp.query or "").lower().split()
        wanted = inp.provider.lower() if inp.provider else None
        names = catalog.providers
        matching = [
            m for m in catalog.list()
            if (wanted is None or m.provider_id.lower() == wanted or names.get(m.provider_id, "").lower() == wanted)
            and all(t in f"{m.provider_id}/{m.id} {m.name}".lower() for t in terms)
        ]
        matching.sort(key=lambda m: (m.provider_id != own, m.provider_id, -m.released))
        if not inp.all:
            seen: set[tuple[str, str]] = set()
            newest = []
            for m in matching:
                if m.family is not None:
                    if (m.provider_id, m.family) in seen:
                        continue
                    seen.add((m.provider_id, m.family))
                newest.append(m)
            matching = newest
        page = matching[offset : offset + limit]
        providers = []
        for pid in dict.fromkeys(m.provider_id for m in page):
            providers.append({
                "id": pid, "name": names.get(pid, pid),
                "models": [
                    {"id": f"{m.provider_id}/{m.id}", "name": m.name, "released": m.released, "variants": list(m.variants),
                     "cost": [vars(c) for c in m.cost], "status": m.status}
                    for m in page if m.provider_id == pid
                ],
            })
        out: dict[str, Any] = {"providers": providers, "total": len(matching), "next": offset + limit if offset + limit < len(matching) else None}
        return ToolResult(content=None, output=out)

    return [
        ToolInfo("session_rename", "Rename a session, or omit sessionID to rename the current session. Use a short, specific title that summarizes the work being done.", RenameInput, rename, ns()),
        ToolInfo("session_move", "Move a session to another directory, or omit sessionID to move the current session. The current session moves at the next safe boundary; do not run destination-dependent tools in the same step.", MoveInput, move, ns()),
        ToolInfo("worktree_create", "Create a named worktree. Returns its directory.", WorktreeCreateInput, worktree_create, ns()),
        ToolInfo("worktree_list", "List a repository's worktrees.", ListInput, worktree_list, ns()),
        ToolInfo("worktree_remove", "Remove a worktree. The repository location selects configuration; directory identifies the worktree to remove.", WorktreeRemoveInput, worktree_remove, ns("edit")),
        ToolInfo("models", "Search the models available to use. Use this to turn a model name the user mentions into an exact reference before running a subagent on it. Check your own provider first.", ModelsInput, models, ns()),
    ]
