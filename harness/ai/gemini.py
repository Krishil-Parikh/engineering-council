"""Gemini provider (opencode: packages/ai/src/protocols/gemini.ts, on the google-genai SDK instead of raw HTTP).

Lowering: our messages become Gemini contents. Instruction updates (system messages inside the conversation) are wrapped in
<system-update> and join the previous user turn, because Gemini has no mid-conversation system role. Tool results for one
batch of parallel calls share a single user turn. Thought signatures ride on text, reasoning and tool-call parts and must be sent
back unchanged on the next request, so they travel in the part's provider metadata.

Parsing: the streamed parts are turned into text / reasoning / tool-call events, each block remembering the signature attached
to its own parts; usage and the finish reason are mapped when the stream ends."""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Optional

from harness.ai import events as E
from harness.ai import types as T
from harness.ai.errors import AIError, classify_provider_failure, error as ai_error
from harness.session.usage import Usage

SKIP_THOUGHT_SIGNATURE_VALIDATOR = "skip_thought_signature_validator"
METADATA_KEY = "google"


# --------------------------------------------------------------------------- model quirks


def requires_thought_signature_fallback(model_id: str) -> bool:
    if not re.search(r"(^|/)gemini-", model_id, re.I):
        return False
    if re.search(r"(^|/)gemini-(?:1|2)(?:[.-]|$)", model_id, re.I):
        return False
    if re.search(r"(^|/)gemini-pro(?:-vision)?$", model_id, re.I):
        return False
    return not re.search(r"(^|/)gemini-robotics-er-1\.5(?:[.-]|$)", model_id, re.I)


def omits_function_call_ids(model_id: str) -> bool:
    m = re.match(r"^gemini(?:-live)?-(\d+)", model_id, re.I)
    return m is not None and int(m.group(1)) < 3


# --------------------------------------------------------------------------- lowering


def _escape_update(text: str) -> str:
    return re.sub(r"<(/?)system-update>", r"&lt;\1system-update&gt;", text)


def wrap_system_update(text: str) -> str:
    return f"<system-update>\n{_escape_update(text)}\n</system-update>"


def _signature(metadata: Optional[T.ProviderMetadata], key: str) -> Optional[str]:
    value = (metadata or {}).get(key)
    return value.get("thoughtSignature") if isinstance(value, dict) and isinstance(value.get("thoughtSignature"), str) else None


def _sig_bytes(sig: Optional[str]) -> Optional[bytes]:
    if sig is None:
        return None
    try:
        return base64.b64decode(sig, validate=True)
    except Exception:  # noqa: BLE001 - e.g. the literal skip marker, which is URL-safe text, not standard base64
        try:
            return base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
        except Exception:  # noqa: BLE001
            return sig.encode()


def _tool_result_text(part: T.ToolResultPart) -> str:
    r = part.result
    if r.type == "text":
        return r.value if isinstance(r.value, str) else json.dumps(r.value, default=str)
    if r.type == "content":
        return "\n".join(c.get("text", "") for c in r.value if c.get("type") == "text")
    if r.type == "error":
        v = r.value
        if isinstance(v, dict) and "error" in v:
            msg = v["error"].get("message", "") if isinstance(v["error"], dict) else str(v["error"])
            extra = "\n".join(c.get("text", "") for c in v.get("content", []) if c.get("type") == "text")
            return "\n".join(x for x in (msg, extra) if x)
        return v if isinstance(v, str) else json.dumps(v, default=str)
    return json.dumps(r.value, default=str)


