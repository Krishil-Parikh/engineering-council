"""The single Gemini adapter. Nothing else in the app imports the SDK or sees SDK response types."""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Protocol, TypeVar

from pydantic import BaseModel

from meetings.config import Settings

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


@dataclass
class LLMEvent:
    """What the UI sees while a call is in flight. kind: start|thought|chunk|retry|done|error."""

    kind: str
    stage: str
    attempt: int = 1
    text: str = ""
    info: str = ""


Observer = Callable[[LLMEvent], None]


class LLM(Protocol):
    """What the rest of the app depends on. Tests provide a fake implementing this."""

    usage: list[dict]
    observer: Optional[Observer]

    async def generate(self, prompt: str, schema: type[T], *, stage: str, system: str = "") -> T: ...


def extract_json(text: str) -> str:
    """Strip markdown fences / chatter and return the outermost JSON object text."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model output")
    return text[start : end + 1]


def retry_delay_seconds(message: str) -> Optional[float]:
    """Pull the server's suggested wait out of a 429 body, e.g. 'retry in 34.5s' or retryDelay '34s'."""
    m = re.search(r"retry in ([\d.]+)\s*s", message, re.IGNORECASE) or re.search(r"retryDelay['\"]?\s*:\s*['\"]?([\d.]+)s", message)
    return float(m.group(1)) if m else None


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


def _rejects(exc: Exception, word: str) -> bool:
    low = str(exc).lower()
    return word in low and (isinstance(exc, (ValueError, TypeError)) or getattr(exc, "code", None) == 400)


