"""Turning what happened in a run into lessons.

`facts_to_lessons` is deterministic: it reads the run's facts (conflicts, verification failures, failed features, design decisions) and writes
the lessons they imply, so something is always learned even when no model is available. `DISTILL_PROMPT` and `parse_lessons` are for the
optional second pass, where the scrum master reflects on the whole run in its own words."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RunFacts:
    project: str
    conflicts: list[dict] = field(default_factory=list)  # {"feature", "files", "with": [devs], "resolved": bool}
    failed_features: list[dict] = field(default_factory=list)  # {"feature", "owner", "skill", "reason"}
    verification_failures: list[dict] = field(default_factory=list)  # {"command", "tail"}
    decisions: list[dict] = field(default_factory=list)  # {"title", "approved", "proposer_skill", "comments"}
    unresolved_merges: int = 0
    features: int = 0


def facts_to_lessons(facts: RunFacts) -> list[dict]:
    """[{"text", "skill", "tags", "source"}] — each lesson says what to do differently, not just what happened."""
    out: list[dict] = []
    for c in facts.conflicts:
        files = ", ".join(c.get("files", [])[:4])
        if c.get("resolved", True):
            out.append({"text": f"Features built in parallel collided in {files}. When the plan has two features that touch the same file, give them one owner or make one depend on the other.",
                        "skill": "", "tags": ["merge", "conflict", "plan", "parallel"], "source": "conflict"})
        else:
            out.append({"text": f"A merge conflict in {files} could not be resolved by conversation. Split shared files so each feature owns its own, and agree the shared interface before building.",
                        "skill": "", "tags": ["merge", "conflict", "interface"], "source": "conflict"})
    for f in facts.failed_features:
        reason = re.sub(r"\s+", " ", str(f.get("reason", "")))[:160]
        out.append({"text": f"A {f.get('skill', '').lower() or 'feature'} feature ('{f.get('feature')}') failed: {reason}. Make such tasks smaller and state how each one is verified.",
                    "skill": str(f.get("skill", "")), "tags": ["failure", "task-size"], "source": "failure"})
    for v in facts.verification_failures:
        tail = re.sub(r"\s+", " ", str(v.get("tail", "")))[-160:]
        out.append({"text": f"The integrated build failed `{v.get('command')}` ({tail}). Run the project's verification command on every feature branch before merging, not only at the end.",
                    "skill": "DEVOPS", "tags": ["verification", "integration", "tests"], "source": "verification"})
    for d in facts.decisions:
        if not d.get("approved"):
            out.append({"text": f"A proposed design change ('{d.get('title')}') was rejected by the team. Check proposals against the agreed design before asking for a meeting.",
                        "skill": str(d.get("proposer_skill", "")), "tags": ["design", "meeting"], "source": "design"})
        else:
            out.append({"text": f"The design had to change during the build ('{d.get('title')}'). Settle this kind of decision in planning next time.",
                        "skill": str(d.get("proposer_skill", "")), "tags": ["design", "planning"], "source": "design"})
    if facts.unresolved_merges:
        out.append({"text": "Some branches could not be merged. Merge each feature as soon as it is done so conflicts stay small.", "skill": "", "tags": ["merge", "cadence"], "source": "conflict"})
    return out


DISTILL_PROMPT = """You are the scrum master of a software team that has just finished a project. Reflect on how the work went and write what the team should do differently on its NEXT project.

Write 3 to 6 lessons. Each must be specific, actionable, reusable on other projects (no project-specific names), and one sentence. Prefer lessons about planning, splitting work, merging, verification and design changes.

Respond only with JSON, no prose, no markdown fences:
{{"lessons":[{{"text":"...","skill":"FRONTEND|BACKEND|AIML|MLOPS|DEVOPS|DATABASE or empty for everyone","tags":["..."]}}]}}

WHAT HAPPENED
Project: {project}
Features: {features}
{events}
"""


def describe_events(facts: RunFacts) -> str:
    lines = [f"- conflict in {', '.join(c.get('files', []))} ({'resolved' if c.get('resolved', True) else 'NOT resolved'})" for c in facts.conflicts]
    lines += [f"- feature '{f.get('feature')}' failed: {str(f.get('reason'))[:120]}" for f in facts.failed_features]
    lines += [f"- verification failed: {v.get('command')}" for v in facts.verification_failures]
    lines += [f"- design change '{d.get('title')}': {'approved' if d.get('approved') else 'rejected'}" for d in facts.decisions]
    return "\n".join(lines) or "- nothing went wrong"


def parse_lessons(reply: str, limit: int = 8) -> list[dict]:
    match = re.search(r"\{.*\}", reply, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return []
    out = []
    for item in data.get("lessons", [])[:limit]:
        if isinstance(item, dict) and isinstance(item.get("text"), str) and 15 <= len(item["text"].strip()) <= 400:
            out.append({"text": item["text"].strip(), "skill": str(item.get("skill") or "").upper(), "tags": [str(t) for t in item.get("tags", [])][:6], "source": "distilled"})
    return out