def lower_messages(types: Any, messages: list[T.Message], model_id: str, key: str = METADATA_KEY) -> list[Any]:
    contents: list[Any] = []
    omit_ids = omits_function_call_ids(model_id)
    has_response = lambda c: any(p.function_response is not None for p in (c.parts or []))  # noqa: E731

    for message in messages:
        if message.role == "system":
            text = "".join(p.text for p in message.content if isinstance(p, T.TextPart))
            part = types.Part(text=wrap_system_update(text))
            prev = contents[-1] if contents else None
            # Gemini rejects a continuation whose function-response turn carries extra parts, so an update after a tool result starts its own turn.
            if prev is not None and prev.role == "user" and not has_response(prev):
                prev.parts = [*(prev.parts or []), part]
            else:
                contents.append(types.Content(role="user", parts=[part]))
            continue
        if message.role == "user":
            parts = []
            for p in message.content:
                if isinstance(p, T.TextPart):
                    parts.append(types.Part(text=p.text))
                elif isinstance(p, T.MediaPart):
                    parts.append(types.Part(inline_data=types.Blob(mime_type=p.media.media_type, data=base64.b64decode(p.media.data))))
            if parts:
                contents.append(types.Content(role="user", parts=parts))
            continue
        if message.role == "assistant":
            parts = []
            signed_call = False  # parallel Gemini 3 calls may carry one signature on the first call; unsigned siblings are valid
            for p in message.content:
                if isinstance(p, T.TextPart):
                    if p.text != "":
                        parts.append(types.Part(text=p.text, thought_signature=_sig_bytes(_signature(p.provider_metadata, key))))
                elif isinstance(p, T.ReasoningPart):
                    parts.append(types.Part(text=p.text, thought=True, thought_signature=_sig_bytes(_signature(p.provider_metadata, key))))
                elif isinstance(p, T.ToolCallPart):
                    sig = _signature(p.provider_metadata, key)
                    use = sig if sig is not None else (SKIP_THOUGHT_SIGNATURE_VALIDATOR if requires_thought_signature_fallback(model_id) and not signed_call else None)
                    args = p.input if isinstance(p.input, dict) else {"value": p.input}
                    fc = types.FunctionCall(name=p.name, args=args, **({} if omit_ids else {"id": p.id}))
                    parts.append(types.Part(function_call=fc, thought_signature=_sig_bytes(use)))
                    if sig is not None:
                        signed_call = True
            if parts:
                contents.append(types.Content(role="model", parts=parts))
            continue
        # tool results
        parts = []
        for p in message.content:
            if isinstance(p, T.ToolResultPart):
                fr = types.FunctionResponse(name=p.name, response={"name": p.name, "content": _tool_result_text(p)}, **({} if omit_ids else {"id": p.id}))
                parts.append(types.Part(function_response=fr))
        if not parts:
            continue
        prev = contents[-1] if contents else None
        # Gemini requires every response to a parallel call batch in one user turn.
        if prev is not None and prev.role == "user" and has_response(prev):
            prev.parts = [*(prev.parts or []), *parts]
        else:
            contents.append(types.Content(role="user", parts=parts))
    return contents


# --------------------------------------------------------------------------- parsing


def map_usage(meta: Any) -> Optional[Usage]:
    if meta is None:
        return None
    prompt = getattr(meta, "prompt_token_count", None)
    cached = getattr(meta, "cached_content_token_count", None) or 0
    thoughts = getattr(meta, "thoughts_token_count", None) or 0
    visible = getattr(meta, "candidates_token_count", None)
    return Usage(
        non_cached_input_tokens=max(0, (prompt or 0) - cached), visible_output_tokens=visible or 0,
        reasoning_tokens=thoughts, cache_read_input_tokens=cached,
    )


def map_finish_reason(reason: Optional[str], has_tool_calls: bool) -> str:
    if reason is None:
        return "tool-calls" if has_tool_calls else "unknown"
    if reason == "STOP":
        return "tool-calls" if has_tool_calls else "stop"
    if reason == "MAX_TOKENS":
        return "length"
    if reason in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION", "IMAGE_SAFETY", "LANGUAGE"):
        return "content-filter"
    if reason in ("MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL", "NO_IMAGE", "TOO_MANY_TOOL_CALLS", "MISSING_THOUGHT_SIGNATURE", "MALFORMED_RESPONSE"):
        return "error"
    return "unknown"


def _b64(sig: Any) -> Optional[str]:
    if not sig:
        return None
    return base64.b64encode(sig).decode() if isinstance(sig, (bytes, bytearray)) else str(sig)


def _meta(sig: Optional[str], key: str = METADATA_KEY) -> Optional[dict[str, Any]]:
    return {key: {"thoughtSignature": sig}} if sig else None


@dataclass
class _State:
    key: str = METADATA_KEY
    has_tool_calls: bool = False
    finish_reason: Optional[str] = None
    prompt_feedback: Any = None
    usage: Any = None
    reasoning_id: Optional[str] = None
    text_id: Optional[str] = None
    reasoning_signature: Optional[str] = None
    text_signature: Optional[str] = None
    next_reasoning: int = 0
    next_text: int = 0
    seen_call_ids: set[str] = field(default_factory=set)
    started_text: set[str] = field(default_factory=set)
    started_reasoning: set[str] = field(default_factory=set)


