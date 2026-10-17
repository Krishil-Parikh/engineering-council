import asyncio

import pytest

from coding_harness.runner import Runner
from coding_harness.types import Message, ModelReply, ToolCall
from coding_harness.workspace import Workspace


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    proj = tmp_path / "proj"
    proj.mkdir()
    return Workspace(proj, home=tmp_path / "home")


class ScriptedModel:
    """Plays back prepared replies and records what it was sent. A callable entry computes the reply from the messages."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    async def complete(self, *, system, messages, tools, tool_choice="auto", on_event=None, stage="", max_output_tokens=None):
        self.calls.append({"system": system, "messages": list(messages), "tools": [t.name for t in tools], "tool_choice": tool_choice, "stage": stage})
        if not self.replies:
            return ModelReply("done")
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        if callable(r):
            r = r(messages)
        if isinstance(r, str):
            return ModelReply(r)
        return r


_n = [0]


def call(name, **args):
    _n[0] += 1
    return ToolCall(f"c{_n[0]}", name, args)


def calls(*cs, text=""):
    return ModelReply(text, list(cs), finish="tool_calls")


def make_runner(ws, model, **kw):
    async def no_sleep(_):
        return None

    kw.setdefault("sleep", no_sleep)
    return Runner(ws, model, **kw)


def run(coro):
    return asyncio.run(coro)
