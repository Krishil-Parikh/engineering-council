"""Slash commands: template evaluation, loading from markdown and config, built-ins, and running them through a Harness."""

import asyncio
import sys

import pytest

from harness import command as C
from harness.schema import message as M
from tests.harness.test_app import make
from tests.harness.test_runner import ScriptedLLM, text_reply

PY = sys.executable.replace("\\", "/")


def evaluate(template, text, tmp_path, run=None):
    async def fake(source, cwd, shell):
        return f"<{source}>"

    return asyncio.run(C.evaluate_template(template, text, tmp_path, "sh", run or fake))


def test_arguments_are_split_with_quotes_respected():
    assert C.parse_arguments('one "two words" \'three four\' five') == ["one", "two words", "three four", "five"]
    assert C.parse_arguments("") == [] and C.parse_arguments("[Image 1] go") == ["[Image 1]", "go"]


def test_placeholders_fill_from_the_arguments_and_the_last_takes_the_rest(tmp_path):
    assert evaluate("Fix $1 in $2", "bug app.py", tmp_path) == "Fix bug in app.py"
    assert evaluate("Do $1 then $2", "a b c d", tmp_path) == "Do a then b c d"  # the last placeholder takes everything left
    assert evaluate("Fix $1 and $3", "only", tmp_path) == "Fix only and"  # a missing argument is empty
    assert evaluate("Review: $ARGUMENTS", 'the "big change"', tmp_path) == 'Review: the "big change"'


def test_text_with_no_placeholder_gets_the_input_appended(tmp_path):
    assert evaluate("Summarize the repo.", "focus on tests", tmp_path) == "Summarize the repo.\n\nfocus on tests"
    assert evaluate("Summarize the repo.", "", tmp_path) == "Summarize the repo."
    assert C.append_input("Template $ARGUMENTS end", " x ") == "Template x end" and C.append_input("T", "x") == "T\n\nx" and C.append_input("T", "") == "T"


def test_shell_output_is_interpolated_after_the_arguments(tmp_path):
    assert evaluate("Branch: !`git branch` and !`echo $1`", "main", tmp_path) == "Branch: <git branch> and <echo main>"


def test_a_real_shell_command_runs_in_the_working_directory(tmp_path):
    (tmp_path / "marker.txt").write_text("hello")
    out = asyncio.run(C.evaluate_template("Files: !`ls`", "", tmp_path))
    assert "marker.txt" in out


def test_a_failing_shell_interpolation_names_the_command(tmp_path):
    async def boom(source, cwd, shell):
        raise OSError("no such shell")

    with pytest.raises(C.CommandError, match='Shell interpolation failed for "false": no such shell'):
        evaluate("x !`false`", "", tmp_path, boom)


def test_commands_load_from_markdown_folders_with_nested_names(tmp_path):
    root = tmp_path / ".harness"
    (root / "commands" / "review").mkdir(parents=True)
    (root / "commands" / "greet.md").write_text("---\ndescription: say hello\nagent: general\n---\nHello $1!\n")
    (root / "commands" / "review" / "security.md").write_text("Audit the code for security problems.\n")
    (root / "command").mkdir()
    (root / "command" / "old.md").write_text("---\nsubtask: true\n---\nOld style folder.\n")
    (root / "commands" / "notes.txt").write_text("ignored")
    loaded = C.load_directory(root)
    assert sorted(loaded) == ["greet", "old", "review/security"]
    assert loaded["greet"] == {"description": "say hello", "agent": "general", "template": "Hello $1!"}
    assert loaded["old"]["subtask"] is True and loaded["review/security"]["template"].startswith("Audit")


def test_a_later_definition_replaces_an_earlier_one():
    from harness.config import service as cfg

    entries = [
        cfg.Document({"commands": {"x": {"template": "from the global file", "description": "g"}, "y": {"template": "only here"}}}),
        cfg.Document({"commands": {"x": {"template": "from the project file"}, "bad": "not a command", "worse": {"description": "no template"}}}),
    ]
    merged = C.load_entries(entries)
    assert merged["x"]["template"] == "from the project file" and merged["y"]["template"] == "only here" and set(merged) == {"x", "y"}


def test_model_references_in_two_spellings():
    assert C.model_ref({"providerID": "google", "model": "gemini-x", "variant": "high"}) == M.ModelRef(provider_id="google", id="gemini-x", variant="high")
    assert C.model_ref("google/gemini-x#low") == M.ModelRef(provider_id="google", id="gemini-x", variant="low")
    assert C.model_ref("nonsense") is None and C.model_ref(None) is None


# ------------------------------------------------------------------ through a Harness

def run(tmp_path, llm, setup=None, **kw):
    """A Harness whose project already holds whatever `setup(project_dir)` wrote, the way a real project does when the harness starts."""
    proj = tmp_path / "home" / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    if setup:
        setup(proj)
    return make(tmp_path, llm, **kw)


def request_text(request):
    return "\n".join(p.text for m in request.messages for p in m.content if hasattr(p, "text"))


def test_the_builtin_commands_are_listed():
    h, _ = make_plain()
    assert {"init", "review"} <= {c.name for c in h.commands.list()}
    assert h.commands.get("init").description == "guided AGENTS.md setup" and h.commands.get("nope") is None


def make_plain():
    import tempfile
    from pathlib import Path

    return make(Path(tempfile.mkdtemp()), ScriptedLLM())


