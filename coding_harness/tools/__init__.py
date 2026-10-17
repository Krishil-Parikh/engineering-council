from coding_harness.tools.base import Tool, ToolContext, ToolFailure
from coding_harness.tools.files import EditTool, GlobTool, GrepTool, ReadTool, WriteTool
from coding_harness.tools.misc import QuestionTool, SkillTool, SubagentTool, TodoTool, WebFetchTool
from coding_harness.tools.patch import PatchTool
from coding_harness.tools.shell import ShellTool


def builtin_tools() -> list[Tool]:
    return [ReadTool(), GlobTool(), GrepTool(), EditTool(), WriteTool(), PatchTool(), ShellTool(), WebFetchTool(), SkillTool(), QuestionTool(), TodoTool(), SubagentTool()]


__all__ = ["Tool", "ToolContext", "ToolFailure", "builtin_tools"]
