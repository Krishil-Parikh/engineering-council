"""Reference repositories: named in configuration, cloned once into a cache, refreshed when old, read through the reference tool."""

import asyncio
import json
import os
import subprocess

import pytest

from harness.app import Harness
from harness.reference import Reference, ReferenceCache, ReferenceError_, parse_references, remote_url
from harness.config import service as cfg
from tests.harness.test_runner import ScriptedLLM, text_reply, tool_reply

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, **ENV}).stdout.decode()


@pytest.fixture
def library(tmp_path):
    src = tmp_path / "library"
    src.mkdir()
    git(src, "init", "-q", "-b", "main")
    (src / "core.py").write_bytes(b"def feature():\n    return 1\n")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "first")
    return src


def test_references_come_from_configuration_and_later_documents_win(tmp_path):
    a = cfg.Document({"references": {"docs": {"path": "docs"}, "lib": {"repository": "owner/lib", "branch": "main", "description": "the library"}, "bad name!": {"path": "x"}, "empty": {}}}, tmp_path / "harness.json")
    b = cfg.Document({"references": {"docs": {"path": "other"}}}, tmp_path / "sub" / "harness.json")
    found = parse_references([a, cfg.Directory(tmp_path), b], tmp_path)
    assert sorted(found) == ["docs", "lib"]
    assert found["docs"].path == str((tmp_path / "sub" / "other").resolve()) and found["lib"].description == "the library" and found["lib"].branch == "main"


def test_owner_slash_name_means_github_and_everything_else_is_left_alone(tmp_path):
    assert remote_url("fastapi/fastapi") == "https://github.com/fastapi/fastapi.git"
    assert remote_url("https://example.com/x.git") == "https://example.com/x.git"
    assert remote_url(str(tmp_path)) == str(tmp_path)


def test_a_repository_is_cloned_once_and_refreshed_only_when_old(tmp_path, library):
    now = [1_000_000.0]
    cache = ReferenceCache(tmp_path / "cache", ttl=3600, clock=lambda: now[0])
    ref = Reference("lib", repository=str(library), branch="main")
    first = cache.directory_for(ref)
    assert b"def feature" in (first / "core.py").read_bytes()
    (library / "extra.py").write_bytes(b"X = 1\n")
    git(library, "add", "-A")
    git(library, "commit", "-q", "-m", "second")
    now[0] += 600  # young: used as it is
    assert cache.directory_for(ref) == first and not (first / "extra.py").exists()
    now[0] += 4000  # old: refreshed
    assert cache.directory_for(ref) == first and (first / "extra.py").exists()


def test_a_missing_repository_or_directory_gives_a_clear_error(tmp_path):
    cache = ReferenceCache(tmp_path / "cache")
    with pytest.raises(ReferenceError_, match="not a directory"):
        cache.directory_for(Reference("nope", path=str(tmp_path / "missing")))
    with pytest.raises(ReferenceError_, match="Could not clone"):
        cache.directory_for(Reference("gone", repository=str(tmp_path / "no-such-repo")))


def harness_with_references(tmp_path, llm, references):
    home = tmp_path / "home"
    proj = home / "proj"
    proj.mkdir(parents=True)
    (proj / "harness.json").write_text(json.dumps({"references": references}), encoding="utf-8")
    return Harness(proj, llm=llm, data_root=tmp_path / "d", home=home, db_path=":memory:", snapshots=False), proj


def test_the_agent_can_list_and_open_a_reference_and_read_it(tmp_path, library):
    llm = ScriptedLLM(
        tool_reply(("reference", {})), text_reply("saw the list"),
        tool_reply(("reference", {"name": "lib"})), text_reply("opened"),
    )
    h, _ = harness_with_references(tmp_path, llm, {"lib": {"repository": str(library), "description": "the library we integrate with"}})

    async def main():
        await h.prompt("what references do we have?")
        assert "lib: the library we integrate with" in str(llm.requests[1].messages)
        await h.prompt("open lib")
        text = str(llm.requests[3].messages)
        assert "The reference 'lib' is at" in text and "references" in text
        directory = next(p for p in (tmp_path / "d").rglob("lib-*") if p.is_dir())
        assert (directory / "core.py").exists()
        await h.close()

    asyncio.run(main())


def test_an_unknown_reference_is_explained(tmp_path, library):
    llm = ScriptedLLM(tool_reply(("reference", {"name": "ghost"})), text_reply("ok"))
    h, _ = harness_with_references(tmp_path, llm, {"lib": {"repository": str(library)}})

    async def main():
        run = await h.prompt("open ghost")
        assert "no reference named 'ghost'" in str(llm.requests[1].messages) and "lib" in str(llm.requests[1].messages)
        await h.close()

    asyncio.run(main())


def test_the_scout_is_a_read_only_subagent_that_the_main_agent_can_hand_questions_to(tmp_path, library):
    h, _ = harness_with_references(tmp_path, ScriptedLLM(), {"lib": {"repository": str(library)}})
    scout = h.agents.resolve("scout")
    assert scout.mode == "subagent" and "scout" in scout.system.lower()
    from harness.permission import evaluate

    rules = scout.permissions
    assert evaluate("edit", "x.py", rules).effect == "deny" and evaluate("shell", "ls", rules).effect == "deny"
    assert evaluate("read", "x.py", rules).effect == "allow" and evaluate("reference", "lib", rules).effect == "allow"
    assert "scout" in h.registry.get("subagent").description
