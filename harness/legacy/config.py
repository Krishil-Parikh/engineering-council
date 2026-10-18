"""Harness settings from `council.json` (project root or .council/) and `config.json` in the harness home. Project wins."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.legacy.permission import Rule, Ruleset
from harness.legacy.workspace import Workspace


@dataclass
class HarnessConfig:
    context_window: int = 200_000  # compaction budget; Gemini's real window is larger, but long contexts get slower and noisier
    compaction_keep: int = 15_000  # tokens of recent conversation kept verbatim after compaction
    auto_compact: bool = True
    max_output_tokens: int = 16_384
    snapshots: bool = True
    default_agent: str = "build"
    rules: Ruleset = field(default_factory=list)  # appended after the built-in rules, so they win
    agent_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)  # agent id -> {steps, system, permissions}
    max_subagent_depth: int = 2
    git_name: str = "Council Developer"  # used for commits only when git has no identity configured
    git_email: str = "developer@council.local"


def _rules(raw: Any) -> Ruleset:
    """Accepts [{"action","resource","effect"}] or {"shell": {"git push *": "ask"}, "edit": "allow"}."""
    out: Ruleset = []
    if isinstance(raw, list):
        out = [Rule(r["action"], r.get("resource", "*"), r["effect"]) for r in raw]
    elif isinstance(raw, dict):
        for action, value in raw.items():
            if isinstance(value, str):
                out.append(Rule(action, "*", value))  # type: ignore[arg-type]
            else:
                out += [Rule(action, res, eff) for res, eff in value.items()]  # type: ignore[arg-type]
    return out


def load_config(workspace: Workspace) -> HarnessConfig:
    cfg = HarnessConfig()
    for path in (workspace.home / "config.json", workspace.root / "council.json", workspace.root / ".council" / "config.json"):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key in ("context_window", "compaction_keep", "auto_compact", "max_output_tokens", "snapshots", "default_agent", "max_subagent_depth", "git_name", "git_email"):
            if key in data:
                setattr(cfg, key, data[key])
        cfg.rules += _rules(data.get("permission"))
        for aid, over in (data.get("agents") or {}).items():
            cfg.agent_overrides.setdefault(aid, {}).update(over)
    return cfg
