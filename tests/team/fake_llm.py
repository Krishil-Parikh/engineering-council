"""A model that behaves from the conversation it is shown, so a whole team can be driven without a real model.

Rules are (regex, steps). The newest user message that matches a rule picks it; `steps` is what to do in order: ("tool", name, args) calls a
tool, ("text", reply) answers. The step index is the number of tool results since that message, so each tool result advances the script."""

from __future__ import annotations

import re
from typing import Any, Callable, Union

from harness.ai import events as E
from harness.ai import types as T
from tests.harness.test_runner import text_reply, tool_reply

Step = tuple
Steps = Union[list[Step], Callable[[str], list[Step]]]


class TeamLLM:
    def __init__(self) -> None:
        self.rules: list[tuple[re.Pattern, Steps]] = []
        self.requests: list[T.LLMRequest] = []
        self.matched: list[str] = []

    def on(self, pattern: str, steps: Steps) -> "TeamLLM":
        self.rules.append((re.compile(pattern, re.S), steps))
        return self

    @staticmethod
    def _text(message: T.Message) -> str:
        return "\n".join(p.text for p in message.content if isinstance(p, T.TextPart))

    async def stream(self, request: T.LLMRequest):
        self.requests.append(request)
        messages = request.messages
        for index in range(len(messages) - 1, -1, -1):
            m = messages[index]
            if m.role != "user":
                continue
            text = self._text(m)
            for pattern, steps in self.rules:
                if pattern.search(text):
                    after = sum(1 for x in messages[index + 1:] if x.role == "tool")
                    script = steps(text) if callable(steps) else steps
                    self.matched.append(pattern.pattern)
                    step = script[after] if after < len(script) else ("text", "done")
                    events = tool_reply((step[1], step[2])) if step[0] == "tool" else text_reply(step[1])
                    for ev in events:
                        yield ev
                    return
        for ev in text_reply("(no scripted behaviour for this conversation)"):
            yield ev