# Stages whose output is legitimately large (whole specifications); every other stage gets the smaller token cap.
BIG_STAGES = ("spec", "repair", "revision", "design1:revise", "design2:revise", "decisions")


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
        # Gemma rejects JSON mode / response_schema on large prompts with an instant 500. For those models the schema is
        # embedded in the prompt instead and the reply is parsed and validated locally. Gemini models use native JSON mode.
        gemini = settings.model.lower().startswith("gemini")
        self._json_mode = gemini
        self._use_schema = gemini
        # Thought summaries only exist on Gemini thinking models; Gemma answers a thinking config with a 500.
        self._use_thoughts = settings.model.lower().startswith("gemini")
        self._pause_until = 0.0  # shared by all concurrent calls: one 429 slows everybody down
        self._client = genai.Client(
            api_key=settings.api_key,
            http_options=types.HttpOptions(timeout=int(settings.request_timeout_s * 1000)),
        )
        self.usage: list[dict] = []
        self.observer: Optional[Observer] = None

    def _emit(self, kind: str, stage: str, attempt: int = 1, text: str = "", info: str = "") -> None:
        if self.observer:
            try:
                self.observer(LLMEvent(kind, stage, attempt, text, info))
            except Exception:  # a UI bug must never break the meeting
                pass

    async def _wait_for_shared_pause(self, stage: str, attempt: int) -> None:
        remaining = self._pause_until - time.monotonic()
        if remaining > 0:
            self._emit("retry", stage, attempt, info=f"waiting {remaining:.0f}s for the shared rate limit to clear")
            await self._sleep(remaining)

    async def generate(self, prompt: str, schema: type[T], *, stage: str, system: str = "") -> T:
        s = self._settings
        feedback = ""
        last: Optional[Exception] = None
        attempt = 0
        quota_hits = 0
        while attempt < s.max_attempts:
            attempt += 1
            await self._wait_for_shared_pause(stage, attempt)
            started = time.monotonic()
            self._emit("start", stage, attempt, info=f"{len(prompt) + len(system) + len(feedback)} chars in")
            try:
                text, tokens = await asyncio.wait_for(
                    self._call(prompt + feedback, schema, system, stage, attempt),
                    timeout=s.request_timeout_s + 15,
                )
            except Exception as exc:  # SDK, network and timeout errors
                if self._use_schema and _rejects(exc, "schema"):
                    self._use_schema = False  # fall back to a prompt-embedded schema
                    attempt -= 1
                    continue
                if self._use_thoughts and _rejects(exc, "thinking"):
                    self._use_thoughts = False
                    attempt -= 1
                    continue
                kind, _ = classify_error(exc)
                msg = s.redact(str(exc))
                if kind == "transient" and time.monotonic() - started < 3 and (self._use_thoughts or self._use_schema or self._json_mode):
                    # An instant 5xx usually means the model dislikes a request option: drop the fanciest one and retry.
                    if self._use_thoughts:
                        self._use_thoughts = False
                    elif self._use_schema:
                        self._use_schema = False
                    else:
                        self._json_mode = False
                    self._emit("retry", stage, attempt, info="instant server error; retrying with simpler request options")
                    attempt -= 1
                    continue
                if kind == "auth":
                    self._emit("error", stage, attempt, info="API key rejected")
                    raise AuthError("Gemini rejected the API key. Check GEMINI_API_KEY.") from None
                if kind == "model":
                    self._emit("error", stage, attempt, info="model unavailable")
                    raise ModelError(
                        f"Model {s.model!r} is unavailable for this key. Set GEMINI_MODEL to a supported model."
                    ) from None
                if kind in ("bad_request", "unknown"):
                    self._emit("error", stage, attempt, info=_short(msg))
                    raise LLMError(f"{stage}: Gemini request failed ({type(exc).__name__}): {_short(msg)}") from None
                if kind == "quota":
                    # Free-tier limits are per minute: honour the server's hint and give quota its own larger budget.
                    quota_hits += 1
                    wait = (retry_delay_seconds(msg) or min(90.0, 20.0 * quota_hits)) + 2 + random.random() * 3
                    self._pause_until = max(self._pause_until, time.monotonic() + wait)
                    last = QuotaError(f"{stage}: quota or rate limit hit after {quota_hits} waits: {_short(msg)}")
                    if quota_hits < s.max_quota_waits:
                        attempt -= 1  # quota waits do not consume the normal retry budget
                        self._emit("retry", stage, attempt + 1, info=f"rate limited (429); pausing all calls {wait:.0f}s")
                        continue
                    self._emit("error", stage, attempt, info="quota still exhausted after waiting")
                    raise last
                else:
                    last = TransientError(f"{stage}: network/server problem: {_short(msg)}")
                    if attempt < s.max_attempts:
                        wait = min(30.0, 2.0 * 2 ** (attempt - 1)) + random.random()
                        self._emit("retry", stage, attempt, info=f"{_short(msg, 120)} — retrying in {wait:.0f}s")
                        await self._sleep(wait)
                continue
            try:
                obj = schema.model_validate_json(extract_json(text))
            except ValueError as exc:  # includes pydantic ValidationError and bad JSON
                last = MalformedOutputError(f"{stage}: model output failed validation: {_short(exc)}")
                self._emit("retry", stage, attempt, info=f"output failed validation: {_short(exc, 160)}")
                feedback = (
                    "\n\nYour previous reply was rejected by the validator:\n"
                    f"{_short(exc, 1500)}\nReturn a corrected JSON object only. Keep it SHORT: lists of at most 8 items, no enumerating of file or component names, no repeated entries."
                )
                continue
            seconds = round(time.monotonic() - started, 2)
            self.usage.append({"stage": stage, "model": s.model, "seconds": seconds, **tokens})
            self._emit("done", stage, attempt, info=f"{seconds}s, {tokens.get('output_tokens')} tokens out")
            return obj
        self._emit("error", stage, attempt, info=_short(last or "no usable response"))
        raise last or LLMError(f"{stage}: Gemini did not return a usable response")

    async def _call(self, prompt: str, schema: type[BaseModel], system: str, stage: str, attempt: int) -> tuple[str, dict]:
        t = self._types
        if not self._use_schema:
            prompt += (
                "\n\nReturn ONE JSON object matching this JSON Schema exactly:\n"
                + json.dumps(schema.model_json_schema())
            )
        kwargs = dict(
            system_instruction=system or None,
            response_mime_type="application/json" if self._json_mode else None,
            response_schema=schema if self._use_schema else None,
            temperature=0.5,
            max_output_tokens=self._settings.max_output_tokens if stage.startswith(BIG_STAGES) else self._settings.max_turn_tokens,
        )
        if self._use_thoughts:
            kwargs["thinking_config"] = t.ThinkingConfig(include_thoughts=True)
        config = t.GenerateContentConfig(**kwargs)
        stream = await self._client.aio.models.generate_content_stream(
            model=self._settings.model, contents=prompt, config=config
        )
        answer: list[str] = []
        meta = None
        async for chunk in stream:
            meta = getattr(chunk, "usage_metadata", None) or meta
            for cand in getattr(chunk, "candidates", None) or []:
                content = getattr(cand, "content", None)
                for part in getattr(content, "parts", None) or []:
                    piece = getattr(part, "text", None)
                    if not piece:
                        continue
                    if getattr(part, "thought", False):
                        self._emit("thought", stage, attempt, text=piece)
                    else:
                        answer.append(piece)
                        self._emit("chunk", stage, attempt, text=piece)
        tokens = {
            "prompt_tokens": getattr(meta, "prompt_token_count", None),
            "output_tokens": getattr(meta, "candidates_token_count", None),
        }
        return "".join(answer), tokens


def _short(value: object, limit: int = 400) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."
