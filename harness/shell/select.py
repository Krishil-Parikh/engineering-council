"""Choosing the shell commands run in (opencode: packages/core/src/shell/select.ts).

Deviation: on Windows opencode prefers PowerShell and falls back to Git Bash. Our agents' prompts and tools assume POSIX syntax, so here
Git Bash comes first (PowerShell remains selectable through config). A shell named in config is honoured if it exists."""

from __future__ import annotations

import ntpath
import os
import posixpath
import shutil
import sys
from dataclasses import dataclass
from typing import Optional

META = {
    "bash": {"login": True},
    "dash": {"login": True},
    "fish": {"deny": True, "login": True},
    "ksh": {"login": True},
    "nu": {"deny": True},
    "powershell": {"ps": True},
    "pwsh": {"ps": True},
    "sh": {"login": True},
    "zsh": {"login": True},
}


@dataclass
class Item:
    path: str
    name: str
    acceptable: bool


def name(file: str) -> str:
    base = ntpath.basename(file) if sys.platform == "win32" or "\\" in file else posixpath.basename(file)
    stem = base.lower()
    return stem[:-4] if stem.endswith(".exe") else stem


def _meta(file: str) -> dict:
    return META.get(name(file), {})


def compatible(file: str) -> bool:
    return not _meta(file).get("deny", False)


def ps(file: str) -> bool:
    return bool(_meta(file).get("ps", False))


def login(file: str) -> bool:
    return bool(_meta(file).get("login", False))


def args(file: str, command: str) -> list[str]:
    n = name(file)
    if n == "cmd":
        return ["/c", command]
    if ps(file):
        return ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]
    return ["-c", command]


def gitbash(configured: Optional[str] = None) -> Optional[str]:
    if sys.platform != "win32":
        return None
    if configured:
        return configured
    roots = []
    git = shutil.which("git")
    if git:  # git.exe sits in Git/cmd, Git/bin or Git/mingw64/bin depending on how it was found
        here = os.path.dirname(git)
        for _ in range(3):
            here = os.path.dirname(here)
            roots.append(here)
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        if os.environ.get(var):
            roots.append(os.path.join(os.environ[var], "Git"))
    for root in roots:
        for rel in (("bin", "bash.exe"), ("usr", "bin", "bash.exe")):
            candidate = os.path.join(root, *rel)
            if os.path.isfile(candidate):
                return candidate
    return None


def _executable(file: str) -> Optional[str]:
    if os.path.isabs(file):
        return file if os.path.isfile(file) else None
    return shutil.which(file)


def _fallback() -> str:
    if sys.platform == "darwin":
        return "/bin/zsh"
    return shutil.which("bash") or "/bin/sh"


def _windows_default(gitbash_path: Optional[str]) -> str:
    for candidate in (gitbash(gitbash_path), shutil.which("pwsh"), shutil.which("powershell"), os.environ.get("COMSPEC") or "cmd.exe"):
        if candidate:
            return candidate
    return "cmd.exe"


def resolve(priority: str = "config", config_shell: Optional[str] = None, gitbash_path: Optional[str] = None) -> str:
    """priority: 'config' | 'compat' (compat refuses shells whose syntax breaks our assumptions, e.g. fish and nushell)."""
    wants_compat = priority == "compat"
    candidates = [config_shell] if config_shell else ([] if sys.platform == "win32" else [os.environ.get("SHELL")])
    for file in candidates:
        if file and (not wants_compat or compatible(file)):
            found = _executable(file)
            if found:
                return found
    return _windows_default(gitbash_path) if sys.platform == "win32" else _fallback()


def list_shells(gitbash_path: Optional[str] = None) -> list[Item]:
    if sys.platform == "win32":
        files = [f for f in (gitbash(gitbash_path), shutil.which("pwsh"), shutil.which("powershell"), os.environ.get("COMSPEC") or "cmd.exe") if f]
    else:
        try:
            with open("/etc/shells", encoding="utf-8") as fh:
                files = [l.strip() for l in fh if l.strip() and not l.startswith("#")]
        except OSError:
            files = ["/bin/bash", "/bin/zsh", "/bin/sh"]
    out, seen = [], set()
    for f in files:
        if f in seen or not _executable(f):
            continue
        seen.add(f)
        out.append(Item(f, name(f), compatible(f)))
    return out
