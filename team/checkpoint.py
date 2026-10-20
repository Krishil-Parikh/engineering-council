"""Commit messages for the small commits a developer's work is saved in while it happens, the way a person commits a function or a test at a time.

The message comes from what changed (new files, edits, removals, where they are), so history reads `test(timer): add test_registry.py` and
`feat(core): add contracts.py, update bus.py` instead of one `Implement Exceptions` for a whole feature."""

from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath
from typing import Optional

SUBJECT_LIMIT = 72
CONFIG_NAMES = {".gitignore", ".env.example", "pyproject.toml", "requirements.txt", "setup.cfg", "package.json", "tsconfig.json", "Dockerfile", "Makefile", "AGENTS.md"}
CONFIG_SUFFIXES = (".toml", ".ini", ".cfg", ".yaml", ".yml", ".lock")
VERBS = {"A": "add", "M": "update", "D": "remove", "R": "rename", "C": "copy", "T": "update"}
GENERIC_DIRS = {"src", "lib", "app", "jarvis", "plugins", "core", "tests", "test", "docs", "backend", "frontend", "packages"}


def parse_name_status(text: str) -> list[tuple[str, str]]:
    """`git diff --cached --name-status` -> [(status letter, path)]. A rename keeps its new path."""
    changes: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            changes.append((parts[0][0], parts[-1].strip()))
    return changes


def _is_test(path: str) -> bool:
    p = PurePosixPath(path)
    return "tests" in p.parts or "test" in p.parts or p.name.startswith("test_") or p.name.endswith(("_test.py", ".test.ts", ".test.tsx", ".spec.ts"))


def _is_docs(path: str) -> bool:
    p = PurePosixPath(path)
    return p.suffix.lower() in (".md", ".rst", ".txt") or "docs" in p.parts


def _is_config(path: str) -> bool:
    p = PurePosixPath(path)
    return p.name in CONFIG_NAMES or p.suffix.lower() in CONFIG_SUFFIXES


def classify(paths: list[str], summary: str = "") -> str:
    """test / docs / chore / fix / feat, from where the changes are (and a hint in the developer's own words)."""
    if paths and all(_is_test(p) for p in paths):
        return "test"
    if paths and all(_is_docs(p) for p in paths):
        return "docs"
    if paths and all(_is_config(p) for p in paths):
        return "chore"
    if summary and any(word in summary.lower() for word in ("fix", "bug", "repair", "correct")):
        return "fix"
    return "feat"


def scope_of(paths: list[str], fallback: str = "") -> str:
    """The part of the project the change is about: the most specific folder that is not just a layout folder (`jarvis/plugins/timer/x.py` -> timer)."""
    votes: Counter[str] = Counter()
    for path in paths:
        parts = list(PurePosixPath(path).parts)
        stem = PurePosixPath(path).stem
        if _is_test(path) and stem.startswith("test_") and len(stem) > 5:
            votes[stem[5:].split("_")[0]] += 1
            continue
        folders = [p for p in parts[:-1] if p not in GENERIC_DIRS]
        if folders:
            votes[folders[-1]] += 1
        else:
            generic = [p for p in parts[:-1]]
            votes[generic[-1] if generic else (fallback or stem)] += 1
    return votes.most_common(1)[0][0] if votes else fallback


def _phrase(changes: list[tuple[str, str]]) -> str:
    groups: dict[str, list[str]] = {}
    for status, path in changes:
        groups.setdefault(VERBS.get(status, "update"), []).append(PurePosixPath(path).name)
    ordered = [v for v in ("add", "update", "rename", "remove", "copy") if v in groups]
    return "; ".join(f"{verb} {', '.join(dict.fromkeys(groups[verb]))}" for verb in ordered)


def build_message(changes: list[tuple[str, str]], feature: str = "", task: str = "", note: str = "") -> Optional[tuple[str, str]]:
    """(subject, body) for a commit of `changes`, or None when nothing changed. The subject is at most 72 characters."""
    if not changes:
        return None
    paths = [p for _, p in changes]
    kind = classify(paths, note)
    scope = scope_of(paths, feature)
    head = f"{kind}({scope}): " if scope else f"{kind}: "
    phrase = _phrase(changes)
    if len(head) + len(phrase) > SUBJECT_LIMIT:  # too many files to name: the first one and a count
        verb, name = VERBS.get(changes[0][0], "update"), PurePosixPath(changes[0][1]).name
        others = len({PurePosixPath(p).name for p in paths}) - 1
        phrase = f"{verb} {name}" + (f" and {others} more" if others else "")
    subject = (head + phrase)[:SUBJECT_LIMIT]
    lines = []
    if task:
        lines.append(f"Task: {task}")
    if feature:
        lines.append(f"Feature: {feature}")
    if note:
        lines.append("")
        lines.append(" ".join(note.split())[:300])
    lines.append("")
    lines.extend(f"{VERBS.get(s, 'update')}: {p}" for s, p in changes[:15])
    if len(changes) > 15:
        lines.append(f"... and {len(changes) - 15} more files")
    return subject, "\n".join(lines).strip()
