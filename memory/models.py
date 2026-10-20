"""The two things memory needs from a model: a vector for a text (to find what means the same), and a structured answer (to extract, reconcile, rewrite and rerank).

Both are synchronous and small; callers run them in a worker thread. Nothing here is required: with no model, memory still works by words and by the graph, and a
model that is overloaded is skipped for a minute (and another one tried) so memory never slows the build."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional, Protocol

DIMENSIONS = 768  # the embedding is asked for at this size: close to the full quality, a quarter of the cost to store and compare


class MemoryModel(Protocol):
    embed_model: str

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]: ...

    def generate_json(self, prompt: str) -> Any: ...


def parse_json(text: str) -> Any:
    """The first JSON value in a model's reply (it may be wrapped in a code fence or in words)."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        for opener, closer in (("{", "}"), ("[", "]")):
            start, end = text.find(opener), text.rfind(closer)
            if 0 <= start < end:
                try:
                    return json.loads(text[start: end + 1])
                except ValueError:
                    continue
    raise ValueError("the model's reply was not JSON")


class GeminiMemoryModel:
    FALLBACKS = ("gemini-3.5-flash-lite", "gemini-3-flash-preview", "gemini-flash-lite-latest")  # tried in turn when the chosen model is overloaded

    def __init__(self, api_key: str, model: str = "gemini-3.1-flash-lite", embed_model: str = "gemini-embedding-001", dimensions: int = DIMENSIONS,
                 fallbacks: Optional[tuple[str, ...]] = None) -> None:
        from google import genai
        from google.genai import types

        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=45_000))  # a stuck call must not stall the build
        self.model, self.embed_model, self.dimensions = model, embed_model, dimensions
        self.models = [model, *[m for m in (self.FALLBACKS if fallbacks is None else fallbacks) if m != model]]
        self._down: dict[str, float] = {}  # model -> when it may be tried again: a model that just failed is skipped, not waited for
        self._embed_down = 0.0  # the embedding service: while it is failing, calls are refused at once (memory then runs on words and the graph)

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        from google.genai import types

        if time.time() < self._embed_down:
            raise RuntimeError("embeddings are unavailable for a moment")
        out: list[list[float]] = []
        for start in range(0, len(texts), 64):
            batch = [t[:6000] for t in texts[start: start + 64]]
            for attempt in range(2):
                try:
                    reply = self.client.models.embed_content(
                        model=self.embed_model, contents=batch,
                        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT", output_dimensionality=self.dimensions),
                    )
                    out.extend(list(e.values) for e in reply.embeddings)
                    break
                except Exception:  # noqa: BLE001 - a hiccup: one more try, then give up for a minute
                    if attempt == 1:
                        self._embed_down = time.time() + 60
                        raise
                    time.sleep(1.0)
        return out

    def generate_json(self, prompt: str) -> Any:
        """The first model that answers, in order; a model that failed is left alone for a minute, and one that is slow is not waited for twice."""
        from google.genai import types

        last: Optional[Exception] = None
        for name in self.models:
            if time.time() < self._down.get(name, 0.0):
                continue
            try:
                reply = self.client.models.generate_content(model=name, contents=prompt, config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1))
                return parse_json(reply.text or "")
            except Exception as exc:  # noqa: BLE001 - overloaded, not found, a reply that is not JSON: try the next one
                self._down[name] = time.time() + 60
                last = exc
        raise last or RuntimeError("no memory model is available for a moment")


def default_model(api_key: Optional[str], model: Optional[str] = None) -> Optional[MemoryModel]:
    """The Gemini model when a key is known; None otherwise (memory then runs on words and the graph alone)."""
    if not api_key:
        return None
    try:
        return GeminiMemoryModel(api_key, model or "gemini-3.1-flash-lite")
    except Exception:  # noqa: BLE001
        return None
