"""Config discovery, skills, instruction files and built-ins (modelled on opencode's config, skill and instruction-discovery tests)."""

import json
import subprocess
from datetime import date

import pytest

from harness.config import markdown
from harness.config import service as cfg
from harness.config.variable import parse_jsonc, substitute
from harness.instruction_discovery import InstructionDiscovery, render_update
from harness.instructions import builtins
from harness.instructions import index as I
from harness.location import Location
from harness.permission import Rule
from harness.skill import SkillCatalog, available, prepare
from harness.skill_file import Parsed, Skipped, parse
from harness.skill_instructions import load as skill_instructions
from harness.skill_loader import SkillLoader
from harness.util.global_paths import GlobalPaths


@pytest.fixture
def env(tmp_path):
    """A project inside a fake home, with its own global config dir."""
    home = tmp_path / "home"
    proj = home / "work" / "proj"
    (proj / "src" / "deep").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    paths = GlobalPaths.default(root=tmp_path / "global", home=home).ensure()
    loc = Location.of(proj / "src" / "deep")
    return paths, loc, proj


def config_for(env, **kw):
    paths, loc, _ = env
    return cfg.Config(loc, paths)


def rules_texts(ins):
    return I.render_initial(ins, {s.key: s.read() for s in ins})


# ---- JSONC, variables, markdown


def test_jsonc_comments_and_trailing_commas():
    assert parse_jsonc('{ // c\n "a": 1, /* x */ "b": "http://x//y", }') == {"a": 1, "b": "http://x//y"}
    with pytest.raises(ValueError):
        parse_jsonc("{ nope")


