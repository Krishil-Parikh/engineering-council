"""Building the model request (opencode: packages/core/src/session/model-request.ts, the parts the engine needs)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from harness.ai import types as T
from harness.ai.model import ModelLimit, ResolvedModel
from harness.schema import message as M
from harness.session import system_prompt as SystemPrompt
from harness.session.to_llm_message import to_llm_messages

OUTPUT_TOKEN_FALLBACK = 32_000  # used when the catalog has no output limit for the model
OUTPUT_TOKEN_MAX = 256_000  # no reply needs more, however much the model allows
SUMMARY_OUTPUT_MAX = 32_000  # a summary never needs more
ESTIMATE_ERROR = 0.15  # prompt text is estimated at ~4 chars/token, which can run low on dense text such as code
OUTPUT_TOKEN_MIN = 1_024


@dataclass
class InputTokens:
    measured: float = 0
    estimated: float = 0


def output_limit(limit: ModelLimit, kind: str, input_tokens: Optional[InputTokens] = None) -> int:
    """The default output limit: the catalog limit, fitted to the room the prompt leaves in the context window."""
    model = min(limit.output if limit.output > 0 else OUTPUT_TOKEN_FALLBACK, OUTPUT_TOKEN_MAX)
    requested = min(model, SUMMARY_OUTPUT_MAX) if kind == "compaction" else model
    if input_tokens is None or limit.context <= 0:
        return requested
    room = limit.context - input_tokens.measured - math.ceil(input_tokens.estimated * (1 + ESTIMATE_ERROR))
    return int(min(requested, max(OUTPUT_TOKEN_MIN, room)))


@dataclass
class Transcript:
    provider_metadata_key: str
    system: list[T.SystemPart]
    messages: list[T.Message]


def base_transcript(*, agent_system: Optional[str], model: ResolvedModel, tool_names: list[str], initial: str, messages: list[M.Info]) -> Transcript:
    """System prompt = the agent's own prompt if it has one, otherwise the default; then the frozen instruction baseline."""
    key = model.metadata_key
    parts = [agent_system if agent_system else SystemPrompt.make(tool_names), initial]
    return Transcript(key, [T.SystemPart(p) for p in parts if len(p) > 0], to_llm_messages(messages, model.ref, key))
