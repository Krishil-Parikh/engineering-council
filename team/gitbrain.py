"""When git fails, the team understands why and fixes it, instead of giving up.

opencode's agents work this way: a failed command is not the end, it is information. The error comes back to the model, which reads it,
decides what is wrong and runs something else. The engine's own git steps (publishing a branch, checking one out, committing, merging) get the
same treatment:

  1. a quick, certain fix for the failures that have one (a rejected push is a fetch and a rebase; a stale lock file is deleted; a half-finished
     merge is abandoned), then the step is tried again;
  2. if that is not enough, the developer's own agent is shown what failed, what git says about the repository, and what the step was meant to
     achieve. It investigates and fixes it with real git commands (rebase, merge, stash, resolve, re-create a branch...), under the same
     permission rules as always (nothing forced, nothing on main, no tampering with hooks);
  3. the step is tried again, up to a limit. Only then does it fail, with the whole story attached.

Every attempt is reported as an event so a person watching can see what happened."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from team.repo import RepoError, TeamRepo

FIX_PROMPT = """A git step failed. You are in your own clone of the repository. Work out why and fix it, so that the step can be run again and succeed.

THE STEP: {goal}
THE ERROR:
{error}

WHAT GIT SAYS ABOUT YOUR CLONE NOW:
{state}

{earlier}How to work:
- Read the error carefully, then look (git status, git log, git branch -vv, git diff) before you change anything.
- Fix the cause, not the symptom. Typical causes: the remote branch moved (fetch, then rebase or merge it in), uncommitted changes in the way (commit them, or stash them), a half-finished merge or rebase (finish it or abort it), a stale .git/index.lock, a branch that does not exist yet, diverged histories.
- Never lose work: do not discard commits or uncommitted changes you cannot account for. Prefer rebase or merge over reset.
- You may push your own feature or fix branch. You may not push main or master, force-push, delete branches, or touch hooks, remotes or git configuration; those are refused, so do not try.
- If merging brings in conflicts, resolve every one of them so that both sides' intent survives, remove all conflict markers, and run the tests.
- Do not do the step itself unless it is the fix. When you are done, say in two or three sentences what was wrong and what you changed."""


@dataclass
class Attempt:
    goal: str
    error: str
    fixed_by: str = ""  # "quick:<what>" | "agent" | ""
    note: str = ""


@dataclass
class GitBrain:
    repo: TeamRepo
    harness_for: Callable[[str], Any]
    agent_for: Callable[[str], str]
    rounds: int = 2
    timeout: float = 600.0
    emit: Callable[..., None] = lambda kind, **data: None
    history: list[Attempt] = field(default_factory=list)

    # ------------------------------------------------------------------ the loop

    async def run(self, dev: str, goal: str, fn: Callable[..., Any], *args: Any, branch: Optional[str] = None, **kw: Any) -> Any:
        """Runs a git step in a thread. If it raises RepoError, diagnoses and fixes, then tries again; raises only when every round failed."""
        errors: list[str] = []
        for attempt in range(self.rounds + 1):
            try:
                return await asyncio.to_thread(fn, *args, **kw)
            except RepoError as exc:
                errors.append(str(exc))
                record = Attempt(goal, str(exc))
                self.history.append(record)
                if attempt == self.rounds:
                    self.emit("git-gave-up", dev=dev, goal=goal, error=str(exc)[:300])
                    raise RepoError(f"{goal}: still failing after {self.rounds} repair attempt(s). Last error: {exc}") from exc
                self.emit("git-trouble", dev=dev, goal=goal, error=str(exc)[:300], attempt=attempt + 1)
                quick = await asyncio.to_thread(self.quick_fix, dev, str(exc), branch) if attempt == 0 else ""
                if quick:
                    record.fixed_by = f"quick:{quick}"
                    self.emit("git-fixed", dev=dev, goal=goal, how=quick)
                    continue
                note = await self.ask_agent(dev, goal, str(exc), branch, errors[:-1])
                record.fixed_by, record.note = ("agent" if note else ""), note
                self.emit("git-fixed" if note else "git-unfixed", dev=dev, goal=goal, how="agent", note=note[:300])
        raise AssertionError("unreachable")

    # ------------------------------------------------------------------ certain fixes

    def quick_fix(self, dev: str, error: str, branch: Optional[str]) -> str:
        """The failures that have exactly one sensible answer. Returns what was done, or '' if nothing applied."""
        text = error.lower()
        if "index.lock" in text or ".lock" in text and ("unable to create" in text or "file exists" in text):
            removed = self.repo.clear_stale_locks(dev)
            if removed:
                return "removed stale lock " + ", ".join(removed)
        unfinished = ("not concluded your merge", "merge_head exists", "unmerged files", "resolve your current index", "needs merge", "middle of a merge", "middle of a rebase")
        if any(phrase in text for phrase in unfinished) or ("rebase" in text and "in progress" in text):
            done = self.repo.abort_in_progress(dev)
            if done:
                return "abandoned an unfinished " + "/".join(done)
        if branch and re.search(r"non-fast-forward|rejected|fetch first|behind its remote|tip of your current branch is behind", text):
            if self.repo.rebase_onto_remote(dev, branch):
                return f"rebased {branch} onto origin/{branch}"
        return ""

    # ------------------------------------------------------------------ the agent

    async def ask_agent(self, dev: str, goal: str, error: str, branch: Optional[str], earlier: list[str]) -> str:
        """Hands the failure to the developer's own agent. Returns its account of the fix ('' if it could not finish)."""
        harness = self.harness_for(dev)
        state = await asyncio.to_thread(self.repo.state_report, dev, branch)
        before = ("Earlier attempts to fix this failed with:\n" + "\n".join(f"- {e[:300]}" for e in earlier) + "\n\n") if earlier else ""
        prompt = FIX_PROMPT.format(goal=goal, error=error[:3000], state=state[:4000], earlier=before)
        session = harness.new_session(agent=self.agent_for(dev), title=f"git: {goal}"[:80])
        try:
            result = await asyncio.wait_for(harness.prompt(prompt, session_id=session.id), self.timeout)
        except asyncio.TimeoutError:
            await harness.sessions.interrupt(session.id)
            return ""
        return result.text.strip() if result.outcome == "succeeded" else ""