def test_variable_substitution(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_KEY", "abc")
    (tmp_path / "secret.txt").write_text("from-file\n")
    out = substitute('{"k": "{env:MY_KEY}", "f": "{file:secret.txt}", "missing": "{env:NOPE_X}"}', directory=tmp_path)
    assert json.loads(out) == {"k": "abc", "f": "from-file", "missing": ""}
    monkeypatch.setenv("WIN", 'C:\\Users\\x')
    assert json.loads(substitute('{"p": "{env:WIN}"}', directory=tmp_path)) == {"p": "C:\\Users\\x"}  # escaped only because raw JSON breaks


def test_frontmatter_including_unquoted_colons():
    md = markdown.parse("---\nname: x\ndescription: Use when: a thing happens\n---\nbody\n")
    assert md.data == {"name": "x", "description": "Use when: a thing happens"} and md.content == "body\n"
    assert markdown.parse("no frontmatter").data == {}
    assert markdown.parse_option("---\n- a\n- b\n---\nx") is None


# ---- config entries


def test_config_entries_are_ordered_lowest_to_highest_priority(env):
    paths, loc, proj = env
    (paths.config / "harness.json").write_text('{"model": "global/model", "instructions": ["a.md"]}')
    (proj / "harness.json").write_text('// project\n{"model": "project/model",}')
    (proj / ".harness").mkdir()
    (proj / ".harness" / "harness.jsonc").write_text('{"default_agent": "plan"}')
    entries = config_for(env).entries()
    docs = [e for e in entries if isinstance(e, cfg.Document)]
    assert cfg.latest(entries, "model") == "project/model"  # the project file outranks the global one
    assert cfg.latest(entries, "default_agent") == "plan" and cfg.latest(entries, "instructions") == ["a.md"]
    assert [type(e).__name__ for e in entries].count("Directory") == 2  # global dir and project .harness dir
    assert docs[0].path.parent == paths.config


def test_malformed_config_is_ignored_not_fatal(env):
    paths, _, proj = env
    (proj / "harness.json").write_text("{ broken")
    assert [e for e in config_for(env).entries() if isinstance(e, cfg.Document)] == []


# ---- skills


def write_skill(directory, name, description="Does a thing", body="Do the thing.", extra=""):
    d = directory / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n{extra}---\n{body}\n")
    return d


def test_skill_file_parsing(tmp_path):
    p = parse(tmp_path, tmp_path / "git" / "SKILL.md", "---\nname: Git Helper\ndescription: Commits\n---\nSteps\n")
    assert isinstance(p, Parsed) and p.skill.id == "git" and p.skill.name == "Git Helper" and p.skill.content == "Steps\n"
    loose = parse(tmp_path, tmp_path / "notes.md", "---\ndescription: x\n---\nhi")
    assert loose.skill.id == "notes" and loose.skill.name == "notes"  # a loose .md uses its file name
    hidden = parse(tmp_path, tmp_path / "a" / "SKILL.md", "---\ndescription: x\ndisable-model-invocation: true\n---\n")
    assert hidden.skill.autoinvoke is False
    native = parse(tmp_path, tmp_path / "a" / "SKILL.md", "---\ndescription: x\nmetadata:\n  opencode/autoinvoke: false\n---\n")
    assert native.skill.autoinvoke is False
    assert isinstance(parse(tmp_path, tmp_path / "a" / "SKILL.md", "---\n- bad\n---\n"), Skipped)


def test_skills_load_from_every_source_and_native_dirs_win(env):
    paths, loc, proj = env
    write_skill(paths.home / ".claude" / "skills", "shared", "from claude home")
    write_skill(proj / ".agents" / "skills", "agents-only", "from agents")
    write_skill(proj / ".harness" / "skills", "shared", "from project harness")
    write_skill(paths.config / "skills", "global-one", "from global config")
    c = config_for(env)
    skills = {s.id: s for s in SkillLoader(c, paths, loc.directory).load()}
    assert set(skills) == {"shared", "agents-only", "global-one"}
    assert skills["shared"].description == "from project harness"  # native project directory beats the Claude-compat one


def test_skills_listed_in_config_documents(env, tmp_path):
    paths, loc, proj = env
    extra = tmp_path / "extra"
    write_skill(extra, "extra-skill")
    (proj / "harness.json").write_text(json.dumps({"skills": [str(extra)]}))
    assert "extra-skill" in {s.id for s in SkillLoader(config_for(env), paths, loc.directory).load()}


def test_skill_tool_output_lists_sibling_files(env):
    paths, loc, proj = env
    d = write_skill(proj / ".harness" / "skills", "withfiles")
    (d / "scripts").mkdir()
    (d / "scripts" / "run.sh").write_text("echo")
    skill = SkillLoader(config_for(env), paths, loc.directory).load()[0]
    out = prepare(skill)["output"]
    assert out.startswith('<skill_content name="withfiles">') and "# Skill: withfiles" in out and "run.sh" in out and "SKILL.md</file>" not in out


def test_skill_availability_follows_permissions_and_autoinvoke(env):
    paths, loc, proj = env
    write_skill(proj / ".harness" / "skills", "allowed")
    write_skill(proj / ".harness" / "skills", "denied")
    write_skill(proj / ".harness" / "skills", "manual", extra="disable-model-invocation: true\n")
    cat = SkillCatalog()
    cat.add_provider(SkillLoader(config_for(env), paths, loc.directory).load)
    rules = [Rule("skill", "*", "allow"), Rule("skill", "denied", "deny")]
    assert {s.id for s in available(cat.list(), rules)} == {"allowed", "manual"}
    text = I.render_initial(skill_instructions(cat, rules), {"core/skill-guidance": [{"id": "allowed", "name": "allowed", "description": "Does a thing"}]})
    assert "<id>allowed</id>" in text and "Use the skill tool to load a skill" in text
    src = skill_instructions(cat, rules)[0].read()
    assert [s["id"] for s in src] == ["allowed"]  # manual-only and denied skills are not advertised


def test_skill_guidance_updates_are_small_deltas():
    from harness.skill_instructions import update

    a, b = {"id": "a", "name": "a", "description": "x"}, {"id": "b", "name": "b", "description": "y"}
    added = update([a], [a, b])
    assert added.startswith("New skills are available in addition") and "<id>b</id>" in added and "<id>a</id>" not in added
    assert "no longer available and must not be used: a." in update([a, b], [b])
    assert update([a], [{**a, "description": "changed"}]).startswith("The available skills have changed")


# ---- instruction files


def test_instruction_files_global_then_nearest_to_farthest(env):
    paths, loc, proj = env
    (paths.config / "AGENTS.md").write_text("GLOBAL")
    (proj / "AGENTS.md").write_text("ROOT")
    (proj / "src" / "AGENTS.md").write_text("SRC")
    (proj / "src" / "deep" / "CLAUDE.md").write_text("DEEP-CLAUDE")
    files = InstructionDiscovery(loc, paths, config_for(env)).list()
    assert [f.content for f in files] == ["GLOBAL", "DEEP-CLAUDE", "SRC", "ROOT"]  # CLAUDE.md is used when a directory has no AGENTS.md


def test_agents_md_wins_over_claude_md_in_the_same_directory(env):
    paths, loc, proj = env
    (proj / "src" / "deep" / "AGENTS.md").write_text("A")
    (proj / "src" / "deep" / "CLAUDE.md").write_text("C")
    assert [f.content for f in InstructionDiscovery(loc, paths, config_for(env)).list()] == ["A"]


def test_project_and_global_discovery_can_be_turned_off(env):
    paths, loc, proj = env
    (paths.config / "AGENTS.md").write_text("GLOBAL")
    (proj / "AGENTS.md").write_text("ROOT")
    assert [f.content for f in InstructionDiscovery(loc, paths, config_for(env), project=False).list()] == ["GLOBAL"]
    assert [f.content for f in InstructionDiscovery(loc, paths, config_for(env), global_=False).list()] == ["ROOT"]


def test_nothing_found_is_a_removal_not_an_empty_list(env):
    paths, loc, _ = env
    src = InstructionDiscovery(loc, paths, config_for(env)).load()
    assert src[0].read() is I.REMOVED


def test_configured_instruction_globs_are_combined_with_agents_md(env):
    paths, loc, proj = env
    (proj / "AGENTS.md").write_text("ROOT")
    (proj / "CONTRIBUTING.md").write_text("CONTRIB")
    (proj / "docs").mkdir()
    (proj / "docs" / "a.md").write_text("DOC-A")
    (proj / "harness.json").write_text(json.dumps({"instructions": ["CONTRIBUTING.md", "docs/*.md"]}))
    contents = [f.content for f in InstructionDiscovery(loc, paths, config_for(env)).list()]
    assert contents == ["ROOT", "CONTRIB", "DOC-A"]


def test_changed_instruction_file_renders_a_diff_when_shorter(env):
    big = "\n".join(f"rule {i}: keep things consistent across the codebase" for i in range(40))
    before = [{"path": "/p/AGENTS.md", "content": big}]
    after = [{"path": "/p/AGENTS.md", "content": big.replace("rule 3:", "rule three:")}]
    text = render_update(before, after)
    assert text.startswith("The instructions from /p/AGENTS.md changed. Here's the diff:") and "```diff" in text and "-rule 3:" in text and "+rule three:" in text
    tiny = render_update([{"path": "/x", "content": "a"}], [{"path": "/x", "content": "b"}])
    assert tiny.startswith("The instructions changed:\nInstructions from: /x")  # the full text is shorter than a diff
    assert render_update(before, []).startswith("The instructions from /p/AGENTS.md no longer apply.")
    assert render_update([], after).startswith("New instructions apply from:\nInstructions from: /p/AGENTS.md")


def test_unreadable_project_file_makes_the_source_unavailable(env, monkeypatch):
    paths, loc, proj = env
    (proj / "AGENTS.md").write_text("ROOT")
    d = InstructionDiscovery(loc, paths, config_for(env))
    monkeypatch.setattr(d, "_read", lambda p: None)
    assert d.load()[0].read() is I.UNAVAILABLE  # a discovered file vanished before it could be read: keep what the model has


def test_built_in_date_and_environment(env):
    paths, loc, _ = env
    ins = builtins.load(loc, paths, today=lambda: date(2026, 7, 9))
    text = I.render_initial(ins, {s.key: s.read() for s in ins})
    assert "Today's date: Thu Jul 09 2026" in text and "Working directory:" in text and "Is directory a git repo: yes" in text
    changed = ins[0].changed("Thu Jul 09 2026", "Fri Jul 10 2026")
    assert changed == "Today's date is now: Fri Jul 10 2026"


# ---- assembling a request's context


def test_context_assembles_instructions_in_cache_friendly_order_and_tracks_changes(env, store):
    from harness.permission import merge
    from harness.session import instruction_state as S
    from harness.session.compaction import AgentInfo
    from harness.session.context import SessionContext
    from harness.skill import SkillCatalog
    from tests.harness.conftest import MODEL

    paths, loc, proj = env
    (proj / "AGENTS.md").write_text("Always run make check.")
    write_skill(proj / ".harness" / "skills", "review", "Review a diff")
    c = config_for(env)
    skills = SkillCatalog()
    skills.add_provider(SkillLoader(c, paths, loc.directory).load)
    ctx = SessionContext(
        store, loc, paths, InstructionDiscovery(loc, paths, c), skills,
        resolve_agent=lambda name: (AgentInfo(name or "build"), [Rule("*", "*", "allow")]), resolve_model=lambda s: MODEL,
    )
    session = store.create(str(loc.directory), agent="build")
    selection, loaded = ctx.context(session.id)
    text = loaded.initial
    # skill guidance, then project instructions, then the date and environment
    assert text.index("<available_skills>") < text.index("Instructions from:") < text.index("Today's date:")
    assert "Always run make check." in text and "<id>review</id>" in text

    # nothing changed: no new message
    assert ctx.prepare(ctx.select(session.id)) is None
    # a rule file changes: the baseline is untouched and the model gets a frozen update message
    (proj / "AGENTS.md").write_text("Always run make check.\nNever edit generated/.")
    selection, loaded2 = ctx.context(session.id)
    assert loaded2.initial == text
    updates = [m for m in loaded2.messages if m.type == "system"]
    assert len(updates) == 1 and "Never edit generated/." in updates[0].text and "AGENTS.md" in updates[0].text
