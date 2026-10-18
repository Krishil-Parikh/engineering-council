import asyncio
from typing import AsyncIterator

import pytest

from harness.ai import events as E
from harness.ai import types as T
from harness.ai.errors import AIError
from harness.ai.model import ModelLimit, ResolvedModel
from harness.db.database import Database
from harness.schema import message as M
from harness.session import history
from harness.session.compaction import AgentInfo, Compaction, Loaded, Settings
from harness.session.store import SessionStore
from harness.session.usage import Usage

SUMMARY = "## Objective\n- build the thing\n\n## Next Move\n1. finish"


class FakeLLM:
    """Plays back scripted replies. Each entry is a string (the reply text), an AIError/Exception to raise, or a list of events."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[T.LLMRequest] = []

    async def stream(self, request: T.LLMRequest) -> AsyncIterator[E.LLMEvent]:
        self.requests.append(request)
        item = self.script.pop(0) if self.script else SUMMARY
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, str):
            item = [E.TextDelta(item), E.StepFinish(Usage(non_cached_input_tokens=100, visible_output_tokens=20)), E.Finish("stop")]
        for ev in item:
            yield ev


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


@pytest.fixture
def store(db):
    return SessionStore(db)


MODEL = ResolvedModel(M.ModelRef(provider_id="google", id="gemini-test"), "google", ModelLimit(context=100_000, output=8_000))


def user(text):
    return M.User(text=text)


def assistant(text="", tools=(), tokens=None, model=None):
    content = [M.AssistantText(text=text)] if text else []
    content += list(tools)
    return M.Assistant(agent="build", model=model or MODEL.ref, content=content, finish="stop", tokens=tokens)


def tool(name="read", out="file contents", call_id="c1", inp=None):
    return M.AssistantTool(id=call_id, name=name, state=M.ToolStateCompleted(input=inp or {"path": "a.py"}, content=[M.TextContent(text=out)]))


def loaded(store, session, model=MODEL, initial="", agent=None):
    return Loaded(session=store.get(session.id), agent=agent or AgentInfo("build"), model=model, initial=initial, messages=history.load(store, session.id))


def make_compaction(store, llm, **kw):
    async def no_sleep(_):
        return None

    return Compaction(store, llm, settings=kw.pop("settings", Settings()), sleep=no_sleep, **kw)


def run(coro):
    return asyncio.run(coro)
