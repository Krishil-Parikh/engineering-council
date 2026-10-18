"""Worktree manager and the harness_* tools (session rename/move, worktrees, models)."""

import os
import re
import shutil
import subprocess

import pytest

from harness import worktree as W
from harness.ai.catalog import ModelCatalog, ModelInfo
from harness.git import Git
from harness.schema import message as M
from harness.schema.permission import Rule
from harness.session.service import SessionService
from harness.tool.builtin import harness_tools
from harness.tool.info import ToolError
from harness.util.global_paths import GlobalPaths
from tests.harness.tools_rig import Rig

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class NoRunner:
    async def drain(self, session_id):
        raise AssertionError("not used")


def build(tmp_path, **kw):
    rig = Rig(tmp_path, **kw)
    (rig.proj / "a.txt").write_text("one")
    subprocess.run(["git", "add", "-A"], cwd=rig.proj, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=rig.proj, check=True, env={**os.environ, **ENV})
    manager = W.WorktreeManager(rig.db, rig.location, rig.paths)
    sessions = SessionService(rig.store, NoRunner(), str(rig.proj))
    catalog = ModelCatalog([
        ModelInfo("google", "flash-2", "Flash 2", "flash", 200),
        ModelInfo("google", "flash-1", "Flash 1", "flash", 100),
        ModelInfo("google", "pro-1", "Pro 1", "pro", 150),
        ModelInfo("other", "x-1", "Ex One", None, 300, variants=["high"]),
    ], {"google": "Google", "other": "Other Co"})
    rig.deps.extras.update({"sessions": sessions, "worktrees": manager, "model_catalog": catalog})
    for tool in harness_tools.make_all(rig.deps):
        rig.registry.add(tool)
    return rig, manager, sessions


def test_slug_shape():
    assert re.fullmatch(r"[a-z]+-[a-z]+", W.slug())


def test_rename_and_move(tmp_path):
    rig, _, sessions = build(tmp_path)
    assert "Renamed session" in rig.text("harness_session_rename", title="  Fix login  ")
    assert rig.store.get(rig.session.id).title == "Fix login"
    other = tmp_path / "elsewhere"
    other.mkdir()
    rig.text("harness_session_move", directory=str(other))
    info = rig.store.get(rig.session.id)
    assert os.path.realpath(info.directory) == os.path.realpath(other)
    switched = [m for _, m in rig.store.messages(rig.session.id) if isinstance(m, M.LocationSwitched)]
    assert len(switched) == 1 and switched[0].previous.directory == str(rig.proj)
    with pytest.raises(ToolError, match="Unable to move session"):
        rig.call("harness_session_move", directory=str(tmp_path / "nope"))
    with pytest.raises(ToolError, match="Unable to rename session ses_missing"):
        rig.call("harness_session_rename", sessionID="ses_missing", title="x")


def test_worktree_create_list_remove(tmp_path):
    rig, manager, _ = build(tmp_path)
    created = rig.call("harness_worktree_create", name="feature-x").output
    path = created["directory"]
    assert os.path.isfile(os.path.join(path, "a.txt")) and os.path.basename(path) == "feature-x"
    again = rig.call("harness_worktree_create", name="feature-x").output["directory"]
    assert os.path.basename(again) == "feature-x-2"  # an existing name gets a suffix
    listed = rig.call("harness_worktree_list").output["worktrees"]
    assert {os.path.realpath(w["directory"]) for w in listed} >= {os.path.realpath(rig.proj), os.path.realpath(path)}
    assert any(w.get("strategy") == "git" for w in listed)

    with open(os.path.join(path, "dirty.txt"), "w") as fh:
        fh.write("x")
    with pytest.raises(ToolError, match="it has modified or untracked files"):
        rig.call("harness_worktree_remove", directory=path)
    out = rig.call("harness_worktree_remove", directory=path, force=True).output
    assert out["removed"] and not os.path.exists(path)
    assert path not in [w.directory for w in manager.list()]
    with pytest.raises(ToolError, match="not a worktree of this project"):
        rig.call("harness_worktree_remove", directory=str(rig.proj))
    with pytest.raises(ToolError, match="does not exist or is not a directory"):
        rig.call("harness_worktree_remove", directory=str(tmp_path / "gone"))


def test_worktree_remove_needs_edit_permission(tmp_path):
    rig, manager, _ = build(tmp_path, rules=[Rule("*", "*", "allow"), Rule("edit", "*", "ask")], answers=["once"])
    path = manager.create(name="w")["directory"]
    rig.call("harness_worktree_remove", directory=path)
    assert rig.asked and rig.asked[0][0] == "edit" and not os.path.exists(path)


def test_refresh_discovers_and_forgets(tmp_path):
    rig, manager, _ = build(tmp_path)
    git = Git()
    repo = git.discover(str(rig.proj))
    outside = tmp_path / "manual-wt"
    git.worktree_create(repo, str(outside))
    manager.refresh()
    stored = {os.path.realpath(w.directory): w.strategy for w in manager.list()}
    assert stored[os.path.realpath(outside)] == "git"
    shutil.rmtree(outside)
    manager.refresh()
    assert os.path.realpath(outside) not in {os.path.realpath(w.directory) for w in manager.list()}


def test_create_from_unknown_source_is_rejected(tmp_path):
    rig, manager, _ = build(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(W.SourceDirectoryNotFoundError):
        manager.create(name="w", from_directory=str(other))
    with pytest.raises(W.StrategyUnavailableError):
        manager.selected = "nope"
        manager.create(name="w")


def test_models_listing(tmp_path):
    rig, _, _ = build(tmp_path)
    rig.store.update(rig.session.id, model={"provider_id": "other", "id": "x-1"})
    out = rig.call("harness_models").output
    assert [p["id"] for p in out["providers"]] == ["other", "google"]  # the session's own provider first
    google = out["providers"][1]["models"]
    assert [m["id"] for m in google] == ["google/flash-2", "google/pro-1"]  # newest of each family only
    assert out["total"] == 3 and out["next"] is None
    everything = rig.call("harness_models", all=True).output
    assert everything["total"] == 4
    paged = rig.call("harness_models", all=True, limit=2).output
    assert paged["next"] == 2 and sum(len(p["models"]) for p in paged["providers"]) == 2
    assert rig.call("harness_models", query="ex one").output["providers"][0]["models"][0]["variants"] == ["high"]
    assert [p["id"] for p in rig.call("harness_models", provider="other co").output["providers"]] == ["other"]
    assert rig.call("harness_models", query="nothing here").output == {"providers": [], "total": 0, "next": None}
