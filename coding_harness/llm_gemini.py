"""Gemini adapter: tool-calling chat over the google-genai SDK, streamed, with provider errors mapped to ModelError.

Gemini 3 attaches a "thought signature" to function-call parts and requires it back on the next request, so assistant turns are kept
verbatim (`Message.raw`) and replayed unchanged."""

from __future__ import annotations

import json
import re
from typing import Any

from coding_harness.types import ChatModel, Event, Message, ModelError, ModelReply, Observer, ToolCall, ToolSpec

_RETRY_IN = re.compile(r"retry in ([0-9.]+)\s*s|retryDelay['\"]?:\s*['\"]?([0-9.]+)s", re.IGNORECASE)
_OVERFLOW = ("exceeds the maximum number of tokens", "input token count", "context length", "too long", "request payload size exceeds")


def classify(exc: Exception) -> ModelError:
    msg = " ".join(str(exc).split())
    low = msg.lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    m = _RETRY_IN.search(msg)
    retry = float(m.group(1) or m.group(2)) if m else None
    if code == 400 and any(k in low for k in _OVERFLOW):
        return ModelError(msg[:300], "overflow")
    if code == 429 or "resource_exhausted" in low or "quota" in low:
        return ModelError(msg[:300], "rate_limit", retry)
    if code in (401, 403) or "api key" in low and "invalid" in low:
        return ModelError("Gemini rejected the API key.", "auth")
    if isinstance(code, int) and code >= 500:
        return ModelError(msg[:300], "transient", retry)
    if isinstance(code, int) and 400 <= code < 500:
        return ModelError(msg[:300], "fatal")
    name = type(exc).__name__.lower()
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)) or any(k in name for k in ("timeout", "connect", "network", "protocol", "remote")):
        return ModelError(msg[:300] or name, "transient")
    return ModelError(msg[:300] or name, "fatal")


class GeminiChatModel:
    def __init__(self, api_key: str, model: str = "gemini-3.1-flash-lite", *, timeout_s: float = 600.0, temperature: float = 0.2, max_output_tokens: int = 16384) -> None:
        from google import genai
        from google.genai import types

        self.types = types
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.thoughts = model.lower().startswith("gemini")
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))

    # ---- conversion
    def _contents(self, messages: list[Message]) -> list[Any]:
        t = self.types
        out: list[Any] = []
        responses: list[Any] = []

        def flush() -> None:
            if responses:
                out.append(t.Content(role="user", parts=list(responses)))
                responses.clear()

        for m in messages:
            if m.role == "tool":
                body = {"error": m.text} if m.is_error else {"output": m.text}
                responses.append(t.Part(function_response=t.FunctionResponse(name=m.tool_name or "tool", response=body)))
                continue
            flush()
            if m.role == "user":
                if not m.text.strip():
                    continue
                if out and out[-1].role == "user" and not any(p.function_response for p in out[-1].parts or []):
                    out[-1].parts.append(t.Part(text=m.text))
                else:
                    out.append(t.Content(role="user", parts=[t.Part(text=m.text)]))
            else:
                if m.raw:
                    out.append(t.Content.model_validate_json(json.dumps(m.raw)))
                    continue
                parts = ([t.Part(text=m.text)] if m.text.strip() else []) + [t.Part(function_call=t.FunctionCall(name=c.name, args=c.args)) for c in m.tool_calls]
                if parts:
                    out.append(t.Content(role="model", parts=parts))
        flush()
        return out

    def _tools(self, tools: list[ToolSpec]) -> list[Any]:
        t = self.types
        if not tools:
            return []
        return [t.Tool(function_declarations=[t.FunctionDeclaration(name=s.name, description=s.description, parameters_json_schema=s.parameters) for s in tools])]

    # ---- call
    async def complete(
        self, *, system: str, messages: list[Message], tools: list[ToolSpec], tool_choice: str = "auto",
        on_event: Observer | None = None, stage: str = "", max_output_tokens: int | None = None,
    ) -> ModelReply:
        t = self.types
        kwargs: dict[str, Any] = dict(
            system_instruction=system or None, temperature=self.temperature, max_output_tokens=max_output_tokens or self.max_output_tokens,
        )
        decls = self._tools(tools)
        if decls:
            kwargs["tools"] = decls
            kwargs["automatic_function_calling"] = t.AutomaticFunctionCallingConfig(disable=True)
            if tool_choice == "none":
                kwargs["tool_config"] = t.ToolConfig(function_calling_config=t.FunctionCallingConfig(mode=t.FunctionCallingConfigMode.NONE))
        if self.thoughts:
            kwargs["thinking_config"] = t.ThinkingConfig(include_thoughts=True)
        config = t.GenerateContentConfig(**kwargs)
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        raw_parts: list[dict[str, Any]] = []
        usage: dict[str, int] = {}
        finish = "stop"
        try:
            stream = await self.client.aio.models.generate_content_stream(model=self.model, contents=self._contents(messages), config=config)
            async for chunk in stream:
                meta = getattr(chunk, "usage_metadata", None)
                if meta:
                    usage = {"input_tokens": getattr(meta, "prompt_token_count", 0) or 0, "output_tokens": getattr(meta, "candidates_token_count", 0) or 0}
                for cand in getattr(chunk, "candidates", None) or []:
                    fr = getattr(cand, "finish_reason", None)
                    if fr is not None and "MAX_TOKENS" in str(fr):
                        finish = "length"
                    for part in getattr(getattr(cand, "content", None), "parts", None) or []:
                        if getattr(part, "thought", False):
                            if part.text and on_event:
                                on_event(Event("thought", {"text": part.text}))
                            continue
                        raw_parts.append(json.loads(part.model_dump_json(exclude_none=True)))
                        if part.function_call:
                            fc = part.function_call
                            calls.append(ToolCall(fc.id or f"call_{len(calls) + 1}_{len(raw_parts)}", fc.name or "", dict(fc.args or {})))
                        elif part.text:
                            text_parts.append(part.text)
                            if on_event:
                                on_event(Event("text", {"text": part.text}))
        except ModelError:
            raise
        except Exception as exc:  # SDK, network and timeout errors
            raise classify(exc) from None
        raw = {"role": "model", "parts": raw_parts} if raw_parts else None
        if calls and finish != "length":
            finish = "tool_calls"
        return ModelReply("".join(text_parts), calls, raw, usage, finish)  # type: ignore[arg-type]


assert isinstance(GeminiChatModel, type)