def _enum_name(v: Any) -> Optional[str]:
    if v is None:
        return None
    return v.name if hasattr(v, "name") else str(v).split(".")[-1]


def _end_reasoning(st: _State, out: list[E.LLMEvent]) -> None:
    if st.reasoning_id is not None:
        out.append(E.ReasoningEnd(st.reasoning_id, _meta(st.reasoning_signature, st.key)))
        st.reasoning_id = st.reasoning_signature = None


def _end_text(st: _State, out: list[E.LLMEvent]) -> None:
    if st.text_id is not None:
        out.append(E.TextEnd(st.text_id, _meta(st.text_signature, st.key)))
        st.text_id = st.text_signature = None


def step_chunk(st: _State, chunk: Any) -> list[E.LLMEvent]:
    """Fold one streamed chunk into events. Raises AIError for stream-level failures."""
    out: list[E.LLMEvent] = []
    if getattr(chunk, "prompt_feedback", None) is not None:
        st.prompt_feedback = chunk.prompt_feedback
    if getattr(chunk, "usage_metadata", None) is not None:
        st.usage = chunk.usage_metadata
    cands = getattr(chunk, "candidates", None) or []
    cand = cands[0] if cands else None
    if cand is not None and getattr(cand, "finish_reason", None) is not None:
        st.finish_reason = _enum_name(cand.finish_reason)
    if st.finish_reason == "MALFORMED_RESPONSE":
        # Gemini sporadically ends a valid request with MALFORMED_RESPONSE; continuing or resending it recovers.
        raise ai_error("InvalidProviderOutput", f"Gemini stopped with {st.finish_reason}", classification="incomplete-stream")
    if st.finish_reason and map_finish_reason(st.finish_reason, st.has_tool_calls) == "error":
        raise ai_error("InvalidProviderOutput", f"Gemini stopped with {st.finish_reason}")
    content = getattr(cand, "content", None) if cand is not None else None
    if content is None:
        return out
    for part in content.parts or []:
        sig = _b64(getattr(part, "thought_signature", None))
        is_thought = bool(getattr(part, "thought", False))
        text = getattr(part, "text", None)
        if sig is not None and is_thought:
            st.reasoning_signature = sig
        elif sig is not None and text is not None:
            st.text_signature = sig
        fc = getattr(part, "function_call", None)
        if text is not None and len(text) > 0:
            if is_thought:
                _end_text(st, out)
                if st.reasoning_id is None:
                    st.reasoning_id = f"reasoning-{st.next_reasoning}"
                    st.next_reasoning += 1
                if st.reasoning_id not in st.started_reasoning:
                    st.started_reasoning.add(st.reasoning_id)
                    out.append(E.ReasoningStart(st.reasoning_id))
                out.append(E.ReasoningDelta(text, st.reasoning_id))
                continue
            _end_reasoning(st, out)
            if st.text_id is None:
                st.text_id = f"text-{st.next_text}"
                st.next_text += 1
            if st.text_id not in st.started_text:
                st.started_text.add(st.text_id)
                out.append(E.TextStart(st.text_id))
            out.append(E.TextDelta(text, st.text_id))
            continue
        if fc is not None:
            args = dict(fc.args) if getattr(fc, "args", None) else {}
            supplied = getattr(fc, "id", None) or None
            duplicate = supplied is not None and supplied in st.seen_call_ids
            if supplied is not None:
                st.seen_call_ids.add(supplied)
            call_id = supplied if supplied is not None and not duplicate else "tool_" + os.urandom(16).hex()
            _end_reasoning(st, out)
            _end_text(st, out)
            out.append(E.ToolCall(call_id, fc.name or "", args, provider_metadata=_meta(sig, st.key)))
            st.has_tool_calls = True
    return out


def finish_events(st: _State) -> list[E.LLMEvent]:
    block = getattr(st.prompt_feedback, "block_reason", None) if st.finish_reason is None else None
    reason = st.finish_reason or _enum_name(block)
    if reason is None and st.usage is None:
        return []
    out: list[E.LLMEvent] = []
    _end_reasoning(st, out)
    _end_text(st, out)
    normalized = "content-filter" if block is not None else map_finish_reason(reason, st.has_tool_calls)
    meta = {st.key: {"promptFeedback": str(st.prompt_feedback)}} if st.prompt_feedback is not None and block is not None else None
    out.append(E.StepFinish(map_usage(st.usage), meta, normalized, reason))  # type: ignore[arg-type]
    out.append(E.Finish(normalized, reason))  # type: ignore[arg-type]
    return out


