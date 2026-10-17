import subprocess

import pytest

from coding_harness.jobs import JobManager
from coding_harness.permission import Permissions, Rule, evaluate, wildcard
from coding_harness.session import Session
from coding_harness.tools import builtin_tools
from coding_harness.tools.base import FileTime, ToolContext, ToolFailure, validate_args
from coding_harness.tools.files import find_matches, glob_match
from coding_harness.tools.patch import parse_patch
from coding_harness.tools.shell import scan_command, split_commands
from tests.harness.conftest import run

TOOLS = {t.name: t for t in builtin_tools()}


def ctx_for(ws, asker=None, rules=None):
    session = Session(ws, "build")
    return ToolContext(
        session_id=session.id, agent="build", call_id="c", workspace=ws, cwd=ws.cwd, permissions=Permissions(asker), rules=rules or [Rule("*", "*", "allow")],
        file_time=FileTime(), jobs=JobManager(), session=session,
    )


def use(name, ctx, **args):
    return run(TOOLS[name].run(validate_args(args, TOOLS[name].parameters), ctx))


# ---- permissions


def test_wildcards_and_last_rule_wins():
    assert wildcard("git status", "git status *") and wildcard("git status -s", "git status *")
    assert not wildcard("git statusx", "git status *")
    assert wildcard("a/b/.env", "*.env") and not wildcard("a/b/.envx", "*.env")
    rules = [Rule("*", "*", "allow"), Rule("shell", "git push *", "ask"), Rule("shell", "git push --force *", "deny")]
    assert evaluate("shell", "ls", rules).effect == "allow"
    assert evaluate("shell", "git push origin main", rules).effect == "ask"
    assert evaluate("shell", "git push --force origin main", rules).effect == "deny"
    assert evaluate("edit", "x", [Rule("shell", "*", "allow")]).effect == "ask"  # nothing matched -> ask


def test_ask_without_asker_is_a_refusal_the_model_can_read(ws):
    ctx = ctx_for(ws, rules=[Rule("*", "*", "ask")])
    with pytest.raises(ToolFailure, match="Approval needed"):
        use("write", ctx, path="a.txt", content="x")
    assert not (ws.cwd / "a.txt").exists()


def test_always_reply_is_remembered(ws):
    asked = []

    async def asker(req):
        asked.append(req)
        return {"reply": "always"}

    ctx = ctx_for(ws, asker, [Rule("*", "*", "ask")])
    use("write", ctx, path="a.txt", content="1")
    use("write", ctx, path="a.txt", content="2")  # same resource: no second question
    assert len(asked) == 1


def test_declining_carries_feedback_to_the_model(ws):
    async def asker(req):
        return {"reply": "reject", "message": "use the tests folder"}

    ctx = ctx_for(ws, asker, [Rule("*", "*", "ask")])
    with pytest.raises(ToolFailure, match="use the tests folder"):
        use("write", ctx, path="a.txt", content="x")


# ---- read / write / edit


def test_read_numbers_lines_and_pages(ws):
    (ws.cwd / "f.txt").write_text("".join(f"line {i}\n" for i in range(1, 11)))
    ctx = ctx_for(ws)
    out = use("read", ctx, path="f.txt", offset=3, limit=2).output
    assert "3: line 3" in out and "4: line 4" in out and "5: line 5" not in out and "offset=5" in out
    assert "10: line 10" in use("read", ctx, path="f.txt").output


def test_read_directory_and_missing_file_suggestion(ws):
    (ws.cwd / "alpha.py").write_text("x")
    (ws.cwd / "sub").mkdir()
    ctx = ctx_for(ws)
    listing = use("read", ctx, path=".").output
    assert "alpha.py" in listing and "sub/" in listing
    with pytest.raises(ToolFailure, match="alpha.py"):
        use("read", ctx, path="alpah.py")


def test_write_requires_reading_an_existing_file_first(ws):
    (ws.cwd / "f.txt").write_text("old")
    ctx = ctx_for(ws)
    with pytest.raises(ToolFailure, match="read"):
        use("write", ctx, path="f.txt", content="new")
    use("read", ctx, path="f.txt")
    use("write", ctx, path="f.txt", content="new")
    assert (ws.cwd / "f.txt").read_text() == "new"
    use("write", ctx, path="deep/er/new.txt", content="hi")
    assert (ws.cwd / "deep/er/new.txt").exists()


