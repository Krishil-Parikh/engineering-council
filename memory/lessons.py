"""Cross-project memory: what the team learns on one project and carries to the next, the way a person gets better with experience.

  lessons.jsonl   short, specific lessons ("two features that edit the same file collide at merge; give them one owner"). Each remembers the
                  projects it came from and how often it has been seen. A near-duplicate of a known lesson strengthens it instead of piling up.
  profiles.json   what each skill has worked on so far: projects, features, merges that needed a conversation, verification failures.
  skills/         lessons seen on at least two projects are *promoted* into skill files (SKILL.md) the harness discovers, so they are offered to
                  every developer on every future project without anyone having to remember to ask.

Recall is plain keyword scoring (no embeddings): query words against the lesson text and tags, weighted by how often the lesson has been
confirmed, how recently, and whether it is about the developer's skill."""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Optional

DUPLICATE_RATIO = 0.82
HALF_LIFE_DAYS = 180.0
PROMOTE_MIN_PROJECTS = 2


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]{3,}", text.lower())


def _norm(text: str) -> str:
    return " ".join(_words(text))


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "general"


@dataclass
class Lesson:
    id: str
    text: str
    skill: str = ""  # "" = applies to everyone
    tags: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    seen: int = 1
    source: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)


@dataclass
class Profile:
    projects: int = 0
    features: int = 0
    conversations: int = 0  # merges that needed a talk
    failures: int = 0
    notes: list[str] = field(default_factory=list)


class LessonStore:
    def __init__(self, directory: Path) -> None:
        self.dir = Path(directory)
        self.lessons_file = self.dir / "lessons.jsonl"
        self.profiles_file = self.dir / "profiles.json"
        self.skills_dir = self.dir / "skills"
        self.lessons: list[Lesson] = []
        self.profiles: dict[str, Profile] = {}
        self.load()

    # ------------------------------------------------------------------ persistence

    def load(self) -> None:
        self.lessons = []
        if self.lessons_file.exists():
            for line in self.lessons_file.read_text(encoding="utf-8").splitlines():
                try:
                    self.lessons.append(Lesson(**json.loads(line)))
                except (ValueError, TypeError):
                    continue  # a damaged line costs one lesson, not the memory
        self.profiles = {}
        if self.profiles_file.exists():
            try:
                self.profiles = {k: Profile(**v) for k, v in json.loads(self.profiles_file.read_text(encoding="utf-8")).items()}
            except (ValueError, TypeError):
                self.profiles = {}

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.lessons_file.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(asdict(l), ensure_ascii=False) + "\n" for l in self.lessons), encoding="utf-8")
        tmp.replace(self.lessons_file)
        self.profiles_file.write_text(json.dumps({k: asdict(v) for k, v in self.profiles.items()}, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ learning

    def add(self, text: str, skill: str = "", tags: Iterable[str] = (), project: str = "", source: str = "") -> Lesson:
        """Records a lesson; a near-duplicate (same skill or general) strengthens the existing one instead."""
        text = text.strip()
        key = _norm(text)
        for known in self.lessons:
            if known.skill in (skill, "") or skill == "":
                if SequenceMatcher(None, key, _norm(known.text)).ratio() >= DUPLICATE_RATIO:
                    known.seen += 1
                    known.updated = time.time()
                    if project and project not in known.projects:
                        known.projects.append(project)
                    for t in tags:
                        if t not in known.tags:
                            known.tags.append(t)
                    return known
        lesson = Lesson(f"L{len(self.lessons) + 1:04d}-{int(time.time()) % 100000}", text, skill, list(dict.fromkeys(tags)), [project] if project else [], source=source)
        self.lessons.append(lesson)
        return lesson

    def prune(self, max_lessons: int = 400) -> int:
        """Keeps the most useful lessons: confirmed often, on several projects, recently."""
        if len(self.lessons) <= max_lessons:
            return 0
        ranked = sorted(self.lessons, key=self._worth, reverse=True)
        dropped = len(self.lessons) - max_lessons
        self.lessons = ranked[:max_lessons]
        return dropped

    def _worth(self, lesson: Lesson, now: Optional[float] = None) -> float:
        age_days = ((now or time.time()) - lesson.updated) / 86400
        return (lesson.seen + 2 * len(lesson.projects)) * math.pow(0.5, age_days / HALF_LIFE_DAYS)

    # ------------------------------------------------------------------ recall

    def recall(self, query: str, skill: Optional[str] = None, k: int = 5, exclude_project: Optional[str] = None) -> list[Lesson]:
        words = set(_words(query))
        if not words:
            return []
        docs = [set(_words(l.text + " " + " ".join(l.tags))) for l in self.lessons]
        n = max(len(self.lessons), 1)
        scored = []
        for lesson, doc in zip(self.lessons, docs):
            if skill and lesson.skill not in ("", skill):
                continue
            overlap = words & doc
            if not overlap:
                continue
            idf = sum(math.log(1 + n / (1 + sum(1 for d in docs if w in d))) for w in overlap)
            bonus = 1.3 if skill and lesson.skill == skill else 1.0
            scored.append((idf * bonus * (1 + math.log(lesson.seen)) * (0.5 + 0.5 * self._worth(lesson) / (1 + self._worth(lesson))), lesson))
        scored.sort(key=lambda t: -t[0])
        return [l for _, l in scored[:k]]

    def render(self, lessons: list[Lesson], heading: str = "Lessons from earlier projects") -> str:
        if not lessons:
            return ""
        return f"{heading} (apply them where they fit; they may not):\n" + "\n".join(f"- {l.text}" for l in lessons)

    # ------------------------------------------------------------------ profiles

    def profile(self, skill: str) -> Profile:
        return self.profiles.setdefault(skill, Profile())

    def record_run(self, skill: str, features: int = 0, conversations: int = 0, failures: int = 0, note: str = "") -> None:
        p = self.profile(skill)
        p.projects += 1
        p.features += features
        p.conversations += conversations
        p.failures += failures
        if note:
            p.notes = ([*p.notes, note])[-8:]

    def describe(self, skill: str) -> str:
        p = self.profiles.get(skill)
        if p is None or p.projects == 0:
            return ""
        return f"Experience: {p.projects} earlier project(s), {p.features} feature(s) built, {p.conversations} merge conversation(s)" + (f", {p.failures} failure(s)" if p.failures else "") + "."

    # ------------------------------------------------------------------ evolving skills

    def promotable(self, min_projects: int = PROMOTE_MIN_PROJECTS) -> list[Lesson]:
        return [l for l in self.lessons if len(set(l.projects)) >= min_projects]

    def write_skills(self, min_projects: int = PROMOTE_MIN_PROJECTS) -> list[Path]:
        """One SKILL.md per skill area holding the lessons confirmed on several projects. Returns the files written."""
        groups: dict[str, list[Lesson]] = {}
        for lesson in self.promotable(min_projects):
            groups.setdefault(lesson.skill or "general", []).append(lesson)
        written = []
        for area, items in groups.items():
            name = f"council-{slug(area)}-lessons"
            body = "\n".join(f"- {l.text}  _(seen on {len(set(l.projects))} projects)_" for l in sorted(items, key=lambda l: -l.seen))
            doc = (
                f"---\nname: {name}\ndescription: Lessons the team learned across projects about {area.lower()} work. Load it before planning or building "
                f"{area.lower()} features.\n---\n\n# Lessons: {area.title()}\n\nThese were confirmed on more than one project.\n\n{body}\n"
            )
            path = self.skills_dir / name / "SKILL.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(doc.encode("utf-8"))
            written.append(path)
        return written
