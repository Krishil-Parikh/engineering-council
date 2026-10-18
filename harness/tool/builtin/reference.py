"""The reference tool (opencode: tool/plugin/reference.ts). Lists the configured reference repositories and gives the local directory of one.

`deps.extras["references"]` is the ReferenceService."""

from __future__ import annotations

import asyncio
from typing import Optional

from pydantic import BaseModel, Field

from harness.reference import ReferenceError_, ReferenceService
from harness.tool.builtin.deps import ToolDeps
from harness.tool.info import ToolContext, ToolError, ToolInfo, ToolResult

NAME = "reference"
DESCRIPTION = (
    "Look up a reference repository: another codebase named in the configuration that may be read for guidance (a library you integrate with, an example to follow). "
    "Call it without a name to list the references; with a name it makes sure the repository is available locally and returns its directory. "
    "Then use read, glob and grep on that directory, or ask the scout agent to explore it for you. References are read-only: never edit them."
)


class Input(BaseModel):
    name: Optional[str] = Field(default=None, description="The reference to open. Leave out to list the available references.")


def make(deps: ToolDeps) -> ToolInfo:
    service: ReferenceService = deps.extras["references"]

    async def execute(inp: Input, ctx: ToolContext) -> ToolResult:
        if not inp.name:
            return ToolResult(content=service.describe(), output={"references": service.names()})
        await deps.assert_permission(ctx, NAME, [inp.name], save=["*"])
        try:
            directory = await asyncio.to_thread(service.resolve, inp.name)
        except ReferenceError_ as exc:
            raise ToolError(str(exc)) from None
        return ToolResult(
            content=f"The reference {inp.name!r} is at {directory}\nIt is read-only. Use read, glob and grep on that directory (or the scout agent).",
            output={"name": inp.name, "directory": str(directory)}, metadata={"name": inp.name, "directory": str(directory)},
        )

    return ToolInfo(NAME, DESCRIPTION, Input, execute)
