"""Agents: built-ins, selection, plan mode, configured agents (modelled on opencode's agent and config/agent tests)."""

import json
import subprocess

import pytest

from harness import agent as A
from harness.ai import types as T
from harness.config import service as cfg
from harness.location import Location
from harness.permission import evaluate
from harness.schema.message import ModelRef
from harness.schema.permission import Rule
from harness.util.global_paths import GlobalPaths


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    proj = home / "proj"
    proj.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    paths = GlobalPaths.default(root=tmp_path / "g", home=home).ensure()
    return paths, Location.of(proj), proj, home


def registry(env, with_config=True):
    paths, loc, proj, home = env
    c = cfg.Config(loc, paths) if with_config else None
    return A.default_registry(c, home, str(paths.config / "plans"))


# ---- built-ins


def test_builtin_agents_and_their_modes(env):
    reg = registry(env, with_config=False)
    assert {a.id for a in reg.list()} == {"build", "plan", "general", "explore", "scout", "compaction", "title", "summary"}
    assert reg.get("general").mode == "subagent" and reg.get("explore").mode == "subagent" and reg.get("build").mode == "primary"
    assert reg.get("title").hidden and reg.get("summary").hidden and reg.get("compaction").hidden
    assert "file search specialist" in reg.get("explore").system and reg.get("build").system is None


def test_default_selection_prefers_configured_then_build_and_skips_subagents_and_hidden(env):
    reg = registry(env, with_config=False)
    assert reg.resolve().id == "build" and reg.select()[0] == "build" and reg.list()[0].id == "build"
    reg.transform(lambda e: e.default("plan"))
    reg.reload()
    assert reg.resolve().id == "plan" and reg.list()[0].id == "plan"
    reg.transform(lambda e: e.default("explore"))  # a subagent cannot be the default; fall back to build
    reg.reload()
    assert reg.resolve().id == "build"
    assert reg.resolve("explore").id == "explore" and reg.resolve("nope") is None  # explicit lookups are not restricted


def test_explore_is_read_only_but_can_run_shell_and_search(env):
    rules = registry(env, with_config=False).get("explore").permissions
    assert evaluate("edit", "a.py", rules).effect == "deny" and evaluate("write", "a.py", rules).effect == "deny"
    assert evaluate("grep", "x", rules).effect == "allow" and evaluate("shell", "ls", rules).effect == "allow" and evaluate("read", "a.py", rules).effect == "allow"
    assert evaluate("read", "secrets.env", rules).effect == "ask" and evaluate("subagent", "general", rules).effect == "deny"


def test_general_cannot_ask_questions_or_spawn_subagents_and_build_can_ask(env):
    reg = registry(env, with_config=False)
    assert evaluate("question", "*", reg.get("general").permissions).effect == "deny" and evaluate("subagent", "x", reg.get("general").permissions).effect == "deny"
    assert evaluate("question", "*", reg.get("build").permissions).effect == "allow" and evaluate("subagent", "x", reg.get("build").permissions).effect == "allow"
    assert evaluate("read", ".env", reg.get("build").permissions).effect == "ask"


def test_the_runner_adapter_exposes_system_steps_and_rules(env):
    reg = registry(env, with_config=False)
    run, rules = reg.resolver()("explore")
    assert run.id == "explore" and "file search" in run.system and rules is reg.get("explore").permissions
    assert reg.resolver()("missing") is None


# ---- plan mode


def test_plan_agent_cannot_edit_except_in_the_plan_directory(env):
    paths = env[0]
    reg = registry(env, with_config=False)
    rules = reg.get("plan").permissions
    plan_dir = (paths.config / "plans").as_posix()
    assert evaluate("edit", "src/a.py", rules).effect == "deny" and evaluate("edit", f"{plan_dir}/idea.md", rules).effect == "allow"


def test_plan_reminder_is_added_while_planning_and_withdrawn_afterwards(env):
    hook = A.plan_context_hook("/plans")
    persisted = []
    msgs = [T.Message.user("earlier"), T.Message.assistant("ok"), T.Message.user("now plan this")]
    hook({"agent": "plan", "messages": msgs, "synthetic": persisted.append})
    assert len(msgs) == 4 and "You are in Plan mode" in msgs[2].content[0].text and msgs[3].content[0].text == "now plan this"  # placed just before the latest prompt
    assert persisted and persisted[0].startswith("<system-reminder>")
    persisted.clear()
    hook({"agent": "plan", "messages": msgs, "synthetic": persisted.append})
    assert len(msgs) == 4 and not persisted  # already present: nothing added twice
    hook({"agent": "build", "messages": msgs, "synthetic": persisted.append})
    assert "NO LONGER in Plan mode" in msgs[3].content[0].text and persisted
    n = len(msgs)
    hook({"agent": "build", "messages": msgs, "synthetic": persisted.append})
    assert len(msgs) == n  # the leave note is added once
    other = [T.Message.user("hi")]
    hook({"agent": "build", "messages": other, "synthetic": persisted.append})
    assert len(other) == 1  # never planned: no leave note


