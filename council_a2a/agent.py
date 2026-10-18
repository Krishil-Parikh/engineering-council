"""One agent as an A2A server, over gRPC (the official `a2a-sdk`).

An agent has a name, a description, and a *handler*: an async function from an `Inbound` message to a reply string. Everything else is the
protocol: the agent publishes an Agent Card, receives `SendMessage` calls, answers each with a single Message, and refuses callers that do
not present the shared token when one is configured."""

from __future__ import annotations

import asyncio
import logging
import hmac
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import grpc
from a2a.helpers.proto_helpers import get_message_text, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue_v2 import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler, GrpcHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import a2a_pb2, a2a_pb2_grpc
from google.protobuf import json_format

TOKEN_HEADER = "authorization"


@dataclass
class Inbound:
    sender: str
    recipient: str
    text: str
    topic: str = ""
    context_id: str = ""  # one conversation: messages that share it belong together
    group: list[str] = field(default_factory=list)  # everyone in a group conversation (empty for a direct one)
    metadata: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[Inbound], Awaitable[str]]


class _Executor(AgentExecutor):
    def __init__(self, name: str, handler: Handler) -> None:
        self.name, self.handler = name, handler

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        meta = json_format.MessageToDict(message.metadata) if message is not None and message.HasField("metadata") else {}
        inbound = Inbound(
            sender=str(meta.get("sender", "")), recipient=self.name, text=get_message_text(message) if message is not None else "",
            topic=str(meta.get("topic", "")), context_id=context.context_id or "", group=list(meta.get("group", [])), metadata=meta,
        )
        try:
            reply = await self.handler(inbound)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the caller gets the failure as text rather than a dead connection
            reply = f"(error: {type(exc).__name__}: {exc})"
        await event_queue.enqueue_event(new_text_message(reply, context_id=context.context_id))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("conversations are single messages; there is nothing to cancel")


class _TokenInterceptor(grpc.aio.ServerInterceptor):
    def __init__(self, token: str) -> None:
        self.token = token

    async def intercept_service(self, continuation, handler_call_details):
        metadata = dict(handler_call_details.invocation_metadata or ())
        supplied = str(metadata.get(TOKEN_HEADER, ""))
        if hmac.compare_digest(supplied, f"Bearer {self.token}"):
            return await continuation(handler_call_details)

        def deny(request, context):  # noqa: ARG001
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "missing or wrong token")

        async def deny_async(request, context):  # noqa: ARG001
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "missing or wrong token")

        return grpc.unary_unary_rpc_method_handler(deny_async)


class A2AAgent:
    def __init__(self, name: str, handler: Handler, description: str = "", skill: str = "", token: Optional[str] = None, host: str = "127.0.0.1", port: int = 0) -> None:
        self.name, self.description, self.skill, self.token, self.host, self.port = name, description or name, skill, token, host, port
        self.handler = handler
        self._server: Optional[grpc.aio.Server] = None
        self.card: Optional[a2a_pb2.AgentCard] = None

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    def _card(self) -> a2a_pb2.AgentCard:
        skills = [a2a_pb2.AgentSkill(id=self.skill.lower() or "general", name=self.skill or "general", description=self.description, tags=[self.skill.lower()] if self.skill else [])]
        return a2a_pb2.AgentCard(
            name=self.name, description=self.description, version="1.0.0",
            supported_interfaces=[a2a_pb2.AgentInterface(url=self.address, protocol_binding="GRPC", protocol_version="1.0")],
            capabilities=a2a_pb2.AgentCapabilities(streaming=False), default_input_modes=["text/plain"], default_output_modes=["text/plain"], skills=skills,
        )

    async def start(self) -> "A2AAgent":
        interceptors = [_TokenInterceptor(self.token)] if self.token else []
        server = grpc.aio.server(interceptors=interceptors)
        if self.token:  # call credentials only travel over a secure channel; "local" credentials are for loopback connections
            self.port = server.add_secure_port(f"{self.host}:{self.port}", grpc.local_server_credentials())
        else:
            self.port = server.add_insecure_port(f"{self.host}:{self.port}")
        self.card = self._card()
        handler = DefaultRequestHandler(_Executor(self.name, self.handler), InMemoryTaskStore(), self.card)
        a2a_pb2_grpc.add_A2AServiceServicer_to_server(GrpcHandler(handler), server)
        await server.start()
        self._server = server
        return self

    async def stop(self) -> None:
        if self._server is not None:
            await self._server.stop(grace=0.5)
            self._server = None

# The SDK logs a warning each time a request finishes before its event dispatcher is joined; it is harmless and would otherwise print on every call.
logging.getLogger("a2a.server.events.event_queue_v2").setLevel(logging.ERROR)
