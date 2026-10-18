"""Services the built-in tools need, passed explicitly instead of through a dependency-injection container."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from harness.file_access import FileAccess, Invocation
from harness.location import Location
from harness.permission import Permission
from harness.ripgrep import Ripgrep
from harness.session.instructions import SessionInstructions
from harness.session.store import SessionStore
from harness.tool.info import ToolContext


@dataclass
class ToolDeps:
    location: Location
    permission: Permission
    access: FileAccess
    store: SessionStore
    instructions: SessionInstructions
    ripgrep: Ripgrep = field(default_factory=Ripgrep)
    extras: dict[str, Any] = field(default_factory=dict)  # shell jobs, subagent runner, question handler, skills, ...

    def invocation(self, ctx: ToolContext) -> Invocation:
        return Invocation(ctx.session_id, ctx.agent, ctx.message_id, ctx.id)

    def source(self, ctx: ToolContext) -> dict[str, Any]:
        return {"type": "tool", "messageID": ctx.message_id, "id": ctx.id}

    async def assert_permission(self, ctx: ToolContext, action: str, resources: list[str], *, save: Optional[list[str]] = None, metadata: Optional[dict[str, Any]] = None) -> None:
        await self.permission.assert_(
            session_id=ctx.session_id, action=action, resources=resources, save=save, metadata=metadata, agent=ctx.agent, source=self.source(ctx)
        )
