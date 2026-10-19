"""The models the harness can use (opencode: packages/core/src/models-dev.ts and model.ts, reduced to what a Gemini-only setup needs).

Entries carry the limits and prices the engine needs to size requests and cost them, a release time for "newest first" listings, and
optional variants. The built-in list is a starting point: `add` overrides or extends it (for example from configuration)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from harness.ai.model import ModelCost, ModelLimit, ResolvedModel
from harness.schema.message import ModelRef


@dataclass
class ModelInfo:
    provider_id: str
    id: str
    name: str
    family: Optional[str] = None
    released: int = 0  # unix ms; 0 when unknown
    limit: ModelLimit = field(default_factory=ModelLimit)
    cost: list[ModelCost] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)
    status: str = "active"  # active | beta | deprecated

    @property
    def ref(self) -> ModelRef:
        return ModelRef(provider_id=self.provider_id, id=self.id)


PROVIDERS = {"google": "Google"}
_MILLION = 1_048_576


def builtin_models() -> list[ModelInfo]:
    flash = ModelLimit(context=_MILLION, input=_MILLION - 65_536, output=65_536)
    return [
        ModelInfo("google", "gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "gemini-flash-lite", 1_780_000_000_000, flash, [ModelCost(0.10, 0.40)]),  # price: same as 3.1 Flash-Lite until published
        ModelInfo("google", "gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite", "gemini-flash-lite", 1_767_225_600_000, flash, [ModelCost(0.10, 0.40)]),
        ModelInfo("google", "gemini-2.5-flash", "Gemini 2.5 Flash", "gemini-flash", 1_750_000_000_000, flash, [ModelCost(0.30, 2.50, 0.075)]),
        ModelInfo("google", "gemini-2.5-pro", "Gemini 2.5 Pro", "gemini-pro", 1_750_000_000_000, flash, [ModelCost(1.25, 10.0, 0.31, tier_size=200_000), ModelCost(2.50, 15.0, 0.625)]),
    ]


class ModelCatalog:
    def __init__(self, models: Optional[list[ModelInfo]] = None, providers: Optional[dict[str, str]] = None) -> None:
        self._models: dict[tuple[str, str], ModelInfo] = {}
        self.providers = dict(providers or PROVIDERS)
        for m in models if models is not None else builtin_models():
            self.add(m)

    def add(self, model: ModelInfo) -> None:
        self._models[(model.provider_id, model.id)] = model
        self.providers.setdefault(model.provider_id, model.provider_id)

    def list(self) -> list[ModelInfo]:
        return list(self._models.values())

    def get(self, ref: ModelRef) -> Optional[ModelInfo]:
        return self._models.get((ref.provider_id, ref.id))

    def available(self) -> list[dict]:
        """The shape the subagent tool validates a model override against."""
        return [{"provider_id": m.provider_id, "id": m.id, "variants": list(m.variants)} for m in self.list()]

    def resolve(self, ref: ModelRef) -> ResolvedModel:
        info = self.get(ref)
        if info is None:
            return ResolvedModel(ref=ref, provider=ref.provider_id)
        return ResolvedModel(ref=ref, provider=info.provider_id, limit=info.limit, cost=info.cost)
