"""Project memory the way opencode does it: instruction files (AGENTS.md / CLAUDE.md) that are discovered, injected and kept
current, plus skills (SKILL.md folders) the agent can load on demand. Conversation memory lives in compaction.py."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from coding_harness.workspace import Workspace

INSTRUCTION_NAMES = ("AGENTS.md", "CLAUDE.md")  # the first one found in a directory is used
MAX_INSTRUCTION_CHARS = 24_000


def _first_instruction(directory: Path) -> Path | None:
    for name in INSTRUCTION_NAMES:
        p = directory / name
        if p.is_file():
            return p
    return None


@dataclass
class InstructionFile:
    path: Path
    content: str

    @property
    def digest(self) -> str:
        return hashlib.sha1(self.content.encode("utf-8", "ignore")).hexdigest()[:12]


class Instructions:
    """Global file first, then project files from the working directory up to the project root (nearest first)."""

    def __init__(self, workspace: Workspace) -> None:
        self.ws = workspace
        self._known: dict[str, str] = {}  # path -> digest of what the model has been shown
        self._nearby_shown: set[str] = set()

    def _read(self, p: Path) -> InstructionFile | None:
        try:
            text = p.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
        return InstructionFile(p, text[:MAX_INSTRUCTION_CHARS]) if text else None

    def discover(self) -> list[InstructionFile]:
        found: list[InstructionFile] = []
        g = _first_instruction(self.ws.home)
        if g and (f := self._read(g)):
            found.append(f)
        d = self.ws.cwd
        while True:
            p = _first_instruction(d)
            if p and (f := self._read(p)):
                found.append(f)
            if d == self.ws.root or d.parent == d:
                break
            d = d.parent
        return found

    @staticmethod
    def render(files: list[InstructionFile]) -> str:
        if not files:
            return ""
        parts = [f"Instructions from: {f.path.as_posix()}\n{f.content}" for f in files]
        return "Project and user instructions. Follow them; they override your defaults.\n\n" + "\n\n".join(parts)

    def system_block(self) -> str:
        files = self.discover()
        self._known = {f.path.as_posix(): f.digest for f in files}
        return self.render(files)

    def updates(self) -> str:
        """A reminder describing instruction files that changed, appeared or disappeared since the model last saw them."""
        files = {f.path.as_posix(): f for f in self.discover()}
        notes = []
        for path, f in files.items():
            if path not in self._known:
                notes.append(f"New instructions from: {path}\n{f.content}")
            elif self._known[path] != f.digest:
                notes.append(f"Updated instructions from: {path} (replaces the earlier version)\n{f.content}")
        for path in self._known:
            if path not in files:
                notes.append(f"The instructions from {path} no longer apply.")
        self._known = {p: f.digest for p, f in files.items()}
        return "\n\n".join(notes)

    def nearby(self, file: Path) -> str:
        """Instruction files in folders between a just-read file and the project root that were not loaded yet."""
        shown = {Path(p) for p in self._known}
        out: list[str] = []
        d = file.parent if file.is_file() else file
        while True:
            try:
                d.relative_to(self.ws.root)
            except ValueError:
                break
            p = _first_instruction(d)
            if p and p not in shown and p.as_posix() not in self._nearby_shown and d != self.ws.root:
                if f := self._read(p):
                    self._nearby_shown.add(p.as_posix())
                    out.append(f"Instructions from: {p.as_posix()}\n{f.content}")
            if d == self.ws.root or d.parent == d:
                break
            d = d.parent
        return ("<system-reminder>\n" + "\n\n".join(out) + "\n</system-reminder>") if out else ""


# --------------------------------------------------------------------------- skills


@dataclass
class Skill:
    name: str
    description: str
    body: str
    directory: Path


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip("\"'")
    return meta, m.group(2).strip()


class SkillRegistry:
    """Skills are folders holding a SKILL.md with `name` and `description` front matter."""

    DIRS = (".council/skills", ".claude/skills", ".agents/skills")

    def __init__(self, workspace: Workspace, extra_dirs: list[Path] | None = None) -> None:
        self.ws = workspace
        self.extra = extra_dirs or []
        self._skills: dict[str, Skill] | None = None

    def _roots(self) -> list[Path]:
        roots = [self.ws.home / "skills", Path.home() / ".claude" / "skills", Path.home() / ".agents" / "skills"]
        d = self.ws.cwd
        while True:
            roots += [d / rel for rel in self.DIRS]
            if d == self.ws.root or d.parent == d:
                break
            d = d.parent
        return [*roots, *self.extra]  # later entries override earlier ones, so the project beats the user's global skills

    def reload(self) -> None:
        self._skills = None

    def list(self) -> list[Skill]:
        if self._skills is None:
            found: dict[str, Skill] = {}
            for root in self._roots():
                if not root.is_dir():
                    continue
                for md in sorted(root.glob("*/SKILL.md")):
                    try:
                        meta, body = _frontmatter(md.read_text(encoding="utf-8", errors="replace"))
                    except OSError:
                        continue
                    name = meta.get("name") or md.parent.name
                    found[name] = Skill(name, meta.get("description", ""), body, md.parent)
            self._skills = found
        return list(self._skills.values())

    def get(self, name: str) -> Skill | None:
        return next((s for s in self.list() if s.name == name), None)
