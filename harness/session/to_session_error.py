"""Turning exceptions into the structured errors stored on messages (opencode: packages/core/src/session/to-session-error.ts)."""

from __future__ import annotations

from typing import Any

from harness.ai.errors import AIError, Reason
from harness.permission import BlockedError, CorrectedError
from harness.schema.message import SessionError
from harness.tool.info import ToolError

_TYPES = {
    "RateLimit": "provider.rate-limit",
    "Authentication": "provider.auth",
    "QuotaExceeded": "provider.quota",
    "ContentPolicy": "provider.content-filter",
    "Transport": "provider.transport",
    "ProviderInternal": "provider.internal",
    "InvalidProviderOutput": "provider.invalid-output",
    "InvalidRequest": "provider.invalid-request",
    "UnsupportedOperation": "provider.unsupported-operation",
    "NoRoute": "provider.no-route",
    "UnknownProvider": "provider.unknown",
    "Timeout": "provider.timeout",
}


class StepFailedError(Exception):
    def __init__(self, error: SessionError) -> None:
        super().__init__(error.message)
        self.error = error


def _provider_error(kind: str, reason: Reason) -> SessionError:
    return SessionError(type=kind, message=reason.message, response={"body": reason.body} if reason.body is not None else None)


def to_session_error(cause: Any) -> SessionError:
    if isinstance(cause, AIError):
        return _provider_error(_TYPES.get(cause.reason.tag, "provider.unknown"), cause.reason)
    if isinstance(cause, BlockedError):
        return SessionError(type="permission.rejected", message=str(cause))
    if isinstance(cause, CorrectedError):
        return SessionError(type="permission.rejected", message=cause.feedback)
    if isinstance(cause, ToolError):
        if cause.error is None:
            return SessionError(type="tool.execution", message=cause.message)
        unwrapped = to_session_error(cause.error)
        return SessionError(type="tool.execution", message=cause.message, status=unwrapped.status, response=unwrapped.response) if unwrapped.message == "" else unwrapped
    if isinstance(cause, StepFailedError):
        return cause.error
    return SessionError(type="unknown", message=str(cause) if isinstance(cause, BaseException) else str(cause))


def content_filter_error(summary: str, raw: str | None = None, category: str | None = None) -> SessionError:
    head = summary if category is None else f"{summary} ({category})"
    return SessionError(type="provider.content-filter", message=": ".join(p for p in (head, raw) if p))
