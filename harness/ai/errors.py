"""Provider failure classification (opencode: packages/ai/src/provider-error.ts and schema/errors.ts).

Every model failure is mapped to one typed reason so the runner can decide what to do: compact and retry on a context overflow,
wait and retry on a rate limit or server error, stop on an authentication or quota problem. Classification records affirmative
evidence: unrecognized failures stay `unknown` and are retried, because transient failures arrive in unpredictable shapes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

_I = re.IGNORECASE

_OVERFLOW_PATTERNS = [re.compile(p, _I) for p in [
    r"prompt is too long",
    r"input is too long for requested model",
    r"exceeded this model context window limit",
    r"exceeds the context window",
    r"exceeds (?:the )?(?:model'?s )?maximum context length(?: of [\d,]+ tokens?|\s*\([\d,]+\))",
    r"input token count.*exceeds the maximum",
    r"number of input tokens exceeds maximum length",
    r"tokens in request more than max tokens allowed",
    r"maximum prompt length is \d+",
    r"reduce the length of the messages",
    r"requested input length \d+ exceeds maximum input length",
    r"maximum context length is \d+ tokens",
    r"exceeds (?:the )?maximum allowed input length of [\d,]+ tokens?",
    r"input(?: \(\d+ tokens\))? is longer than the model'?s context length",
    r"exceeds the limit of \d+",
    r"exceeds the available context size",
    r"greater than the context length",
    r"`inputs` tokens \+ `max_new_tokens` must be <= \d+",
    r"context window exceeds limit",
    r"exceeded model token limit",
    r"context[_ ]length[_ ]exceeded",
    r"context length is only \d+ tokens",
    r"input length.*exceeds.*context length",
    r"prompt (?:too long|超长)",
    r"too large for model with \d+ maximum context length",
    r"prompt has [\d,]+ tokens?, but the configured context size is [\d,]+ tokens?",
    r"model_context_window_exceeded",
    r"range of input length should be",
    r"too many tokens",
    r"token limit exceeded",
    r"request_too_large",
]]
_PAYLOAD_PATTERNS = [re.compile(p, _I) for p in [r"request entity too large", r"payload too large", r"request too large"]]
_OVERFLOW_EXCLUSIONS = [re.compile(p, _I) for p in [r"^(throttling error|service unavailable):", r"rate limit", r"too many requests", r"max[_ ]tokens must be less than"]]
_NO_BODY = re.compile(r"^4(?:00|13)\s*(status code)?\s*\(no body\)", _I)


def is_context_overflow(message: str) -> bool:
    return not any(p.search(message) for p in _OVERFLOW_EXCLUSIONS) and (any(p.search(message) for p in _OVERFLOW_PATTERNS) or bool(_NO_BODY.search(message)))


def is_payload_too_large(message: str) -> bool:
    return any(p.search(message) for p in _PAYLOAD_PATTERNS)


# --------------------------------------------------------------------------- reasons


@dataclass
class Reason:
    message: str
    body: Optional[str] = None
    http_headers: dict[str, str] = field(default_factory=dict)
    tag: str = "UnknownProvider"
    classification: Optional[str] = None  # InvalidRequest: context-overflow | payload-too-large; InvalidProviderOutput: incomplete-stream
    retry_after_ms: Optional[float] = None
    transport_delivery: Optional[str] = None
    transport_operation: Optional[str] = None
    code: Optional[str] = None


class AIError(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason.message)
        self.reason = reason

    @property
    def tag(self) -> str:
        return self.reason.tag


def error(tag: str, message: str, **kw: Any) -> AIError:
    return AIError(Reason(message=message, tag=tag, **kw))


def is_context_overflow_failure(failure: Any) -> bool:
    return isinstance(failure, AIError) and failure.reason.tag == "InvalidRequest" and failure.reason.classification == "context-overflow"


def is_retryable(err: AIError) -> bool:
    """Rate limits, provider-side failures, transport failures that did not deliver an accepted write, unrecognised failures."""
    override = err.reason.http_headers.get("x-should-retry")
    if override == "true":
        return True
    if override == "false":
        return False
    tag = err.reason.tag
    if tag in ("RateLimit", "ProviderInternal", "UnknownProvider"):
        return True
    if tag == "Transport":
        d = err.reason.transport_delivery
        return d != "rejected" and (d != "accepted" or err.reason.transport_operation == "read")
    if tag == "InvalidProviderOutput":
        return err.reason.classification == "incomplete-stream"
    return False  # Authentication, QuotaExceeded, ContentPolicy, InvalidRequest, UnsupportedOperation, NoRoute, Timeout


# --------------------------------------------------------------------------- classification from a raw failure

_QUOTA_CODES = {"insufficient_quota", "usage_not_included", "billing_error", "gousagelimiterror", "freeusagelimiterror", "creditlimitexceeded"}
_AUTH_CODES = {"authentication_error", "permission_error", "permission_denied", "api_key_invalid"}
_SERVER_CODES = {"api_error", "internal_error", "internalserverexception", "modelstreamerrorexception", "overloaded_error", "server_error", "server_is_overloaded", "slow_down", "serviceunavailableexception"}
_INVALID_REQUEST_CODES = {"model_not_found", "invalid_prompt", "invalid_request", "invalid_request_error", "validationexception"}
_CONTENT_POLICY_CODES = {"content_filter", "content_moderation", "responsibleaipolicyviolation", "content_policy_violation", "image_content_policy_violation", "refusal"}
_GATEWAY_LABEL = re.compile(r"^[^:\n]+: \[([A-Za-z0-9_.-]+)\]")
_AUTH_TEXT = re.compile(r"incorrect api key provided", _I)
_RATE_LIMIT_TEXT = re.compile(r"rate increased too quickly|rate[-_\s]?limit|too[_\s]?many[_\s]?requests", _I)
_QUOTA_TEXT = re.compile(r"insufficient[-_\s]?(?:quota|balance)|quota[-_\s]?exceeded|budget exceeded|usage limit|limit exhausted|package has expired|plan does not yet include", _I)
_CONTENT_POLICY_TEXT = re.compile(r"violating our usage policy|blocked by content filtering policy|content[-_\s]?policy|rejected as a result of our safety system|detected potentially unsafe or sensitive content", _I)
_SERVER_ERROR_TEXT = re.compile(
    r"\b(?:try again|(?:please |you can )?retry (?:the |this |your )?request|try (?:the |this |your )?request again|(?:currently |temporarily )?at capacity|overloaded|temporarily unavailable|service[-_\s]?unavailable|(?:server|internal)[-_\s]?error|server (?:is )?busy|provider returned (?:an )?error|resource[-_\s]?exhausted|upstream (?:connect|connection|request)|request buffer limit while retrying upstream)\b",
    _I,
)


def _is_record(v: Any) -> bool:
    return isinstance(v, dict)


def _provider_codes(value: Any) -> list[str]:
    decoded = value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return []
    if not _is_record(decoded):
        return []
    err = decoded.get("error") if _is_record(decoded.get("error")) else None
    inner = err.get("innererror") if err and _is_record(err.get("innererror")) else None
    metadata = err.get("metadata") if err and _is_record(err.get("metadata")) else None
    response = decoded.get("response") if _is_record(decoded.get("response")) else None
    response_error = response.get("error") if response and _is_record(response.get("error")) else None
    exception = decoded.get("exception") if _is_record(decoded.get("exception")) else None
    out: list[Any] = [
        decoded.get("code"),
        decoded.get("name") if isinstance(decoded.get("errors"), list) else None,
        decoded.get("error_type"),
        err and err.get("code"), err and err.get("type"), err and err.get("status"), err and err.get("error_type"),
        *([d.get("reason") if _is_record(d) else None for d in err.get("details")] if err and isinstance(err.get("details"), list) else []),
        inner and inner.get("code"), metadata and metadata.get("error_type"), response_error and response_error.get("code"),
        response and response.get("error_type"), exception and exception.get("type"),
    ]
    return [c for c in out if isinstance(c, str)]


def provider_error_message(body: str) -> Optional[str]:
    """The human-readable message from a JSON error body, using the common layouts in priority order."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not _is_record(data):
        return None
    def nonblank(v: Any) -> Optional[str]:
        return v if isinstance(v, str) and re.search(r"\S", v) else None
    e = data.get("error")
    for cand in (e.get("message") if _is_record(e) else None, e, data.get("message"), data.get("Message"), data.get("detail")):
        if (m := nonblank(cand)):
            return m
    errs = data.get("errors")
    if isinstance(errs, list) and errs and _is_record(errs[0]) and (m := nonblank(errs[0].get("message"))):
        return m
    return None