async def parse_stream(chunks: Any, key: str = METADATA_KEY) -> AsyncIterator[E.LLMEvent]:
    st = _State(key=key)
    async for chunk in chunks:
        for ev in step_chunk(st, chunk):
            yield ev
    for ev in finish_events(st):
        yield ev


# --------------------------------------------------------------------------- errors

_RETRY_IN = re.compile(r"retry in ([0-9.]+)\s*s|retryDelay['\"]?\s*:\s*['\"]?([0-9.]+)s", re.I)


def classify_sdk_error(exc: BaseException) -> AIError:
    """Map google-genai / network exceptions to typed AI errors.

    Deviation from opencode: on Gemini a 429 saying "Quota exceeded ... Please retry in 34s" is a per-minute throttle (free tier),
    not an exhausted account, so it is a RateLimit with the server's delay."""
    if isinstance(exc, AIError):
        return exc
    message = " ".join(str(getattr(exc, "message", None) or exc).split())
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    status = status if isinstance(status, int) else None
    details = getattr(exc, "details", None)
    raw = json.dumps(details, default=str) if details is not None else message
    m = _RETRY_IN.search(message) or _RETRY_IN.search(raw)  # the message states the exact delay; details round it
    retry_ms = float(m.group(1) or m.group(2)) * 1000 if m else None
    if status == 429 and (retry_ms is not None or re.search(r"per[- ]minute|requests per", raw + message, re.I)):
        return ai_error("RateLimit", message[:400], body=raw[:2000], retry_after_ms=retry_ms)
    if status is not None:
        return classify_provider_failure(message[:400], status=status, raw_body=raw[:2000], data=details, retry_after_ms=retry_ms)
    name = type(exc).__name__.lower()
    if isinstance(exc, (TimeoutError,)) or "timeout" in name:
        return ai_error("Transport", message[:300] or "timeout", transport_operation="request", code="Timeout")
    if isinstance(exc, (ConnectionError, OSError)) or any(k in name for k in ("connect", "network", "protocol", "remote", "read")):
        return ai_error("Transport", message[:300] or name, transport_operation="read" if "read" in name else "request")
    return classify_provider_failure(message[:400] or name)


# --------------------------------------------------------------------------- the client


class GeminiClient:
    def __init__(
        self, api_key: str, model: str = "gemini-3.5-flash-lite", *, timeout_s: float = 600.0, thoughts: bool = True,
        client: Any = None, temperature: Optional[float] = None,
    ) -> None:
        from google import genai
        from google.genai import types

        self.types, self.model, self.thoughts, self.temperature = types, model, thoughts and model.lower().startswith("gemini"), temperature
        self.client = client or genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))

    def _config(self, request: T.LLMRequest) -> Any:
        t = self.types
        kw: dict[str, Any] = {}
        if request.system:
            kw["system_instruction"] = "\n\n".join(p.text for p in request.system)
        g = request.generation
        if g is not None:
            if g.max_tokens is not None:
                kw["max_output_tokens"] = g.max_tokens
            if g.top_p is not None:
                kw["top_p"] = g.top_p
        temperature = g.temperature if g and g.temperature is not None else self.temperature
        if temperature is not None:
            kw["temperature"] = temperature
        if request.tools:
            kw["tools"] = [t.Tool(function_declarations=[t.FunctionDeclaration(name=x.name, description=x.description, parameters_json_schema=x.input_schema) for x in request.tools])]
            kw["automatic_function_calling"] = t.AutomaticFunctionCallingConfig(disable=True)
            if request.tool_choice == "none":
                kw["tool_config"] = t.ToolConfig(function_calling_config=t.FunctionCallingConfig(mode=t.FunctionCallingConfigMode.NONE))
        if self.thoughts:
            kw["thinking_config"] = t.ThinkingConfig(include_thoughts=True)
        return t.GenerateContentConfig(**kw)

    async def stream(self, request: T.LLMRequest) -> AsyncIterator[E.LLMEvent]:
        contents = lower_messages(self.types, request.messages, self.model)
        try:
            chunks = await self.client.aio.models.generate_content_stream(model=self.model, contents=contents, config=self._config(request))
            async for ev in parse_stream(chunks):
                yield ev
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001 - SDK, network and timeout errors
            raise classify_sdk_error(exc) from None
