"""A small rig for exercising built-in tools through the registry, with real permission rules and a scripted approver."""

import asyncio
import subprocess
from pathlib import Path

from harness.db.database import Database
from harness.file_access import FileAccess
from harness.location import Location
from harness.permission import Permission, PermissionSaved
from harness.ripgrep import Ripgrep
from harness.schema.permission import Rule
from harness.session.instructions import SessionInstructions
from harness.session.store import SessionStore
from harness.tool.builtin.deps import ToolDeps
from harness.tool.info import ToolError
from harness.tool.registry import Call, ToolRegistry
from harness.util.global_paths import GlobalPaths


class Rig:
    """tmp/home/proj is the project (a git repo); `rules` apply to the agent; `answers` is the sequence of replies to permission prompts."""

    def __init__(self, tmp_path, rules=None, answers=None, git=True):
        self.home = tmp_path / "home"
        self.proj = self.home / "proj"
        self.proj.mkdir(parents=True)
        if git:
            subprocess.run(["git", "init", "-q"], cwd=self.proj, check=True)
        self.paths = GlobalPaths.default(root=tmp_path / "g", home=self.home).ensure()
        self.location = Location.of(self.proj)
        self.db = Database(":memory:")
        self.store = SessionStore(self.db)
        self.session = self.store.create(str(self.proj), agent="build")
        self.rules = rules if rules is not None else [Rule("*", "*", "allow")]
        self.asked = []
        self.answers = list(answers or [])
        self.permission = Permission(PermissionSaved(self.db, "p"), lambda sid, agent: self.rules, observer=self._observe)
        self.access = FileAccess(self.location, self.permission, home=self.home)
        self.deps = ToolDeps(self.location, self.permission, self.access, self.store, SessionInstructions(self.store, self.location), Ripgrep(use_binary=False))
        self.registry = ToolRegistry()
        self._n = 0

    def _observe(self, kind, data):
        if kind == "permission.asked":
            req = data["request"]
            self.asked.append((req.action, list(req.resources), req.metadata))
            reply = self.answers.pop(0) if self.answers else "once"
            self.permission.reply(req.id, reply[0] if isinstance(reply, tuple) else reply, reply[1] if isinstance(reply, tuple) else None)

    def add(self, *makers):
        for m in makers:
            self.registry.add(m(self.deps))
        return self

    def call(self, name, **args):
        """Run a tool; returns the NormalizedResult, or raises ToolError / permission errors."""
        self._n += 1

        async def go():
            snap = self.registry.snapshot(self.rules)
            return await snap.execute(session_id=self.session.id, agent="build", message_id="msg_t", call=Call(f"c{self._n}", name, args))

        return asyncio.run(go())

    def text(self, name, **args):
        return "\n".join(c.text for c in self.call(name, **args).content if hasattr(c, "text"))

    def write(self, rel, content, binary=False):
        p = self.proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if binary else content.encode("utf-8"))
        return p
