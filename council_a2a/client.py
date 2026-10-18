"""Calling an A2A agent over gRPC (the official `a2a-sdk` client with its gRPC transport)."""

from __future__ import annotations

import uuid
from typing import Any, Optional

import grpc
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_artifact_text, get_message_text, new_text_message
from a2a.types import a2a_pb2

from council_a2a.agent import TOKEN_HEADER


# a stopped agent should fail a call promptly instead of backing off for seconds
FAST_RECONNECT = [("grpc.initial_reconnect_backoff_ms", 100), ("grpc.min_reconnect_backoff_ms", 100), ("grpc.max_reconnect_backoff_ms", 500)]


class A2AError(Exception):
    pass


class _TokenCredentials(grpc.AuthMetadataPlugin):
    def __init__(self, token: str) -> None:
        self.token = token

    def __call__(self, context, callback) -> None:
        callback(((TOKEN_HEADER, f"Bearer {self.token}"),), None)


class A2AClient:
    """A caller identity (`sender`) with a connection to one agent at `address`."""

    def __init__(self, sender: str, address: str, token: Optional[str] = None, timeout: float = 900.0) -> None:
        self.sender, self.address, self.token, self.timeout = sender, address, token, timeout
        self._channel: Optional[grpc.aio.Channel] = None
        self._client = None

    async def _connect(self):
        if self._client is not None:
            return self._client
        if self.token:
            creds = grpc.composite_channel_credentials(grpc.local_channel_credentials(), grpc.metadata_call_credentials(_TokenCredentials(self.token)))
            channel = grpc.aio.secure_channel(self.address, creds, options=FAST_RECONNECT)
        else:
            channel = grpc.aio.insecure_channel(self.address, options=FAST_RECONNECT)
        self._channel = channel
        card = a2a_pb2.AgentCard(
            name=self.address, version="1.0.0", supported_interfaces=[a2a_pb2.AgentInterface(url=self.address, protocol_binding="GRPC", protocol_version="1.0")],
            capabilities=a2a_pb2.AgentCapabilities(streaming=False), default_input_modes=["text/plain"], default_output_modes=["text/plain"],
        )
        config = ClientConfig(streaming=False, supported_protocol_bindings=["GRPC"], grpc_channel_factory=lambda url: channel)
        self._client = ClientFactory(config).create(card)
        return self._client

    async def ask(self, text: str, topic: str = "", context_id: Optional[str] = None, group: Optional[list[str]] = None, extra: Optional[dict[str, Any]] = None) -> str:
        client = await self._connect()
        message = new_text_message(text, context_id=context_id or str(uuid.uuid4()), role=a2a_pb2.Role.ROLE_USER)
        message.metadata.update({"sender": self.sender, "topic": topic, "group": group or [], **(extra or {})})
        reply = ""
        try:
            async for response in client.send_message(a2a_pb2.SendMessageRequest(message=message)):
                if response.HasField("message"):
                    reply = get_message_text(response.message)
                elif response.HasField("task"):
                    reply = "\n".join(get_artifact_text(a) for a in response.task.artifacts) or reply
        except Exception as exc:  # noqa: BLE001
            raise A2AError(f"{self.address}: {type(exc).__name__}: {exc}") from exc
        return reply

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
            self._client = None
