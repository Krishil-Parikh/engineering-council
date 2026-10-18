"""Shell scanning, process service, job service and shell tool (scenarios from opencode's shell-parse and tool-shell tests)."""

import asyncio
import os
import sys

import pytest

from harness.job import JobService
from harness.schema.message import Synthetic
from harness.schema.permission import Rule
from harness.shell import parse as SP
from harness.shell import result as SR
from harness.shell import select as Select
from harness.shell.service import ShellService, cleanup
from harness.tool.builtin import shell as shell_tool
from harness.tool.info import ToolError
from tests.harness.tools_rig import Rig

BASH = Select.resolve("compat")


def scan(cmd, cwd="/work"):
    return SP.scan(cmd, BASH, cwd)


# ------------------------------------------------------------------ parsing

def test_scan_lists_every_simple_command_with_save_patterns():
    r = scan("git status && npm run test -- --watch | grep ok")
    assert [c["resource"] for c in r.commands] == ["git status", "npm run test -- --watch", "grep ok"]
    assert [c["save"] for c in r.commands] == ["git status *", "npm run test *", "grep *"]


def test_scan_includes_substitutions_and_redirects():
    r = scan("echo $(ls foo) > out.txt")
    assert [c["resource"] for c in r.commands] == ["echo $(ls foo) > out.txt", "ls foo"]


def test_scan_cd_becomes_directories_not_commands():
    r = scan("cd /tmp && ls -la && cd ~ && cd $HOME && cd 'a b'")
    assert [c["resource"] for c in r.commands] == ["ls -la"]
    assert r.directories == ["/tmp", os.path.expanduser("~"), "a b"]


def test_scan_arity_prefixes():
    assert scan("docker compose up -d").commands[0]["save"] == "docker compose up *"
    assert scan("rm -rf build").commands[0]["save"] == "rm *"
    assert scan("somecmd a b").commands[0]["save"] == "somecmd *"


def test_scan_env_assignments_and_loops():
    r = scan("FOO=1 make test; for f in a b; do cat $f; done")
    assert [c["save"] for c in r.commands] == ["make test *", "cat *"]


def test_powershell_fallback_splits_statements():
    r = SP.scan("Set-Location C:\\x; git status | Select-Object -First 1", "pwsh", "C:\\")
    assert r.directories == ["C:\\x"]
    assert [c["resource"] for c in r.commands] == ["git status", "Select-Object -First 1"]


# ------------------------------------------------------------------ results

def test_result_notices():
    assert SR.notice(SR.Output("", False, exit=2)) == "Exited with code 2"
    assert SR.notice(SR.Output("", False, exit=0)) is None
    assert SR.notice(SR.Output("", False, timeout=True)) == "Timed out before completion"
    assert SR.notice(SR.Output("", False, signal="SIGKILL")) == "Killed by SIGKILL"
    n = SR.notification("sh_1", "ls", "completed", "x", job_id="job_1")
    assert n["text"] == '<shell id="job_1" state="completed" command="ls">\nx\n</shell>' and n["metadata"]["jobID"] == "job_1"


# ------------------------------------------------------------------ service

def test_service_captures_output_and_exit(tmp_path):
    async def main():
        svc = ShellService(tmp_path / "o", str(tmp_path))
        info = await svc.create("echo hello; echo oops >&2; exit 3", shell=BASH)
        res = await svc.result(info)
        assert res.info.status == "exited" and res.info.exit == 3
        assert res.capture["output"].splitlines() == ["hello", "oops"] and not res.capture["truncated"]
        await svc.close()

    asyncio.run(main())


def test_service_timeout_kills_and_marks(tmp_path):
    async def main():
        svc = ShellService(tmp_path / "o", str(tmp_path))
        info = await svc.create("sleep 30", timeout=300, shell=BASH)
        res = await svc.result(info)
        assert res.info.status == "timeout" and res.info.exit is None
        await svc.close()

    asyncio.run(main())


def test_service_tail_truncation_points_at_the_file(tmp_path):
    async def main():
        svc = ShellService(tmp_path / "o", str(tmp_path))
        svc.max_lines = 3
        info = await svc.create("for i in 1 2 3 4 5; do echo line$i; done", shell=BASH)
        res = await svc.result(info)
        assert res.capture["truncated"]
        assert res.capture["output"].startswith("line3\nline4\nline5")
        assert f"[showing lines 3-5 of 5; full output saved to {info.file}]" in res.capture["output"]
        await svc.close()

    asyncio.run(main())


def test_service_remove_unblocks_waiters_and_deletes_file(tmp_path):
    async def main():
        svc = ShellService(tmp_path / "o", str(tmp_path))
        info = await svc.create("sleep 30", shell=BASH)
        waiter = asyncio.ensure_future(svc.wait(info.id))
        await asyncio.sleep(0.05)
        await svc.remove(info.id)
        with pytest.raises(Exception):
            await waiter
        assert not os.path.exists(info.file)
        res = await svc.result(info)
        assert res.info.status == "killed" and res.capture is None

    asyncio.run(main())


