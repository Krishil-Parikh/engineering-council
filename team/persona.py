"""Who a developer is and what they may do.

A developer is an agent with a skill lens (the same ones the meeting used), working in their own sandbox clone. Their permissions keep them
there: nothing outside the sandbox, pushing only their own feature and fix branches, no touching git remotes, configuration or hooks, no GitHub CLI, no
questions to a human who is not there."""

from __future__ import annotations

from harness.agent import Agent
from harness.schema.permission import Rule, Ruleset
from meetings.prompts import SKILL_LENSES
from team.repo import slugify

def _push_allows(*prefixes: str) -> Ruleset:
    out: Ruleset = []
    for prefix in prefixes:
        for form in (f"git push origin {prefix}/*", f"git push -u origin {prefix}/*", f"git push --set-upstream origin {prefix}/*"):
            out.append(Rule("shell", form, "allow"))
    return out


# Last matching rule wins, so the order is: broad refusals, then the few pushes that are allowed, then the hard refusals that nothing overrides.
_BASE: Ruleset = [
    Rule("external_directory", "*", "deny"),
    Rule("question", "*", "deny"),
    Rule("shell", "git push*", "deny"),
    Rule("shell", "git remote*", "deny"),
    Rule("shell", "git config*", "deny"),
]
_READ_ONLY: Ruleset = [Rule("shell", "git remote -v", "allow"), Rule("shell", "git remote get-url*", "allow"), Rule("shell", "git config --get*", "allow"), Rule("shell", "git config --list", "allow")]
def _hard(protected: tuple[str, ...]) -> Ruleset:
    """Refusals that nothing overrides: the protected branches (whatever the repository's trunk is called), forcing, and going around the guards."""
    rules: Ruleset = []
    for name in protected:
        rules += [Rule("shell", f"git push*{form}", "deny") for form in (f" {name}", f":{name}", f"/{name}")]
        rules += [Rule("shell", f"git push*{form}*", "deny") for form in (f" {name} ", f":{name} ", f"refs/heads/{name}")]
        rules += [Rule("shell", f"git checkout {name}*", "deny"), Rule("shell", f"git switch {name}*", "deny")]
    rules += [Rule("shell", f"git push*{form}*", "deny") for form in ("--force", " -f", "--no-verify", "--delete", " -d ", "--mirror", "--all", "--tags", " +")]
    return [*rules, *_HARD_FIXED]


_HARD_FIXED: Ruleset = [
    Rule("shell", "git branch -D*", "deny"),
    Rule("shell", "git reset --hard origin*", "deny"),
    Rule("shell", "*core.hooksPath*", "deny"),
    Rule("shell", "*.git/hooks*", "deny"),
    Rule("shell", "*.git/config*", "deny"),
    Rule("edit", "*.git/*", "deny"),
    Rule("edit", ".git/*", "deny"),
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

DEFAULT_PROTECTED = ("main", "master")


def rules_for(dev: str, integrator: bool = False, protected: tuple[str, ...] = DEFAULT_PROTECTED) -> Ruleset:
    """A developer publishes only their own feature and fix branches (if a push fails, that is for the agent to understand and fix). The
    integrator also publishes the integration and final branches, which no developer may touch. Nobody touches a protected branch."""
    prefixes = ("feature", "fix", "integration", "final") if integrator else ("feature", "fix")
    return [*_BASE, *_READ_ONLY, *_push_allows(*prefixes), *_hard(tuple(dict.fromkeys((*DEFAULT_PROTECTED, *protected))))]


DEVELOPER_RULES: Ruleset = rules_for("developer")
INTEGRATOR_RULES: Ruleset = rules_for("integrator", integrator=True)

CONSULT_RULES: Ruleset = [Rule("*", "*", "deny")]  # a consultation is conversation only: no tools


def agent_id(dev: str) -> str:
    return slugify(dev)


def developer_agent(dev: str, skill: str, experience: str = "") -> Agent:
    lens = SKILL_LENSES.get(skill, {"title": skill.title(), "sees": "", "asks": ""})
    system = f"""You are {dev}, a {lens['title']} developer on a small autonomous engineering team. You work alone in your own clone of the repository; teammates work in theirs, in parallel, on other branches.

What you see first as a {lens['title']} developer: {lens['sees']}
What you ask yourself: {lens['asks']}

How you work:
- Read AGENTS.md and the relevant part of docs/ before you change anything. Follow the directory layout and the contracts in docs/Design.md exactly; do not rename a contract.
- Do the task you are given, and only that task. Keep changes small and in the files the layout names.
- Write or update tests for what you build, run them, and fix failures before you finish.
- Commit small and often, the way a person does: after each module, function or group of tests that works, with a message like `feat(timer): add registry` or `test(timer): cover limits`. Push your branch after each group of commits with `git push origin <your branch>`; when the task passes, commit and push the rest. If git refuses (the remote moved, a merge or rebase is half done, a lock file, anything), read the error, work out the cause and fix it with git commands, then push again. Never force-push, never push main, and do not touch remotes, hooks or git configuration.
- The team keeps a project memory that everyone writes to, and you keep your own. Before new work, `recall` what the team already knows about it (modules, decisions, traps); when you create something a teammate would need to know about (an API, a convention, a trap), `remember` it with scope 'project'; keep what only matters to you with scope 'me'.
- You cannot see outside your clone. If the design must change (a contract, a component boundary, the data model), do not improvise: call the design_change tool and wait for the team's decision.
- Finish with a short report: what you built, how you verified it, anything unfinished.""" + (f"\n\n{experience}" if experience else "")
    return Agent(id=agent_id(dev), name=dev, mode="primary", description=f"{lens['title']} developer", system=system, permissions=[Rule("question", "*", "deny")])


def consult_agent(dev: str, skill: str) -> Agent:
    lens = SKILL_LENSES.get(skill, {"title": skill.title(), "sees": "", "asks": ""})
    system = (
        f"You are {dev}, a {lens['title']} developer. A teammate is consulting you. Answer only from the material in the message and from your "
        f"{lens['title']} expertise; be specific and brief. You have no tools in this conversation."
    )
    return Agent(id=f"{agent_id(dev)}-consult", name=f"{dev} (consulting)", mode="primary", hidden=True, system=system, permissions=list(CONSULT_RULES))
