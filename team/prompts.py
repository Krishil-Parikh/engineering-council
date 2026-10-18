"""The messages the engine sends: the task a developer is given, the questions asked about a merge conflict, the repair request."""

from __future__ import annotations

from meetings.models import Spec
from team.plan import Feature, Task


def spec_brief(spec: Spec, limit: int = 12000) -> str:
    """A compact rendering of the specification for planning."""
    parts = [f"Project: {spec.project_name}", "Directory layout:\n" + spec.directory_tree.strip()]
    parts.append("Components:\n" + "\n".join(f"- {c.name} ({c.path}): {c.responsibility}" for c in spec.components))
    if spec.contracts:
        parts.append("Contracts:\n" + "\n".join(f"- {k.name} [{k.kind}]: {k.signature}" for k in spec.contracts[:40]))
    parts.append("Tech choices:\n" + "\n".join(f"- {t.concern}: {t.choice}" for t in spec.tech_choices))
    parts.append("Implementation sequence:\n" + "\n".join(f"{s.order}. {s.title}: {s.details}" for s in sorted(spec.implementation_sequence, key=lambda s: s.order)))
    if spec.verification_commands:
        parts.append("Verification commands:\n" + "\n".join(spec.verification_commands))
    return "\n\n".join(parts)[:limit]


def task_prompt(spec: Spec, feature: Feature, task: Task, index: int, others: list[str], memory: str = "") -> str:
    text = f"{feature.title} {task.title} {task.details}".lower()
    comps = [c for c in spec.components if c.name.lower() in text or (c.path and c.path.lower() in text)] or spec.components
    req_ids = {r for c in comps for r in c.requirement_ids}
    acs = [a for a in spec.acceptance_criteria if a.requirement_id in req_ids]
    p = f"Feature: {feature.title}  (branch {feature.branch}, task {index} of {len(feature.tasks)})\nTask: {task.title}\n\n{task.details}\n\n"
    if feature.summary:
        p += f"What this feature is for: {feature.summary}\n\n"
    p += "Components this touches:\n" + "\n".join(f"- {c.name} ({c.path}): {c.responsibility}" for c in comps) + "\n\n"
    if spec.contracts:
        p += "Contracts to implement exactly (full text in docs/Design.md):\n" + "\n".join(f"- {k.name} [{k.kind}]: {k.signature}" for k in spec.contracts[:25]) + "\n\n"
    if acs:
        p += "Acceptance criteria to satisfy:\n" + "\n".join(f"- {a.id} ({a.requirement_id}): given {a.given}, when {a.when}, then {a.then}" for a in acs[:20]) + "\n\n"
    if others:
        p += "Teammates are building these in parallel on their own branches (do not do their work):\n" + "\n".join(f"- {o}" for o in others[:20]) + "\n\n"
    if memory:
        p += f"What the team already knows:\n{memory}\n\n"
    p += (
        "How to work: read AGENTS.md and the relevant part of docs/ first, then do this task in the files the directory layout names, write or update tests "
        f"for it, run the project's test command and fix failures. When it passes, commit with the message `{feature.id}: {task.title}` and publish the branch: `git push origin {feature.branch}`. If the push fails, read the error, fix the cause (fetch and rebase, finish a half-done merge, whatever it is) and push again; never force-push. "
        "Finish with a short report of what you built, how you verified it and anything unfinished."
    )
    return p


def conflict_ask(branch: str, owner: str, files: list[str], texts: dict[str, str], feedback: str = "") -> str:
    shown = "\n\n".join(f"=== {f} ===\n{texts.get(f, '')}" for f in files)
    p = (
        f"Merging {branch} (owned by {owner}) into the integration branch produced conflicts in: {', '.join(files)}.\n\n"
        f"The files with the conflict markers (ours = the integration branch, theirs = {branch}):\n\n{shown}\n\n"
        "From your point of view, explain what your change in each file was meant to do and how the two sides should be combined so that both "
        "intentions survive. Be concrete: name the functions, lines or fields to keep, and anything that must change to make them fit."
    )
    return p + (f"\n\nThe previous attempt failed: {feedback}" if feedback else "")


def conflict_resolution(branch: str, files: list[str], texts: dict[str, str], replies: dict[str, str], feedback: str = "") -> str:
    talk = "\n\n".join(f"{dev} says:\n{reply}" for dev, reply in replies.items())
    p = (
        f"You are merging {branch} into the integration branch and these files conflict: {', '.join(files)}. The conflict markers are in the working "
        f"tree now.\n\nThe developers involved explained their intent:\n\n{talk}\n\n"
        "Resolve every conflicted file so both intentions survive: edit the files, remove all conflict markers (<<<<<<<, =======, >>>>>>>), run the "
        "project's tests and fix anything the merge broke. Do not commit and do not push. Finish with a short report of how you combined the changes."
    )
    return p + (f"\n\nYour previous attempt was not accepted: {feedback}" if feedback else "")


def repair_prompt(failing: list[tuple[str, int, str]]) -> str:
    report = "\n\n".join(f"$ {c}\nexit code {code}\n{out}" for c, code, out in failing)
    return (
        "The project's verification commands fail on the integration branch. Find the root cause and fix it with the smallest correct change, then "
        f"run them again.\n\n{report}\n\nCommit the fix with the message `fix: verification` and push your branch (`git push origin <your branch>`; if that fails, find out why and fix it)."
    )


def design_followup(adrs: list[str]) -> str:
    listing = "\n".join(f"- {a}" for a in adrs)
    return (
        "The team approved a design change for this feature and it is recorded here:\n"
        f"{listing}\n\n"
        "docs/Design.md still describes the old design. Update it now so the document matches what you built: the changed contract, component boundary "
        "or data model, in the same style as the rest of the document. Keep every other part as it is, and keep any diagrams consistent. "
        "Commit the change with the message `docs: apply approved design change`, push your branch, and reply with one sentence saying what you changed."
    )
