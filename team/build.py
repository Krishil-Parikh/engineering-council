"""After the meeting: the six developers build the project from the agreed specification using the coding harness.

The scrum master's job here is pure orchestration in Python: take the implementation sequence in order, hand each step to the
developer whose skill fits it best, let that developer work in the project with the full harness (files, shell, git, subagents,
memory), then run the specification's verification commands and send failures back to a developer."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from harness.legacy.agents import developer_agent
from harness.legacy.config import HarnessConfig
from harness.legacy.runner import HarnessError, Runner
from harness.legacy.types import ChatModel, Observer
from harness.legacy.workspace import Workspace
from meetings.errors import MeetingError
from meetings.models import Roster, Spec, Step
from meetings.prompts import SKILL_LENSES
from meetings.storage import write_text

SKILL_WORDS: dict[str, tuple[str, ...]] = {
    "FRONTEND": ("ui", "screen", "view", "component", "css", "html", "react", "tui", "terminal", "page", "render", "cli", "interface", "layout", "form"),
    "BACKEND": ("api", "endpoint", "service", "server", "handler", "auth", "route", "logic", "controller", "worker", "queue", "core", "engine", "parser"),
    "AIML": ("model", "prompt", "llm", "embedding", "classif", "train", "inference", "ml ", "gemini", "agent", "rag", "retriev", "score"),
    "MLOPS": ("pipeline", "registry", "monitor", "drift", "experiment", "evaluation", "eval", "feature store", "serving"),
    "DEVOPS": ("docker", "ci", "github actions", "deploy", "infra", "container", "release", "packag", "build script", "makefile", "workflow", "config"),
    "DATABASE": ("schema", "migration", "sql", "table", "query", "storage", "index", "persist", "repository", "orm", "database", "store"),
}


GITIGNORE = "__pycache__/\n*.py[cod]\n.pytest_cache/\n.venv/\nvenv/\nnode_modules/\ndist/\nbuild/\n.env\n.DS_Store\ncoverage/\n*.log\n"


@dataclass
class StepReport:
    order: int
    title: str
    developer: str
    ok: bool
    summary: str


@dataclass
class BuildResult:
    project_dir: Path
    steps: list[StepReport] = field(default_factory=list)
    verification: list[tuple[str, int, str]] = field(default_factory=list)  # command, exit code, tail of output
    passed: bool = False
    warnings: list[str] = field(default_factory=list)


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


def agents_md(spec: Spec) -> str:
    """The project's memory file: what an agent entering this repository would otherwise have to rediscover."""
    s = f"# {spec.project_name}\n\nBuilt from the Engineering Council specification in `docs/`. Read `docs/Design.md` before changing structure or contracts.\n\n"
    s += "## Layout\n\n```text\n" + spec.directory_tree.strip() + "\n```\n\nKeep this layout. Add files only where it says they belong.\n\n"
    s += "## Stack\n\n" + "\n".join(f"- {t.concern}: {t.choice}" for t in spec.tech_choices) + "\n\n"
    if spec.verification_commands:
        s += "## Commands\n\n```text\n" + "\n".join(spec.verification_commands) + "\n```\n\n"
    if spec.config_vars:
        s += "## Configuration\n\n" + "\n".join(f"- `{v.name}`{' (required)' if v.required else ''}: {v.description}" for v in spec.config_vars) + "\n\n"
    s += "## Conventions\n\n- Reference requirement ids (FR-/NFR-) in test names or docstrings when a test covers one.\n- Every public contract in `docs/Design.md` must be implemented exactly as written; do not rename it.\n- Never commit secrets; read them from the environment.\n"
    return s


def step_prompt(spec: Spec, step: Step, done: list[StepReport], dev: str) -> str:
    comps = [c for c in spec.components if c.name.lower() in f"{step.title} {step.details}".lower() or (c.path and c.path.lower() in step.details.lower())]
    if not comps:
        comps = spec.components
    req_ids = {r for c in comps for r in c.requirement_ids}
    acs = [a for a in spec.acceptance_criteria if a.requirement_id in req_ids]
    p = f"Implementation step {step.order} of {len(spec.implementation_sequence)}: {step.title}\n\n{step.details}\n\n"
    p += "Components this touches:\n" + "\n".join(f"- {c.name} ({c.path}): {c.responsibility}" for c in comps) + "\n\n"
    if spec.contracts:
        p += "Contracts to implement exactly (full text in docs/Design.md):\n" + "\n".join(f"- {k.name} [{k.kind}]: {k.signature}" for k in spec.contracts[:25]) + "\n\n"
    if acs:
        p += "Acceptance criteria to satisfy:\n" + "\n".join(f"- {a.id} ({a.requirement_id}): given {a.given}, when {a.when}, then {a.then}" for a in acs[:20]) + "\n\n"
    if done:
        p += "Already built by the pod:\n" + "\n".join(f"- step {d.order} {d.title} ({d.developer}): {'done' if d.ok else 'INCOMPLETE'}" for d in done) + "\n\n"
    p += (
        "How to work: read AGENTS.md and the relevant part of docs/ first, then implement only this step in the files the directory layout names, "
        "write or update tests for it, run the project's test command and fix failures, and when it passes commit with the message "
        f"`step {step.order}: {step.title}` (do not push). Finish with a short report of what you built, how you verified it and anything unfinished."
    )
    return p