def test_init_sends_the_guided_prompt_with_the_users_focus(tmp_path):
    llm = ScriptedLLM(text_reply("AGENTS.md drafted."))
    h, proj = make(tmp_path, llm)

    async def main():
        result = await h.command("init", "focus on how tests run")
        assert result.outcome == "succeeded" and result.text == "AGENTS.md drafted."
        text = request_text(llm.requests[0])
        assert "Create or update `AGENTS.md` for this repository." in text and "focus on how tests run" in text
        assert str(proj) in text and "${path}" not in text and "OpenCode" not in text
        await h.close()

    asyncio.run(main())


def test_review_appends_its_argument(tmp_path):
    llm = ScriptedLLM(text_reply("Looks fine."))
    h, _ = make(tmp_path, llm)

    async def main():
        await h.command("review", "a1b2c3d")
        assert "You are a code reviewer." in request_text(llm.requests[0]) and "a1b2c3d" in request_text(llm.requests[0])
        await h.close()

    asyncio.run(main())


def test_a_markdown_command_fills_its_arguments_and_switches_the_agent(tmp_path):
    def setup(proj):
        folder = proj / ".harness" / "commands"
        folder.mkdir(parents=True)
        (folder / "greet.md").write_text("---\ndescription: say hello\nagent: plan\n---\nGreet $1 warmly, in $2.\n")

    llm = ScriptedLLM(text_reply("Hola, Ana!"))
    h, _ = run(tmp_path, llm, setup)

    async def main():
        result = await h.command("greet", "Ana Spanish")
        assert result.text == "Hola, Ana!"
        assert "Greet Ana warmly, in Spanish." in request_text(llm.requests[0])
        assert h.sessions.get(result.session_id).agent == "plan"  # a primary agent: the command switches the session to it
        await h.close()

    asyncio.run(main())


def test_a_command_can_run_a_shell_command_for_its_text(tmp_path):
    def setup(proj):
        folder = proj / ".harness" / "commands"
        folder.mkdir(parents=True)
        (folder / "version.md").write_text(f"Python says: !`{PY} -c \"print('v-ok')\"`\n")

    llm = ScriptedLLM(text_reply("noted"))
    h, _ = run(tmp_path, llm, setup)

    async def main():
        await h.command("version")
        assert "Python says: v-ok" in request_text(llm.requests[0])
        await h.close()

    asyncio.run(main())


def test_unknown_and_failing_commands_raise_clear_errors(tmp_path):
    def setup(proj):
        folder = proj / ".harness" / "commands"
        folder.mkdir(parents=True)
        (folder / "broken.md").write_text("---\nagent: no-such-agent\nsubagent: true\n---\nDo it.\n")

    h, _ = run(tmp_path, ScriptedLLM(), setup)

    async def main():
        with pytest.raises(C.NotFoundError, match="Command not found: nope"):
            await h.command("nope")
        with pytest.raises(C.ExecutionError, match="Unknown agent"):
            await h.command("broken")
        await h.close()

    asyncio.run(main())


def test_a_subagent_command_runs_in_a_child_session_in_the_background(tmp_path):
    def setup(proj):
        folder = proj / ".harness" / "commands"
        folder.mkdir(parents=True)
        (folder / "scout.md").write_text("---\ndescription: look around\nagent: explore\nsubagent: true\n---\nList what is in $1.\n")

    llm = ScriptedLLM(text_reply("The folder has two files."))
    h, _ = run(tmp_path, llm, setup)

    async def main():
        result = await h.command("scout", "src")
        assert result.outcome == "succeeded" and result.steps == 0  # the parent had nothing new to answer
        child = h.store.children(result.session_id)[0]
        assert child.agent == "explore" and child.title == "look around"
        first = [m for _, m in h.store.messages(child.id) if isinstance(m, M.User)][0]
        assert first.text == "You are a subagent spawned by another session.\nList what is in src."
        for _ in range(100):
            await asyncio.sleep(0.05)
            notes = [m for _, m in h.store.messages(result.session_id) if isinstance(m, M.Synthetic)]
            if notes:
                break
        assert notes and 'state="completed"' in notes[0].text and "The folder has two files." in notes[0].text
        await h.close()

    asyncio.run(main())


def test_tool_arguments_are_repaired_before_validation(tmp_path):
    from tests.harness.test_runner import tool_reply

    llm = ScriptedLLM(tool_reply(("read", {"path": "a.txt", "offset": "1", "limit": "2"})), text_reply("read it"))
    h, proj = run(tmp_path, llm, lambda p: (p / "a.txt").write_text("one\ntwo\nthree\n"))

    async def main():
        result = await h.prompt("read a.txt")
        assert result.outcome == "succeeded"
        tool_result = " ".join(str(p.result.value) for m in llm.requests[1].messages for p in m.content if hasattr(p, "result"))
        assert "1: one" in tool_result and "2: two" in tool_result and "Invalid arguments" not in tool_result
        await h.close()

    asyncio.run(main())


def test_a_command_added_while_running_appears_after_a_reload(tmp_path):
    h, proj = run(tmp_path, ScriptedLLM())
    assert h.commands.get("late") is None
    folder = proj / ".harness" / "commands"
    folder.mkdir(parents=True)
    (folder / "late.md").write_text("---\ndescription: added later\n---\nDo it later.\n")
    assert h.commands.get("late") is None  # the set is built once...
    h.commands.reload()
    assert h.commands.get("late").description == "added later"  # ...until it is reloaded
