"""Who a developer is and what they may do.

A developer is an agent with a skill lens (the same ones the meeting used), working in their own sandbox clone. Their permissions keep them
there: nothing outside the sandbox, no pushing (the engine pushes branches), no touching git remotes or configuration, no GitHub CLI, no
questions to a human who is not there."""

from __future__ import annotations

from harness.agent import Agent
from harness.schema.permission import Rule, Ruleset
from meetings.prompts import SKILL_LENSES
from team.repo import slugify

DEVELOPER_RULES: Ruleset = [
    Rule("external_directory", "*", "deny"),
    Rule("question", "*", "deny"),
    Rule("shell", "git push*", "deny"),
    Rule("shell", "git remote*", "deny"),
    Rule("shell", "git config*", "deny"),
    Rule("shell", "git checkout main*", "deny"),
    Rule("shell", "git branch -D*", "deny"),
    Rule("shell", "git reset --hard origin*", "deny"),
    Rule("shell", "gh *", "deny"),
    Rule("shell", "sudo *", "deny"),
    Rule("shell", "rm -rf /*", "deny"),
    Rule("shell", "rm -rf ~*", "deny"),
    Rule("shell", "npm publish*", "deny"),
    Rule("shell", "twine upload*", "deny"),
    Rule("read", "*.env", "deny"),
    Rule("read", "*.env.*", "deny"),
    Rule("read", "*.env.example", "allow"),
]

CONSULT_RULES: Ruleset = [Rule("*", "*", "deny")]  # a consultation is conversation only: no tools


def agent_id(dev: str) -> str:
    return slugify(dev)


def developer_agent(dev: str, skill: str) -> Agent:
    lens = SKILL_LENSES.get(skill, {"title": skill.title(), "sees": "", "asks": ""})
    system = f"""You are {dev}, a {lens['title']} developer on a small autonomous engineering team. You work alone in your own clone of the repository; teammates work in theirs, in parallel, on other branches.

What you see first as a {lens['title']} developer: {lens['sees']}
What you ask yourself: {lens['asks']}

How you work:
- Read AGENTS.md and the relevant part of docs/ before you change anything. Follow the directory layout and the contracts in docs/Design.md exactly; do not rename a contract.
- Do the task you are given, and only that task. Keep changes small and in the files the layout names.
- Write or update tests for what you build, run them, and fix failures before you finish.
- Commit your work with a clear message when the task passes. Do not push, and do not touch git remotes: the team engine publishes your branch.
- You cannot see outside your clone. If the design must change (a contract, a component boundary, the data model), do not improvise: call the design_change tool and wait for the team's decision.
- Finish with a short report: what you built, how you verified it, anything unfinished."""
    return Agent(id=agent_id(dev), name=dev, mode="primary", description=f"{lens['title']} developer", system=system, permissions=[Rule("question", "*", "deny")])


def consult_agent(dev: str, skill: str) -> Agent:
    lens = SKILL_LENSES.get(skill, {"title": skill.title(), "sees": "", "asks": ""})
    system = (
        f"You are {dev}, a {lens['title']} developer. A teammate is consulting you. Answer only from the material in the message and from your "
        f"{lens['title']} expertise; be specific and brief. You have no tools in this conversation."
    )
    return Agent(id=f"{agent_id(dev)}-consult", name=f"{dev} (consulting)", mode="primary", hidden=True, system=system, permissions=list(CONSULT_RULES))
