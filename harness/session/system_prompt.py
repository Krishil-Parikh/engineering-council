"""Default system prompt (opencode: packages/core/src/session/system-prompt.ts)."""

from __future__ import annotations

from pathlib import Path

PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text(encoding="utf-8")


def render(prompt: str, tools: list[str]) -> str:
    instructions: list[str] = []
    if "shell" in tools:
        instructions += [
            "- Prefer dedicated tools over shell commands; fall back to the shell when a tool cannot do what you need.",
            "- Do not chain shell commands with separators like `echo \"====\";` or `printf '---'`; the output becomes noisy in a way that makes the user's side of the conversation worse.",
        ]
    if "write" in tools:
        instructions.append("- Use the write tool to create files or completely replace their content. Prefer using the edit tool for targeted changes.")
    if "edit" in tools:
        instructions.append(
            "- Use the edit tool for targeted changes to existing text files. It replaces the exact text in `oldString` with `newString`, and the values must differ. "
            "By default, `oldString` must occur exactly once. If it occurs multiple times, include more surrounding context to make it unique or set `replaceAll` to true to replace every occurrence."
        )
    return prompt.replace("${TOOL_GUIDANCE}", "\n".join(instructions))


def make(tools: list[str]) -> str:
    return render(PROMPT, tools)
