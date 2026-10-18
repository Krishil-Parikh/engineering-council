from harness.legacy.tools.base import Tool, ToolContext, ToolFailure
from harness.legacy.tools.files import EditTool, GlobTool, GrepTool, ReadTool, WriteTool
from harness.legacy.tools.misc import QuestionTool, SkillTool, SubagentTool, TodoTool, WebFetchTool
from harness.legacy.tools.patch import PatchTool
from harness.legacy.tools.shell import ShellTool


def builtin_tools() -> list[Tool]:
    return [ReadTool(), GlobTool(), GrepTool(), EditTool(), WriteTool(), PatchTool(), ShellTool(), WebFetchTool(), SkillTool(), QuestionTool(), TodoTool(), SubagentTool()]


__all__ = ["Tool", "ToolContext", "ToolFailure", "builtin_tools"]
