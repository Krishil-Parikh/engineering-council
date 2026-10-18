"""The meeting's model calls, carried over A2A.

Every developer in the meeting (and the scrum master) is an A2A agent with a gRPC server. When the meeting needs a developer to think, the
request is sent to that developer's agent as an A2A message; the agent makes the model call and answers with the result. `A2ALLM` wraps any
`LLM` (the real Gemini client, or a fake in tests) so the rest of the meeting does not change: it still calls `llm.generate(...)`.

Which agent gets a call is read from the stage name (`blind:DEV_3`, `talk2:DEV_1`, `proposal:DEV_5`, ...); calls that belong to no single
developer (question curation, decisions, document revision) go to the scrum master. Errors keep their type across the wire, so quota,
authentication and malformed-output handling work exactly as before. Schemas are named by import path, so the same call works when the
agents run in another process."""

from __future__ import annotations

import importlib
import json
from typing import Any, Optional, TypeVar

from council_a2a import A2ANetwork
from meetings import gemini_client as G
from meetings.gemini_client import LLM, LLMError
from meetings.models import AGENT_IDS, SCRUM_MASTER

T = TypeVar("T")
ERROR_TYPES = {cls.__name__: cls for cls in (G.AuthError, G.ModelError, G.QuotaError, G.TransientError, G.MalformedOutputError, G.LLMError)}


def agent_for(stage: str) -> str:
    last = stage.split(":")[-1]
    return last if last in AGENT_IDS else SCRUM_MASTER


def _schema_path(schema: type) -> str:
    return f"{schema.__module__}:{schema.__qualname__}"


def _load_schema(path: str) -> type:
    module, _, name = path.partition(":")
    obj: Any = importlib.import_module(module)
    for part in name.split("."):
        obj = getattr(obj, part)
    return obj


class A2ALLM:
    """An `LLM` whose generate() travels to the right developer's A2A agent."""

    def __init__(self, inner: LLM, network: A2ANetwork, sender: str = "meeting") -> None:
        self.inner, self.network, self.sender = inner, network, sender

    # the parts of the LLM protocol that are plain state live on the wrapped client
    @property
    def usage(self) -> list[dict]:
        return self.inner.usage

    @property
    def observer(self):
        return self.inner.observer

    @observer.setter
    def observer(self, value) -> None:
        self.inner.observer = value

    async def generate(self, prompt: str, schema: type[T], *, stage: str, system: str = "") -> T:
        recipient = agent_for(stage)
        request = json.dumps({"prompt": prompt, "system": system, "stage": stage, "schema": _schema_path(schema)})
        raw = await self.network.ask(self.sender, recipient, request, topic=stage)
        try:
            reply = json.loads(raw)
        except ValueError:
            raise LLMError(f"{recipient} could not answer {stage}: {raw[:200]}") from None
        if "error" in reply:
            raise ERROR_TYPES.get(reply["error"]["type"], LLMError)(reply["error"]["message"])
        return schema.model_validate(reply["result"])  # type: ignore[attr-defined]

    async def close(self) -> None:
        await self.network.close()


async def serve_meeting(inner: LLM, audit_path: Optional[Any] = None, token: Optional[str] = None) -> A2ALLM:
    """Starts one A2A agent per developer plus the scrum master, each answering model requests through `inner`."""
    network = A2ANetwork(token=token, audit_path=audit_path)

    def handler_for(name: str):
        async def handle(inbound) -> str:
            request = json.loads(inbound.text)
            try:
                result = await inner.generate(request["prompt"], _load_schema(request["schema"]), stage=request["stage"], system=request["system"])
            except LLMError as exc:
                return json.dumps({"error": {"type": type(exc).__name__, "message": str(exc)}})
            return json.dumps({"result": result.model_dump(mode="json")})

        return handle

    for name in (*AGENT_IDS, SCRUM_MASTER):
        await network.add(name, handler_for(name), "scrum master" if name == SCRUM_MASTER else "developer in the pod meeting")
    return A2ALLM(inner, network)