def test_a_blocked_plan_edit_explains_where_plans_go(env):
    from harness.permission import BlockedError
    from harness.tool.info import ToolError

    hook = A.plan_tool_hook("/plans")
    err = ToolError("Permission denied", BlockedError([], "edit", ["a.py"]))
    event = {"agent": "plan", "status": "error", "tool": "edit", "error": err}
    hook(event)
    assert "outside the Plan directory: /plans" in event["error"].message
    event2 = {"agent": "build", "status": "error", "tool": "edit", "error": err}
    hook(event2)
    assert event2["error"] is err


# ---- configuration


def test_configured_agents_override_and_extend(env):
    paths, loc, proj, home = env
    (proj / "harness.json").write_text(json.dumps({
        "default_agent": "reviewer",
        "permission": {"bash": {"*": "ask", "git status *": "allow"}},
        "agent": {
            "reviewer": {"description": "Reviews code", "mode": "primary", "model": "google/gemini-3.1-flash-lite#low", "steps": 12, "color": "#112233",
                         "permission": {"edit": "deny"}, "system": "You review."},
            "build": {"steps": 50},
            "general": {"disabled": True},
        },
    }))
    reg = registry(env)
    r = reg.get("reviewer")
    assert r.description == "Reviews code" and r.steps == 12 and r.system == "You review." and r.model == ModelRef(provider_id="google", id="gemini-3.1-flash-lite", variant="low")
    assert reg.resolve().id == "reviewer" and reg.get("build").steps == 50 and reg.get("general") is None
    # global permissions were added to every agent, and the agent's own rules come after them
    for agent in (reg.get("build"), reg.get("plan"), r):
        assert evaluate("shell", "git status -s", [x for x in agent.permissions if x.action != "*"]).effect in ("allow", "ask")
    assert evaluate("edit", "a.py", r.permissions).effect == "deny" and evaluate("bash", "ls", r.permissions).effect == "ask"
    assert evaluate("bash", "git status", r.permissions).effect == "allow"


def test_markdown_agent_files(env):
    paths, loc, proj, home = env
    d = proj / ".harness" / "agents"
    d.mkdir(parents=True)
    (d / "docs.md").write_text("---\ndescription: Writes docs\nmode: subagent\nsteps: 8\n---\nYou write documentation.\n")
    (proj / ".harness" / "modes").mkdir()
    (proj / ".harness" / "modes" / "ops.md").write_text("---\ndescription: Ops\n---\nYou run operations.\n")
    reg = registry(env)
    docs = reg.get("docs")
    assert docs.mode == "subagent" and docs.steps == 8 and docs.system == "You write documentation." and docs.description == "Writes docs"
    assert reg.get("ops").mode == "primary" and reg.get("ops").system == "You run operations."  # files under modes/ are primary agents


def test_home_directory_expansion_in_path_rules_only(env):
    paths, loc, proj, home = env
    (proj / "harness.json").write_text(json.dumps({"permission": {"external_directory": {"~/shared/**": "allow"}, "shell": {"$HOME/x": "deny"}}}))
    rules = registry(env).get("build").permissions
    assert Rule("external_directory", f"{home.as_posix()}/shared/**", "allow") in rules
    assert Rule("shell", "$HOME/x", "deny") in rules  # shell resources are raw command text and are not rewritten


def test_permission_syntaxes():
    assert A.parse_permissions({"edit": "deny", "bash": {"*": "ask", "ls": "allow"}}) == [Rule("edit", "*", "deny"), Rule("bash", "*", "ask"), Rule("bash", "ls", "allow")]
    assert A.parse_permissions([{"action": "read", "resource": "*.md", "effect": "allow"}, {"action": "x", "effect": "deny"}]) == [Rule("read", "*.md", "allow"), Rule("x", "*", "deny")]
    assert A.parse_permissions(None) == []