def classify_provider_failure(
    message: str, *, status: Optional[int] = None, raw_body: Optional[str] = None, data: Any = None, retry_after_ms: Optional[float] = None,
    headers: Optional[dict[str, str]] = None,
) -> AIError:
    body = raw_body or ""
    details = dict(message=message, body=raw_body, http_headers=headers or {})
    m = _GATEWAY_LABEL.match(message)
    codes = [c.lower() for c in [*_provider_codes(data), *_provider_codes(body), *_provider_codes(message), *([m.group(1)] if m else [])]]
    text = "\n".join(v for v in (message, body) if v)
    client_scoped = status is None or 400 <= status < 500

    if client_scoped and ("context_length_exceeded" in codes or "model_context_window_exceeded" in codes or "request_too_large" in codes or is_context_overflow(text)):
        return error("InvalidRequest", classification="context-overflow", **details)
    if status == 413 or is_payload_too_large(text):
        return error("InvalidRequest", classification="payload-too-large", **details)
    if any(c in _CONTENT_POLICY_CODES for c in codes) or (client_scoped and _CONTENT_POLICY_TEXT.search(message)):
        return error("ContentPolicy", **details)
    if status == 402 or any(c in _QUOTA_CODES for c in codes) or (status == 429 and _QUOTA_TEXT.search(text)):
        return error("QuotaExceeded", **details)
    if status in (401, 403) or any(c in _AUTH_CODES for c in codes) or (status == 400 and _AUTH_TEXT.search(text)):
        return error("Authentication", **details)
    if status == 429 or any("rate_limit" in c or c in ("too_many_requests", "throttlingexception") for c in codes) or _RATE_LIMIT_TEXT.search(text):
        return error("RateLimit", retry_after_ms=retry_after_ms, **details)
    if (
        status in (408, 409)
        or (status is not None and status >= 500)
        or ((status is None or status < 400) and (
            (not any(c in _INVALID_REQUEST_CODES for c in codes) and _SERVER_ERROR_TEXT.search(text))
            or any(c in _SERVER_CODES or "exhausted" in c or "unavailable" in c for c in codes)
        ))
    ):
        return error("ProviderInternal", retry_after_ms=retry_after_ms, **details)
    if any(c in _INVALID_REQUEST_CODES for c in codes):
        return error("InvalidRequest", **details)
    if status is not None and 400 <= status < 500:
        return error("InvalidRequest", **details)
    return error("UnknownProvider", **details)
