"""Matching work to the developer whose skill fits it (words in the work against each skill's vocabulary)."""

from __future__ import annotations

import re

from meetings.models import Spec, Step

SKILL_WORDS: dict[str, tuple[str, ...]] = {
    "FRONTEND": ("ui", "screen", "view", "component", "css", "html", "react", "tui", "terminal", "page", "render", "cli", "interface", "layout", "form"),
    "BACKEND": ("api", "endpoint", "service", "server", "handler", "auth", "route", "logic", "controller", "worker", "queue", "core", "engine", "parser"),
    "AIML": ("model", "prompt", "llm", "embedding", "classif", "train", "inference", "ml ", "gemini", "agent", "rag", "retriev", "score"),
    "MLOPS": ("pipeline", "registry", "monitor", "drift", "experiment", "evaluation", "eval", "feature store", "serving"),
    "DEVOPS": ("docker", "ci", "github actions", "deploy", "infra", "container", "release", "packag", "build script", "makefile", "workflow", "config"),
    "DATABASE": ("schema", "migration", "sql", "table", "query", "storage", "index", "persist", "repository", "orm", "database", "store"),
}


def pick_developer(step: Step, spec: Spec, roster: dict[str, str], load: dict[str, int]) -> str:
    """The developer whose skill best matches the words of the step and the components it names; ties go to whoever has built least."""
    text = f"{step.title} {step.details}".lower()
    for c in spec.components:
        if c.name.lower() in text or (c.path and c.path.lower() in text):
            text += f" {c.name} {c.path} {c.responsibility}".lower()
    best, best_score = None, -1.0
    for dev, skill in roster.items():
        score = sum(len(re.findall(r"\b" + re.escape(w.strip()), text)) for w in SKILL_WORDS.get(skill, ())) - 0.1 * load.get(dev, 0)
        if score > best_score:
            best, best_score = dev, score
    return best or next(iter(roster))
