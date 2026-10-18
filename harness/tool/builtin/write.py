"""The write tool (opencode: tool/plugin/write.ts)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from harness import file_mutation as FM
from harness.tool.builtin.deps import ToolDeps
from harness.tool.file_diff import file_diff
from harness.tool.info import ToolContext, ToolError, ToolInfo, ToolOptions, ToolResult
from harness.util import bom as Bom

NAME = "write"
DESCRIPTION = (
    "Writes a file to the local filesystem, overwriting if one exists.\n\nMissing parent directories are created automatically.\n\n"
    "Use this tool to create new files or overwrite existing files. For partial changes, use the edit tool instead."
)


class Input(BaseModel):
    path: str = Field(description="Path to the file to write to")
    content: str = Field(description="Content to write to the file")


def make(deps: ToolDeps) -> ToolInfo:
    async def execute(inp: Input, ctx: ToolContext) -> ToolResult:
        try:
            target = deps.access.resolve(inp.path, "file")
            await deps.access.authorize_external([target], deps.invocation(ctx))
            try:
                current = FM.read_text(target.absolute)
            except FileNotFoundError:
                current = None
            nxt = Bom.split(inp.content)
            preview = file_diff(target.resource, current.text if current else "", nxt.text, "modified" if current else "added")
            await deps.assert_permission(ctx, "edit", [target.resource], save=["*"], metadata={"files": [preview.to_json()]})
            async with FM.with_lock([target.absolute]):
                result = FM.write_text_preserving_bom(target.absolute, target.resource, inp.content)
        except (OSError, FM.FileKindError) as exc:
            raise ToolError(f"Unable to write {inp.path}", exc) from None
        output = {"operation": "write", "target": result.target, "resource": result.resource, "existed": result.existed}
        return ToolResult(content=f"{'Wrote' if result.existed else 'Created'} file successfully: {result.resource}", output=output)

    return ToolInfo(NAME, DESCRIPTION, Input, execute, ToolOptions(permission="edit"))