def test_edit_detects_outside_changes(ws):
    f = ws.cwd / "f.txt"
    f.write_text("a\n")
    ctx = ctx_for(ws)
    use("read", ctx, path="f.txt")
    import os, time

    f.write_text("a changed\n")
    os.utime(f, ns=(time.time_ns() + 5_000_000_000, time.time_ns() + 5_000_000_000))
    with pytest.raises(ToolFailure, match="changed on disk"):
        use("edit", ctx, path="f.txt", oldString="a", newString="b")


def test_edit_unique_replaceall_and_not_found(ws):
    f = ws.cwd / "f.py"
    f.write_text("x = 1\ny = 1\nx = 1\n")
    ctx = ctx_for(ws)
    use("read", ctx, path="f.py")
    with pytest.raises(ToolFailure, match="2 matches"):
        use("edit", ctx, path="f.py", oldString="x = 1", newString="x = 2")
    use("edit", ctx, path="f.py", oldString="x = 1", newString="x = 2", replaceAll=True)
    assert f.read_text() == "x = 2\ny = 1\nx = 2\n"
    with pytest.raises(ToolFailure, match="Could not find"):
        use("edit", ctx, path="f.py", oldString="nope", newString="z")
    with pytest.raises(ToolFailure, match="identical"):
        use("edit", ctx, path="f.py", oldString="y = 1", newString="y = 1")


def test_edit_tolerates_trailing_space_and_curly_quotes_and_keeps_crlf(ws):
    f = ws.cwd / "f.txt"
    f.write_bytes("say “hi”  \r\nnext\r\n".encode("utf-8"))
    ctx = ctx_for(ws)
    use("read", ctx, path="f.txt")
    use("edit", ctx, path="f.txt", oldString='say "hi"\n', newString='say "bye"\n')
    assert f.read_bytes() == b'say "bye"\r\nnext\r\n'


def test_find_matches_exact_then_fuzzy():
    assert find_matches("a b a", "a") == [(0, 1), (4, 5)]
    assert find_matches("  x = 1   \ny\n", "  x = 1\n") != []


# ---- patch


def test_patch_add_update_move_delete(ws):
    (ws.cwd / "src").mkdir()
    (ws.cwd / "src/app.py").write_text('def greet():\n    print("Hi")\n    return 1\n')
    (ws.cwd / "old.txt").write_text("bye\n")
    ctx = ctx_for(ws)
    use("read", ctx, path="src/app.py")
    use("read", ctx, path="old.txt")
    patch = "\n".join([
        "*** Begin Patch", "*** Add File: hello.txt", "+Hello world", "*** Update File: src/app.py", "*** Move to: src/main.py",
        "@@ def greet():", '-    print("Hi")', '+    print("Hello, world!")', "*** Delete File: old.txt", "*** End Patch",
    ])
    use("patch", ctx, patch=patch)
    assert (ws.cwd / "hello.txt").read_text() == "Hello world\n"
    assert (ws.cwd / "src/main.py").read_text() == 'def greet():\n    print("Hello, world!")\n    return 1\n'
    assert not (ws.cwd / "src/app.py").exists() and not (ws.cwd / "old.txt").exists()


def test_patch_rejects_bad_envelope_and_missing_context(ws):
    with pytest.raises(ToolFailure):
        parse_patch("nonsense")
    (ws.cwd / "a.txt").write_text("one\n")
    ctx = ctx_for(ws)
    use("read", ctx, path="a.txt")
    with pytest.raises(ToolFailure, match="Could not find"):
        use("patch", ctx, patch="*** Begin Patch\n*** Update File: a.txt\n@@\n-zzz\n+yyy\n*** End Patch")


# ---- glob / grep


