"""Agent definitions: a name, a prompt, a mode (primary or subagent) and a permission ruleset."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from harness.legacy.permission import Rule, Ruleset

_PROMPTS = Path(__file__).parent / "prompts"


def prompt_text(name: str) -> str:
    return (_PROMPTS / name).read_text(encoding="utf-8").strip()


@dataclass
class Agent:
    id: str
    name: str
    description: str = ""
    mode: str = "primary"  # primary | subagent
    system: str = ""  # appended after the base prompt
    permissions: Ruleset = field(default_factory=list)
    steps: int = 80  # model calls allowed per user message before the agent must wrap up
    temperature: float = 0.2
    hidden: bool = False
    tools: list[str] | None = None  # None = all tools the permissions leave visible


def _r(action: str, resource: str, effect: str) -> Rule:
    return Rule(action, resource, effect)  # type: ignore[arg-type]


# Defaults every agent starts from. The LAST matching rule wins, so specifics come after the catch-all.
BASE_RULES: Ruleset = [
    _r("*", "*", "allow"),
    _r("doom_loop", "*", "ask"),
    _r("external_directory", "*", "ask"),
    _r("read", "*.env", "ask"),
    _r("read", "*.env.*", "ask"),
    _r("read", "*.env.example", "allow"),
    # things that are hard to undo or leave the machine need a person
    _r("shell", "sudo *", "ask"),
    _r("shell", "rm -rf *", "ask"),
    _r("shell", "rm -fr *", "ask"),
    _r("shell", "git push *", "ask"),
    _r("shell", "git reset --hard *", "ask"),
    _r("shell", "git clean *", "ask"),
    _r("shell", "git checkout -- *", "ask"),
    _r("shell", "git config *", "ask"),  # the agent must not rewrite the user's git identity or settings
    _r("shell", "git config --get *", "allow"),
    _r("shell", "git config --list*", "allow"),
    _r("shell", "git config -l*", "allow"),
    _r("shell", "git branch -D *", "ask"),
    _r("shell", "gh pr merge *", "ask"),
    _r("shell", "gh repo delete *", "deny"),
    _r("shell", "gh release create *", "ask"),
    _r("shell", "npm publish *", "ask"),
    _r("shell", "twine upload *", "ask"),
]

READ_ONLY_SHELL = [
    "ls *", "pwd", "cat *", "head *", "tail *", "wc *", "grep *", "find *", "tree *", "echo *", "which *", "file *", "stat *", "diff *",
    "git status *", "git diff *", "git log *", "git show *", "git branch", "git branch -a", "git branch -r", "git rev-parse *",
    "git remote -v", "git ls-files *", "git blame *", "gh pr view *", "gh pr list *", "gh pr diff *", "gh issue view *", "gh issue list *",
    "gh repo view *", "gh run list *", "gh run view *",
]


def build_agent() -> Agent:
    return Agent("build", "Build", "The default agent. Reads, edits and runs commands according to the configured permissions.", "primary",
                 permissions=[_r("question", "*", "allow")], steps=100)


def plan_agent() -> Agent:
    return Agent(
        "plan", "Plan", "Read-only planning agent. Investigates and proposes a plan; never changes files.", "primary",
        system=prompt_text("plan.txt"),
        permissions=[_r("edit", "*", "deny"), _r("shell", "*", "deny"), *[_r("shell", c, "allow") for c in READ_ONLY_SHELL], _r("question", "*", "allow")],
        steps=60,
    )


def explore_agent() -> Agent:
    return Agent(
        "explore",
        "Explore",
        'Fast read-only agent for exploring a codebase: find files by pattern, search code for keywords, answer questions about how it works. '
        'Say how thorough to be: "quick", "medium" or "very thorough".',
        "subagent",
        system=prompt_text("explore.txt"),
        permissions=[
            _r("*", "*", "deny"), _r("read", "*", "allow"), _r("read", "*.env", "ask"), _r("read", "*.env.*", "ask"), _r("read", "*.env.example", "allow"),
            _r("glob", "*", "allow"), _r("grep", "*", "allow"), _r("webfetch", "*", "allow"),
            *[_r("shell", c, "allow") for c in READ_ONLY_SHELL], _r("external_directory", "*", "allow"), _r("skill", "*", "allow"),
        ],
        steps=40,
    )


def general_agent() -> Agent:
    return Agent(
        "general", "General", "General-purpose agent for researching complex questions and executing multi-step tasks. Use it to run units of work in parallel.",
        "subagent", permissions=[_r("question", "*", "deny"), _r("subagent", "*", "deny")], steps=60,
    )


def default_agents() -> dict[str, Agent]:
    return {a.id: a for a in (build_agent(), plan_agent(), explore_agent(), general_agent())}


def developer_agent(agent_id: str, skill_title: str, sees: str, asks: str, extra: str = "") -> Agent:
    """A council developer who now writes code: the generic build agent wearing the skill lens they picked in the meeting."""
    system = (
        f"You are {agent_id}, a {skill_title} developer on an engineering pod. You helped design this project in a meeting and now you build it.\n"
        f"Through your skill you care most about: {sees}\nQuestions you always ask: {asks}\n"
        "Do the work yourself with the tools; do not describe what you would do. Stay inside the files and scope of the task you were given, "
        "follow the specification and the agreed directory structure exactly, and say plainly in your final answer what you changed, what you "
        "verified (and how) and anything you could not finish."
    )
    return Agent(agent_id.lower(), agent_id, f"{skill_title} developer", "primary", system=system + ("\n" + extra if extra else ""),
                 permissions=[_r("question", "*", "deny")], steps=100)
