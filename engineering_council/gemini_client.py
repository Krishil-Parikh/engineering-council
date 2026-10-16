"""The single Gemini adapter. Nothing else in the app imports the SDK or sees SDK response types."""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from typing import Awaitable, Callable, Optional, Protocol, TypeVar

from pydantic import BaseModel

from engineering_council.config import Settings

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Base class for model-call failures that the CLI can show to the user."""


class AuthError(LLMError):
    pass


class ModelError(LLMError):
    pass


class QuotaError(LLMError):
    pass


class TransientError(LLMError):
    pass


class MalformedOutputError(LLMError):
    pass


class LLM(Protocol):
    """What the rest of the app depends on. Tests provide a fake implementing this."""

    usage: list[dict]

    async def generate(self, prompt: str, schema: type[T], *, stage: str, system: str = "") -> T: ...


def extract_json(text: str) -> str:
    """Strip markdown fences / chatter and return the outermost JSON object text."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model output")
    return text[start : end + 1]


def classify_error(exc: Exception) -> tuple[str, bool]:
    """Return (kind, retryable). kind in auth|model|quota|bad_request|transient|unknown."""
    code = getattr(exc, "code", None)
    low = str(exc).lower()
    if code in (401, 403) or "api key" in low or "api_key_invalid" in low or "permission_denied" in low:
        return "auth", False
    if code == 404 or "is not found" in low or "not supported for generatecontent" in low:
        return "model", False
    if code == 429 or "resource_exhausted" in low or "quota" in low:
        return "quota", True
    if isinstance(code, int) and 500 <= code < 600:
        return "transient", True
    if isinstance(code, int) and 400 <= code < 500:
        return "bad_request", False
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)):
        return "transient", True
    name = type(exc).__name__.lower()
    if any(k in name for k in ("timeout", "connect", "network", "protocol", "remote")):
        return "transient", True
    return "unknown", False


def _looks_like_schema_rejection(exc: Exception) -> bool:
    low = str(exc).lower()
    return isinstance(exc, (ValueError, TypeError)) or (
        getattr(exc, "code", None) == 400 and "schema" in low
    )


class GeminiClient:
    def __init__(
        self,
        settings: Settings,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        from google import genai  # imported here so tests and --help work without the SDK configured
        from google.genai import types

        self._settings = settings
        self._types = types
        self._sleep = sleep
        self._use_schema = True  # flipped off if the SDK/model rejects a response_schema
        self._client = genai.Client(
            api_key=settings.api_key,
            http_options=types.HttpOptions(timeout=int(settings.request_timeout_s * 1000)),
        )
        self.usage: list[dict] = []

    async def generate(self, prompt: str, schema: type[T], *, stage: str, system: str = "") -> T:
        s = self._settings
        feedback = ""
        last: Optional[Exception] = None
        for attempt in range(1, s.max_attempts + 1):
            started = time.monotonic()
            try:
                text, tokens = await asyncio.wait_for(
                    self._call(prompt + feedback, schema, system),
                    timeout=s.request_timeout_s + 15,
                )
            except Exception as exc:  # SDK, network and timeout errors
                if self._use_schema and _looks_like_schema_rejection(exc):
                    self._use_schema = False  # SDK/model refused the schema: fall back to prompt-embedded schema
                    continue
                kind, retryable = classify_error(exc)
                msg = s.redact(str(exc))
                if kind == "auth":
                    raise AuthError("Gemini rejected the API key. Check GEMINI_API_KEY.") from None
                if kind == "model":
                    raise ModelError(
                        f"Model {s.model!r} is unavailable for this key. Set GEMINI_MODEL to a supported model."
                    ) from None
                if kind in ("bad_request", "unknown"):
                    raise LLMError(f"{stage}: Gemini request failed ({type(exc).__name__}): {_short(msg)}") from None
                last = (QuotaError if kind == "quota" else TransientError)(
                    f"{stage}: {'quota or rate limit hit' if kind == 'quota' else 'network/server problem'}: {_short(msg)}"
                )
                if attempt < s.max_attempts:
                    await self._sleep(min(30.0, 2.0 * 2 ** (attempt - 1)) + random.random())
                continue
            try:
                obj = schema.model_validate_json(extract_json(text))
            except ValueError as exc:  # includes pydantic ValidationError and bad JSON
                last = MalformedOutputError(f"{stage}: model output failed validation: {_short(exc)}")
                feedback = (
                    "\n\nYour previous reply was rejected by the validator:\n"
                    f"{_short(exc, 1500)}\nReturn a corrected JSON object only."
                )
                continue
            self.usage.append(
                {"stage": stage, "model": s.model, "seconds": round(time.monotonic() - started, 2), **tokens}
            )
            return obj
        raise last or LLMError(f"{stage}: Gemini did not return a usable response")

    async def _call(self, prompt: str, schema: type[BaseModel], system: str) -> tuple[str, dict]:
        t = self._types
        if not self._use_schema:
            prompt += (
                "\n\nReturn ONE JSON object matching this JSON Schema exactly:\n"
                + json.dumps(schema.model_json_schema())
            )
        config = t.GenerateContentConfig(
            system_instruction=system or None,
            response_mime_type="application/json",
            response_schema=schema if self._use_schema else None,
            temperature=0.5,
            max_output_tokens=self._settings.max_output_tokens,
        )
        resp = await self._client.aio.models.generate_content(
            model=self._settings.model, contents=prompt, config=config
        )
        text = resp.text or ""
        meta = getattr(resp, "usage_metadata", None)
        tokens = {
            "prompt_tokens": getattr(meta, "prompt_token_count", None),
            "output_tokens": getattr(meta, "candidates_token_count", None),
        }
        return text, tokens


def _short(value: object, limit: int = 400) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."