def test_glob_and_grep_outside_git(ws):
    (ws.cwd / "a.py").write_text("import os\nTODO fix\n")
    (ws.cwd / "pkg").mkdir()
    (ws.cwd / "pkg/b.py").write_text("print('hi')\n")
    (ws.cwd / "node_modules").mkdir()
    (ws.cwd / "node_modules/x.py").write_text("TODO hidden\n")
    ctx = ctx_for(ws)
    files = use("glob", ctx, pattern="**/*.py").output
    assert "a.py" in files and "pkg/b.py" in files and "node_modules" not in files
    assert "pkg/b.py" in use("glob", ctx, pattern="*.py").output  # no slash -> any depth
    g = use("grep", ctx, pattern="TODO").output
    assert "a.py" in g and "Line 2: TODO fix" in g and "node_modules" not in g
    assert "No matches" in use("grep", ctx, pattern="zzzzz").output
    assert "a.py" in use("grep", ctx, pattern="todo", caseSensitive=False, include="*.py").output


def test_glob_respects_gitignore(ws):
    subprocess.run(["git", "init", "-q"], cwd=ws.cwd, check=True)
    (ws.cwd / ".gitignore").write_text("secret.py\n")
    (ws.cwd / "secret.py").write_text("x")
    (ws.cwd / "keep.py").write_text("x")
    out = use("glob", ctx_for(ws), pattern="*.py").output
    assert "keep.py" in out and "secret.py" not in out


def test_glob_match_semantics():
    assert glob_match("src/a/b.ts", "src/**/*.ts") and glob_match("a.tsx", "*.{ts,tsx}") and not glob_match("a.js", "*.{ts,tsx}")


# ---- shell


def test_shell_runs_and_reports_exit_code(ws):
    r = use("shell", ctx_for(ws), command="echo hello && exit 3")
    assert "hello" in r.output and "exited with code 3" in r.output and r.metadata["exit"] == 3


def test_shell_timeout_stops_the_command(ws):
    r = use("shell", ctx_for(ws), command="sleep 20", timeout=500)
    assert r.metadata["timeout"] is True and "timeout" in r.output


def test_shell_background_notifies(ws):
    async def go():
        ctx = ctx_for(ws)
        res = await TOOLS["shell"].run({"command": "echo done-bg", "background": True}, ctx)
        assert "background" in res.output
        assert await ctx.jobs.wait_for_news(10)
        return ctx.jobs.drain()

    notes = run(go())
    assert any("done-bg" in n and "finished" in n for n in notes)


def test_shell_permission_patterns(ws):
    assert split_commands("a && b | c; d") == ["a", "b", "c", "d"]
    assert split_commands("echo 'a && b'") == ["echo 'a && b'"]
    cmds, dirs = scan_command("FOO=1 git push origin main && ls /etc", ws.cwd)
    assert cmds[0] == ("git push origin main", "git push *") and any(str(d).endswith("etc") for d in dirs)


def test_git_push_needs_approval_and_echo_does_not(ws):
    from coding_harness.agents import BASE_RULES

    ctx = ctx_for(ws, rules=BASE_RULES)
    assert use("shell", ctx, command="echo ok").output.strip() == "ok"
    with pytest.raises(ToolFailure, match="Approval needed"):
        use("shell", ctx, command="git push origin main")


def test_outside_project_needs_external_directory_approval(ws, tmp_path):
    from coding_harness.agents import BASE_RULES

    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "x.txt").write_text("secret")
    with pytest.raises(ToolFailure, match="Approval needed"):
        use("read", ctx_for(ws, rules=BASE_RULES), path=str(other / "x.txt"))


def test_big_output_is_truncated_with_file(ws):
    from coding_harness.tools.base import ToolResult, truncate_result

    big = ToolResult("\n".join(f"row {i}" for i in range(5000)))
    out = truncate_result(big, ws.output_dir, "hint")
    assert out.metadata["truncated"] and "Full output saved to" in out.output and out.output.count("\n") < 2100


def test_invalid_arguments_are_explained():
    with pytest.raises(ToolFailure, match="missing required"):
        validate_args({}, TOOLS["read"].parameters)
    assert validate_args({"path": "a", "offset": "3", "zzz": 1}, TOOLS["read"].parameters) == {"path": "a", "offset": 3}