def test_cleanup_removes_only_old_output(tmp_path):
    d = tmp_path / "shell" / "proj"
    d.mkdir(parents=True)
    old, new = d / "sh_aaaaaaaaaaaa.out", d / "sh_bbbbbbbbbbbb.out"
    old.write_text("x")
    new.write_text("y")
    os.utime(old, (1, 1))
    assert cleanup(tmp_path / "shell") == [str(old)] and new.exists()


# ------------------------------------------------------------------ jobs

def test_job_lifecycle_and_block():
    async def main():
        jobs = JobService()

        async def run():
            await asyncio.sleep(0.05)
            return "done"

        await jobs.start("j1", "t", run)
        r = await jobs.block("j1", "s1")
        assert r.type == "finished" and r.info.output == "done"

        async def boom():
            raise RuntimeError("bad")

        await jobs.start("j2", "t", boom)
        w = await jobs.wait("j2")
        assert w.info.status == "error" and w.info.error == "bad"

    asyncio.run(main())


def test_job_background_releases_block_and_cancel_interrupts():
    async def main():
        jobs = JobService()
        started = asyncio.Event()

        async def run():
            started.set()
            await asyncio.sleep(30)
            return "x"

        await jobs.start("j", "t", run)
        blocker = asyncio.ensure_future(jobs.block("j", "s"))
        await asyncio.sleep(0.05)
        assert len(jobs.background_all("s")) == 1
        assert (await blocker).type == "backgrounded"
        info = await jobs.cancel("j")
        assert info.status == "cancelled"

    asyncio.run(main())


# ------------------------------------------------------------------ tool

@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path).add(shell_tool.make)


def test_tool_runs_a_command(rig):
    out = rig.text("shell", command="echo hi")
    assert out.strip() == "hi"


def test_tool_nonzero_exit_is_useful(rig):
    out = rig.text("shell", command="echo partial; exit 4")
    assert [l for l in out.splitlines() if l] == ["partial", "Exited with code 4"]


def test_tool_sets_agent_environment(rig):
    assert rig.text("shell", command='echo "$AGENT-$HARNESS"').strip() == "1-1"


def test_tool_workdir_relative_and_missing(rig):
    (rig.proj / "sub").mkdir()
    assert os.path.basename(rig.text("shell", command="pwd", workdir="sub").strip()) == "sub"
    with pytest.raises(ToolError, match="Working directory does not exist"):
        rig.call("shell", command="pwd", workdir="nope")


def test_tool_timeout_message(rig):
    out = rig.text("shell", command="sleep 30", timeout=300)
    assert "Command exceeded timeout of 300 ms" in out and "Timed out before completion" in out


def test_tool_permission_resources_and_saves(tmp_path):
    rig = Rig(tmp_path, rules=[Rule("*", "*", "allow"), Rule("shell", "*", "ask")], answers=["once"]).add(shell_tool.make)
    rig.call("shell", command="echo a && git status")
    asks = [a for a in rig.asked if a[0] == "shell"]
    assert len(asks) == 1 and asks[0][1] == ["echo a", "git status"]


def test_tool_external_cd_needs_directory_approval(tmp_path):
    rig = Rig(tmp_path, rules=[Rule("*", "*", "allow"), Rule("external_directory", "*", "ask")], answers=["once"]).add(shell_tool.make)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    rig.call("shell", command=f"cd '{outside.as_posix()}' && echo ok")
    assert any(a[0] == "external_directory" for a in rig.asked)


def test_tool_background_returns_id_then_notifies(rig):
    async def main():
        res = await rig.acall("shell", command="echo bg-output", background=True)
        text = "\n".join(c.text for c in res.content)
        assert "Command moved to the background (shell ID: sh_" in text and "DO NOT poll" in text
        for _ in range(100):
            await asyncio.sleep(0.05)
            notes = [m for _, m in rig.store.messages(rig.session.id) if isinstance(m, Synthetic)]
            if notes:
                break
        assert notes and 'state="completed"' in notes[0].text and "bg-output" in notes[0].text
        assert notes[0].metadata["source"] == "shell"

    asyncio.run(main())


def test_tool_signal_backgrounds_a_foreground_command(rig):
    async def main():
        call = asyncio.ensure_future(rig.acall("shell", command="sleep 1; echo late"))
        await asyncio.sleep(0.3)
        assert len(rig.jobs.background_all(rig.session.id, "shell")) == 1
        res = await call
        assert "moved to the background" in "\n".join(c.text for c in res.content)
        for _ in range(100):
            await asyncio.sleep(0.05)
            if any(isinstance(m, Synthetic) for _, m in rig.store.messages(rig.session.id)):
                break
        assert any(isinstance(m, Synthetic) and "late" in m.text for _, m in rig.store.messages(rig.session.id))

    asyncio.run(main())


def test_tool_description_names_the_shell():
    d = shell_tool.description("bash")
    assert "using bash." in d and d.startswith("Execute a shell command and return its output.")
