"""The skill tool (opencode: tool/plugin/skill.ts). Loads a skill's instructions and its sampled resource list into the conversation.

`deps.extras["skills"]` is the SkillCatalog."""

from __future__ import annotations

from pydantic import BaseModel, Field

from harness import skill as Skill
from harness.tool.builtin.deps import ToolDeps
from harness.tool.info import ToolContext, ToolError, ToolInfo, ToolResult

NAME = "skill"
DESCRIPTION = "\n".join([
    "Load a specialized skill's instructions and resources into the current conversation when the task at hand matches its description.",
    "",
    "The skill ID must match an available skill or a skill explicitly referenced by the user.",
])


class Input(BaseModel):
    id: str = Field(description="The ID of an available skill or a skill explicitly referenced by the user")


def make(deps: ToolDeps) -> ToolInfo:
    catalog: Skill.SkillCatalog = deps.extras["skills"]

    async def execute(inp: Input, ctx: ToolContext) -> ToolResult:
        skill = catalog.get(inp.id)
        if skill is None:
            raise ToolError(f"Unable to load skill {inp.id}")
        try:
            await deps.assert_permission(ctx, NAME, [skill.id], save=[skill.id])
            prepared = Skill.prepare(skill)
        except Exception as exc:  # noqa: BLE001
            from harness.permission import DeclinedError

            if isinstance(exc, DeclinedError):
                raise
            raise ToolError(f"Unable to load skill {inp.id}", exc) from None
        output = {"name": skill.name, **prepared}
        return ToolResult(content=prepared["output"], output=output, metadata={"name": skill.name, "directory": prepared["directory"]})

    return ToolInfo(NAME, DESCRIPTION, Input, execute)
