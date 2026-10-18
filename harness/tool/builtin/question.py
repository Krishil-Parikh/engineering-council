"""The question tool (opencode: tool/plugin/question.ts). Puts structured questions to the user through a form and returns their answers.

`deps.extras["forms"]` is the FormService. A dismissal without a message raises QuestionCancelled, which is not model-facing output: the
step ends. A dismissal carrying a message (a non-interactive client) is ordinary feedback and the model continues."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from harness.permission import DeclinedError
from harness.tool.builtin.deps import ToolDeps
from harness.tool.info import ToolContext, ToolError, ToolInfo, ToolResult

NAME = "question"
DESCRIPTION = """Use this tool when you need to ask the user questions during execution. This allows you to:
1. Gather user preferences or requirements
2. Clarify ambiguous instructions
3. Get decisions on implementation choices as you work
4. Offer choices to the user about what direction to take.

Usage notes:
- A "Type your own answer" option is added automatically; don't include a separate option for free form answers
- Set `multiple: true` to allow selecting more than one option
- If you recommend a specific option, make that the first option in the list and add "(Recommended)" at the end of the label"""


class QuestionCancelled(DeclinedError):
    """A dismissal ends the step like a declined permission does; it never becomes tool output."""

    def __init__(self) -> None:
        super().__init__("The user dismissed this question")


class Option(BaseModel):
    label: str = Field(description="Display text (1-5 words, concise)")
    description: str = Field(description="Explanation of choice")


class Prompt(BaseModel):
    question: str = Field(description="Complete question")
    header: str = Field(description="Very short label (max 30 chars)")
    options: list[Option] = Field(description="Available choices")
    multiple: Optional[bool] = Field(default=None, description="Allow selecting multiple choices")


class Input(BaseModel):
    questions: list[Prompt] = Field(min_length=1, description="Questions to ask")


def to_model_content(questions: list[Prompt], answers: list[list[str]]) -> str:
    formatted = ", ".join(f'"{q.question}"="{", ".join(answers[i]) if i < len(answers) and answers[i] else "Unanswered"}"' for i, q in enumerate(questions))
    return f"User has answered your questions: {formatted}. You can now continue with the user's answers in mind."


def to_field(question: Prompt, index: int) -> dict[str, Any]:
    return {
        "key": f"q{index}", "title": question.header, "description": question.question,
        "type": "multiselect" if question.multiple is True else "string",
        "options": [{"value": o.label, "label": o.label, "description": o.description} for o in question.options],
        "custom": True,
    }


def make(deps: ToolDeps) -> ToolInfo:
    async def execute(inp: Input, ctx: ToolContext) -> ToolResult:
        try:
            await deps.assert_permission(ctx, "question", ["*"])
        except Exception as exc:  # noqa: BLE001
            from harness.permission import DeclinedError

            if isinstance(exc, DeclinedError):
                raise
            raise ToolError("Permission denied: question", exc) from None
        state = await deps.extras["forms"].ask(
            ctx.session_id, "Questions", [to_field(q, i) for i, q in enumerate(inp.questions)],
            metadata={"kind": "question", "tool": {"messageID": ctx.message_id, "id": ctx.id}},
        )
        if state["status"] == "cancelled" and state.get("message") is not None:
            raise ToolError(state["message"])
        if state["status"] == "cancelled":
            raise QuestionCancelled()
        answers: list[list[str]] = []
        for i in range(len(inp.questions)):
            value = state["answer"].get(f"q{i}")
            answers.append([] if value is None else list(value) if isinstance(value, (list, tuple, set)) else [str(value)])
        return ToolResult(content=to_model_content(inp.questions, answers), output={"answers": answers}, metadata={"answers": answers})

    return ToolInfo(NAME, DESCRIPTION, Input, execute)
