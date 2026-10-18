"""Token and cost accounting (opencode: packages/core/src/session/usage.ts)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from harness.ai.model import ModelCost
from harness.schema.message import TokenUsage


def _finite(v: float) -> float:
    return v if math.isfinite(v) else 0.0


def _safe(v: Optional[float]) -> float:
    return max(0.0, _finite(v or 0))


@dataclass
class Usage:
    """What a provider reports for one step."""

    non_cached_input_tokens: float = 0
    visible_output_tokens: float = 0
    reasoning_tokens: float = 0
    cache_read_input_tokens: float = 0
    cache_write_input_tokens: float = 0


def tokens(usage: Optional[Usage]) -> TokenUsage:
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        input=_safe(usage.non_cached_input_tokens), output=_safe(usage.visible_output_tokens), reasoning=_safe(usage.reasoning_tokens),
        cache_read=_safe(usage.cache_read_input_tokens), cache_write=_safe(usage.cache_write_input_tokens),
    )


def calculate_cost(costs: list[ModelCost], usage: TokenUsage) -> float:
    context = usage.input + usage.cache_read + usage.cache_write
    tiers = sorted((c for c in costs if c.tier_size is not None and context > c.tier_size), key=lambda c: -(c.tier_size or 0))
    cost = tiers[0] if tiers else next((c for c in costs if c.tier_size is None), None)
    if cost is None:
        return 0.0
    return (
        usage.input * _finite(cost.input) + (usage.output + usage.reasoning) * _finite(cost.output)
        + usage.cache_read * _finite(cost.cache_read) + usage.cache_write * _finite(cost.cache_write)
    ) / 1_000_000


@dataclass
class Recorded:
    tokens: TokenUsage
    cost: float


def record(usage: Optional[Usage], costs: list[ModelCost]) -> Recorded:
    t = tokens(usage)
    return Recorded(t, calculate_cost(costs, t))


def add(a: Recorded, b: Recorded) -> Recorded:
    return Recorded(
        TokenUsage(
            input=a.tokens.input + b.tokens.input, output=a.tokens.output + b.tokens.output, reasoning=a.tokens.reasoning + b.tokens.reasoning,
            cache_read=a.tokens.cache_read + b.tokens.cache_read, cache_write=a.tokens.cache_write + b.tokens.cache_write,
        ),
        a.cost + b.cost,
    )
