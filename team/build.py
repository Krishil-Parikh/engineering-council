"""What every project the team builds starts with: the ignore file and `AGENTS.md`, the memory file an agent entering the repository reads first.

The building itself is done by `team/engine.py` (branches, parallel developers, merges, sprints)."""

from __future__ import annotations

from meetings.models import Spec
from team.staffing import SKILL_WORDS, pick_developer  # noqa: F401 (re-exported for callers)

GITIGNORE = "__pycache__/\n*.py[cod]\n.pytest_cache/\n.venv/\nvenv/\nnode_modules/\ndist/\nbuild/\n.env\n.DS_Store\ncoverage/\n*.log\n"


def agents_md(spec: Spec) -> str:
    """The project's memory file: what an agent entering this repository would otherwise have to rediscover."""
    s = f"# {spec.project_name}\n\nBuilt from the Engineering Council specification in `docs/`. Read `docs/Design.md` before changing structure or contracts.\n\n"
    s += "## Layout\n\n```text\n" + spec.directory_tree.strip() + "\n```\n\nKeep this layout. Add files only where it says they belong.\n\n"
    s += "## Stack\n\n" + "\n".join(f"- {t.concern}: {t.choice}" for t in spec.tech_choices) + "\n\n"
    if spec.verification_commands:
        s += "## Commands\n\n```text\n" + "\n".join(spec.verification_commands) + "\n```\n\n"
    if spec.config_vars:
        s += "## Configuration\n\n" + "\n".join(f"- `{v.name}`{' (required)' if v.required else ''}: {v.description}" for v in spec.config_vars) + "\n\n"
    s += "## Project memory\n\n- `docs/CODEMAP.md`: a map of the code (files, purposes, top-level symbols), regenerated after every merge.\n- `docs/MEMORY.md`: what the team built and decided, newest last. Read it before changing something that looks deliberate.\n\n"
    s += "## Conventions\n\n- Reference requirement ids (FR-/NFR-) in test names or docstrings when a test covers one.\n- Every public contract in `docs/Design.md` must be implemented exactly as written; do not rename it.\n- Never commit secrets; read them from the environment.\n"
    return s
