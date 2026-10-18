"""Small filesystem helpers (opencode: @opencode/util/fs-util)."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Iterable, Optional


def resolve(path: str | Path) -> Path:
    """Absolute, symlinks resolved when the path exists, otherwise normalized."""
    p = Path(os.path.expanduser(str(path)))
    try:
        return p.resolve()
    except OSError:
        return Path(os.path.abspath(p))


def same_directory(a: str | Path, b: str | Path) -> bool:
    """Equal paths, ignoring case on Windows (a drive letter may differ only in case)."""
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def contains(parent: str | Path, child: str | Path) -> bool:
    p, c = os.path.normcase(os.path.abspath(parent)), os.path.normcase(os.path.abspath(child))
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def up(targets: Iterable[str], start: str | Path, stop: Optional[str | Path] = None, type: Optional[str] = None) -> list[Path]:
    """Existing `targets` in `start` and each parent directory, nearest first. Stops after `stop` (or the filesystem root)."""
    out: list[Path] = []
    d = Path(os.path.abspath(start))
    while True:
        for t in targets:
            p = d / t
            if p.exists() and (type is None or (type == "file" and p.is_file()) or (type == "directory" and p.is_dir())):
                out.append(p)
        if (stop is not None and same_directory(d, stop)) or d.parent == d:
            break
        d = d.parent
    return out


def read_text_safe(path: str | Path) -> Optional[str]:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def is_file(path: str | Path) -> bool:
    return Path(path).is_file()


def is_dir(path: str | Path) -> bool:
    return Path(path).is_dir()


def scan(pattern: str, cwd: str | Path, *, absolute: bool = True, include: str = "file", dot: bool = True) -> list[str]:
    """Glob files under cwd. Supports `*`, `**`, `?`, `[..]` and one `{a,b}` group, like the globs opencode passes."""
    base = Path(cwd)
    if not base.is_dir():
        return []
    results: list[str] = []
    for alt in _expand_braces(pattern):
        rx = _glob_to_regex(alt)
        for root, dirs, files in os.walk(base):
            if not dot:
                dirs[:] = [d for d in dirs if not d.startswith(".")]
            names = files if include == "file" else dirs
            for n in names:
                if not dot and n.startswith("."):
                    continue
                rel = (Path(root) / n).relative_to(base).as_posix()
                if rx.fullmatch(rel):
                    results.append(str(Path(root) / n) if absolute else rel)
    return list(dict.fromkeys(results))


def _expand_braces(pattern: str) -> list[str]:
    i = pattern.find("{")
    if i == -1:
        return [pattern]
    j = pattern.find("}", i)
    if j == -1:
        return [pattern]
    head, body, tail = pattern[:i], pattern[i + 1 : j], pattern[j + 1 :]
    return [x for part in body.split(",") for x in _expand_braces(head + part + tail)]


def _glob_to_regex(pattern: str):
    import re

    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out)


def glob_up(pattern: str, start: str | Path, stop: str | Path) -> list[str]:
    """Files matching a relative pattern in `start` and each parent up to `stop`, nearest first."""
    out: list[str] = []
    d = Path(os.path.abspath(start))
    while True:
        out += [str(p) for p in sorted(d.glob(pattern)) if p.is_file()]
        if same_directory(d, stop) or d.parent == d:
            break
        d = d.parent
    return list(dict.fromkeys(out))
