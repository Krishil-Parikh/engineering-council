"""The terminal front end: one-shot tasks, the interactive loop and its slash commands, approvals, and the admin commands."""

import io
import json
import os
import subprocess

from harness.cli import main
from tests.harness.test_runner import ScriptedLLM, text_reply, tool_reply

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def run(tmp_path, argv, llm, lines=(), ask_before_editing=False):
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    if ask_before_editing:
        (proj / "harness.json").write_text(json.dumps({"permission": {"edit": "ask"}}), encoding="utf-8")
    out = io.StringIO()
    answers = iter(lines)
    asked = []

    def ask(prompt):
        asked.append(prompt)
        try:
            return next(answers)
        except StopIteration:
            raise EOFError

    code = main(["-d", str(proj), "--no-snapshots", "--no-title", *argv], llm=llm, ask=ask, out=out)
    return code, out.getvalue(), asked, proj


def test_a_task_on_the_command_line_runs_and_exits(tmp_path):
    llm = ScriptedLLM(tool_reply(("write", {"path": "hello.txt", "content": "hi\n"})), text_reply("Created hello.txt."))
    code, out, asked, proj = run(tmp_path, ["-y", "make", "a", "greeting"], llm)
    assert code == 0 and (proj / "hello.txt").exists() and "Created hello.txt." in out and "> write" in out and asked == []


def test_without_a_task_it_is_interactive_and_leaves_on_exit(tmp_path):
    llm = ScriptedLLM(text_reply("Hello there!"))
    code, out, asked, _ = run(tmp_path, ["-y"], llm, ["hi", "/exit"])
    assert code == 0 and "Hello there!" in out and "/help for commands" in out and len(asked) == 2


def test_a_permission_question_is_asked_at_the_prompt_and_a_no_stops_the_action(tmp_path):
    llm = ScriptedLLM(tool_reply(("write", {"path": "a.txt", "content": "x\n"})), text_reply("understood, I will not write it"))
    code, out, asked, proj = run(tmp_path, [], llm, ["write a file", "n", "/exit"], ask_before_editing=True)
    assert "Allow" in out and "a.txt" in out and "declined" in out and not (proj / "a.txt").exists() and any("[y]es once" in a for a in asked)


def test_yes_once_lets_it_through(tmp_path):
    llm = ScriptedLLM(tool_reply(("write", {"path": "a.txt", "content": "x\n"})), text_reply("done"))
    code, out, asked, proj = run(tmp_path, [], llm, ["write a file", "y", "/exit"], ask_before_editing=True)
    assert (proj / "a.txt").exists() and "done" in out


def test_help_agent_stats_and_sessions_commands(tmp_path):
    llm = ScriptedLLM(text_reply("first answer"))
    code, out, asked, _ = run(tmp_path, ["-y"], llm, ["hello", "/help", "/agent plan", "/agent nonsense", "/stats", "/sessions", "/exit"])
    assert "/undo" in out and "Using the plan agent." in out and "Agents: " in out and "Sessions   1" in out and "ses_" in out


def test_undo_and_redo_rewind_the_conversation_and_the_files(tmp_path):
    import subprocess

    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=proj, check=True)
    (proj / "base.txt").write_bytes(b"base\n")
    subprocess.run(["git", "add", "-A"], cwd=proj, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=proj, check=True, env={**os.environ, **ENV})
    llm = ScriptedLLM(tool_reply(("write", {"path": "made.txt", "content": "x\n"})), text_reply("made it"))
    out = io.StringIO()
    answers = iter(["make a file", "/undo", "/redo", "/redo", "/exit"])
    main(["-d", str(proj), "-y", "--no-title"], llm=llm, ask=lambda p: next(answers), out=out)
    text = out.getvalue()
    assert "Rewound to before: 'make a file'" in text and "made.txt" in text and "Brought back what you undid." in text and "Nothing to redo." in text
    assert (proj / "made.txt").exists()  # undone and redone: the file is back


def test_export_import_and_sessions_from_the_command_line(tmp_path):
    llm = ScriptedLLM(text_reply("an answer"))
    target = tmp_path / "chat.json"
    code, out, _, proj = run(tmp_path, ["-y"], llm, ["a question", f"/export {target}", "/exit"])
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["sessions"][0]["messages"][0]["text"] == "a question"
    markdown = tmp_path / "chat.md"
    run(tmp_path, ["-y"], ScriptedLLM(text_reply("x")), ["q", f"/export {markdown}", "/exit"])
    assert markdown.read_text(encoding="utf-8").startswith("# ") or "## You" in markdown.read_text(encoding="utf-8")
    code, out, _, _ = run(tmp_path, ["import", str(target)], ScriptedLLM())
    assert code == 0 and "Imported as ses_" in out


def test_admin_commands_report_bad_input_without_crashing(tmp_path):
    for argv in (["export"], ["import"], ["import", str(tmp_path / "missing.json")], ["export", "ses_nope"]):
        code, out, _, _ = run(tmp_path, argv, ScriptedLLM())
        assert code == 1
    code, out, _, _ = run(tmp_path, ["-s", "ses_nope", "hi"], ScriptedLLM())
    assert code == 1


def test_continue_picks_up_the_latest_session(tmp_path):
    first = ScriptedLLM(text_reply("one"))
    run(tmp_path, ["-y", "first"], first)
    second = ScriptedLLM(text_reply("two"))
    code, out, _, _ = run(tmp_path, ["-y", "-c", "second"], second)
    assert "first" in str(second.requests[0].messages) and "second" in str(second.requests[0].messages)
