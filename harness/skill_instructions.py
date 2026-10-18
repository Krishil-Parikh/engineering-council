"""The skill list as an instruction source (opencode: packages/core/src/skill/instructions.ts)."""

from __future__ import annotations

from typing import Any

from harness.instructions import index as I
from harness.schema.permission import Ruleset
from harness.skill import SkillCatalog, available


def _entries(skills: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for s in skills:
        out += ["  <skill>", f"    <id>{s['id']}</id>", f"    <name>{s['name']}</name>", f"    <description>{s['description']}</description>", "  </skill>"]
    return out


def render(skills: list[dict[str, Any]]) -> str:
    return "\n".join([
        "Skills provide specialized instructions and workflows for specific tasks.",
        "Use the skill tool to load a skill when a task matches its description.",
        "The user may also invoke a skill directly. When that happens, its instructions appear in the conversation as a <skill_content> block, the same shape the skill tool returns. A skill that is already present this way does not need to be invoked again.",
        *(["No skills are currently available."] if not skills else ["<available_skills>", *_entries(skills), "</available_skills>"]),
    ])


def update(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> str:
    diff = I.diff_by_key(previous, current, lambda s: s["id"], lambda b, a: b["name"] != a["name"] or b["description"] != a["description"])
    # Additions and removals render as small deltas; anything else restates the full list.
    if diff["changed"] or (not diff["added"] and not diff["removed"]):
        return "\n".join(["The available skills have changed. This list supersedes the previous available skills list.", render(current)])
    parts: list[str] = []
    if diff["added"]:
        parts += ["New skills are available in addition to those previously listed:", *_entries(diff["added"])]
    if diff["removed"]:
        parts.append(f"The following skill IDs are no longer available and must not be used: {', '.join(s['id'] for s in diff['removed'])}.")
    return "\n".join(parts)


def load(catalog: SkillCatalog, permissions: Ruleset) -> I.List:
    """Lists skills the given ruleset does not deny; callers pass the merged agent and session permissions."""
    summaries = sorted(
        (
            {"id": s.id, "name": s.name, "description": s.description}
            for s in available(catalog.list(), permissions)
            if s.description is not None and s.autoinvoke is not False
        ),
        key=lambda s: s["id"],
    )
    return I.make(I.Definition(
        key="core/skill-guidance",
        read=lambda: I.REMOVED if not summaries else summaries,
        render_initial=render,
        render_changed=update,
        render_removed=lambda _: "Skill guidance is no longer available. Do not use any previously listed skill.",
    ))