def run_shell(command: str, cwd: Path, timeout: int = 300) -> tuple[int, str]:
    from harness.legacy.tools.shell import pick_shell

    argv, _ = pick_shell()
    try:
        out = subprocess.run([*argv, command], cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return out.returncode, (out.stdout + out.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as exc:
        return 127, str(exc)


async def build_project(
    meeting_dir: Path, model: ChatModel, *, project_dir: Path | None = None, asker: Callable | None = None, observer: Observer | None = None,
    config: HarnessConfig | None = None, fix_rounds: int = 2, on_step: Callable[[str], None] = lambda s: None,
) -> BuildResult:
    spec_path = meeting_dir / "specification.json"
    if not spec_path.exists():
        raise MeetingError(f"{meeting_dir} has no specification.json; finish the meeting first.")
    spec = Spec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    roster_path = meeting_dir / "roster.json"
    roster = Roster.model_validate_json(roster_path.read_text(encoding="utf-8")).skills if roster_path.exists() else {}
    if not roster:
        raise MeetingError("roster.json is missing: the developers' skills are unknown.")

    project = (project_dir or meeting_dir / "project").resolve()
    project.mkdir(parents=True, exist_ok=True)
    (project / "docs").mkdir(exist_ok=True)
    for doc in ("PRD.md", "Technical_Approach.md", "Design.md"):
        if (meeting_dir / doc).exists():
            shutil.copy2(meeting_dir / doc, project / "docs" / doc)
    if not (project / ".gitignore").exists():
        write_text(project / ".gitignore", GITIGNORE)
    if not (project / "AGENTS.md").exists():
        write_text(project / "AGENTS.md", agents_md(spec))
    result = BuildResult(project)
    if not (project / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=project, capture_output=True)

    ws = Workspace(project)
    devs = {}
    for dev, skill in roster.items():
        lens = SKILL_LENSES.get(skill, {"title": skill.title(), "sees": "", "asks": ""})
        devs[dev.lower()] = developer_agent(dev, lens["title"], lens["sees"], lens["asks"])
    runner = Runner(ws, model, config=config, asker=asker, observer=observer, agents=devs)
    # the first commit records the starting point (docs + AGENTS.md) so every later step is a clean diff
    run_shell('git add -A && git -c user.name="Council Developer" -c user.email="developer@council.local" commit -q -m "Add specification and project memory" --allow-empty', project)

    load: dict[str, int] = {}
    try:
        for step in sorted(spec.implementation_sequence, key=lambda s: s.order):
            dev = pick_developer(step, spec, roster, load)
            load[dev] = load.get(dev, 0) + 1
            on_step(f"step {step.order}/{len(spec.implementation_sequence)}: {step.title} -> {dev} ({roster[dev].title()})")
            session = runner.new_session(dev.lower(), title=f"step {step.order}: {step.title}")
            try:
                res = await runner.run(session, step_prompt(spec, step, result.steps, dev), dev.lower())
                ok, summary = res.stopped == "completed", res.text
            except HarnessError as exc:
                ok, summary = False, f"Stopped: {exc}"
                result.warnings.append(f"step {step.order} ({dev}) could not finish: {exc}")
            result.steps.append(StepReport(step.order, step.title, dev, ok, summary))
            if not ok:
                result.warnings.append(f"step {step.order} {step.title}: {summary[:200]}")

        # final gate: the specification's own verification commands, with bounded repair rounds
        commands = [c for c in spec.verification_commands if c.strip() and not c.lower().startswith("proposed")]
        for attempt in range(fix_rounds + 1):
            result.verification = [(c, *run_shell(c, project)) for c in commands]
            failing = [(c, code, out) for c, code, out in result.verification if code != 0]
            if not failing:
                result.passed = bool(commands) or all(s.ok for s in result.steps)
                break
            if attempt == fix_rounds:
                result.warnings.append("Verification still failing after the repair rounds: " + ", ".join(c for c, _, _ in failing))
                break
            dev = pick_developer(Step(order=0, title="fix failing verification", details=" ".join(c for c, _, _ in failing)), spec, roster, load)
            on_step(f"verification failed ({len(failing)}); asking {dev} to fix (round {attempt + 1}/{fix_rounds})")
            session = runner.new_session(dev.lower(), title="fix verification")
            report = "\n\n".join(f"$ {c}\nexit code {code}\n{out}" for c, code, out in failing)
            try:
                await runner.run(session, f"The project's verification commands fail. Find the root cause and fix it with the smallest correct change, then run them again.\n\n{report}\n\nCommit the fix with the message `fix: verification` (do not push).", dev.lower())
            except HarnessError as exc:
                result.warnings.append(f"repair by {dev} failed: {exc}")
                break
    finally:
        await runner.close()

    write_text(meeting_dir / "build_report.md", render_report(spec, result, roster))
    return result


def render_report(spec: Spec, res: BuildResult, roster: dict[str, str]) -> str:
    s = f"# Build Report — {spec.project_name}\n\n**Project:** `{res.project_dir}`  \n**Result:** {'verification passed' if res.passed else 'NOT verified'}\n\n## Steps\n\n"
    s += "| Step | Developer | Result | Summary |\n|---|---|---|---|\n"
    for r in res.steps:
        summary = re.sub(r"[|\n]+", " ", r.summary)[:240]
        s += f"| {r.order}. {r.title} | {r.developer} ({roster.get(r.developer, '').title()}) | {'done' if r.ok else 'incomplete'} | {summary} |\n"
    if res.verification:
        s += "\n## Verification\n\n| Command | Exit |\n|---|---|\n" + "".join(f"| `{c}` | {code} |\n" for c, code, _ in res.verification)
    if res.warnings:
        s += "\n## Warnings\n\n" + "\n".join(f"- {w}" for w in res.warnings) + "\n"
    return s
