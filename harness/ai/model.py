"""Model description used by the engine (opencode: packages/schema/src/model.ts, reduced)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from harness.schema.message import ModelRef


@dataclass
class ModelLimit:
    context: int = 0  # 0 = unknown
    input: int = 0
    output: int = 0


@dataclass
class ModelCost:
    input: float = 0.0  # USD per million tokens
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    tier_size: Optional[int] = None  # a context-tiered price applies above this many input tokens


@dataclass
class ResolvedModel:
    ref: ModelRef
    provider: str  # provider key used for provider metadata, e.g. "google"
    limit: ModelLimit = field(default_factory=ModelLimit)
    cost: list[ModelCost] = field(default_factory=list)
    provider_metadata_key: Optional[str] = None

    @property
    def metadata_key(self) -> str:
        return self.provider_metadata_key or self.provider
