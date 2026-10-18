"""File search (opencode: packages/core/src/ripgrep.ts).

opencode shells out to ripgrep. This uses `rg` when it is installed, with the same arguments, and otherwise a Python
implementation with the same behaviour: inside a git repository it searches tracked and untracked-but-not-ignored files
(.gitignore is honoured), elsewhere every file; hidden files are excluded from `glob` unless asked for and included in `grep`;
`.git` is never searched; binary files are skipped by `grep`."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

MAX_SUBMATCHES = 100
MAX_LINE_TEXT = 2_000
MAX_FILE_BYTES = 10 * 1024 * 1024


class RipgrepError(Exception):
    pass


class InvalidPatternError(RipgrepError):
    def __init__(self, pattern: str, message: str) -> None:
        super().__init__(message)
        self.pattern, self.message = pattern, message


@dataclass
class Entry:
    path: str  # relative to the search directory, forward slashes
    type: str = "file"


@dataclass
class Submatch:
    text: str
    start: int
    end: int


@dataclass
class Match:
    entry: Entry
    line: int
    offset: int
    text: str
    submatches: list[Submatch] = field(default_factory=list)


def _normalize(value: str) -> str:
    return re.sub(r"^[\\/]+", "", re.sub(r"^(?:\.[\\/])+", "", value)).replace("\\", "/")


# --------------------------------------------------------------------------- glob matching (ripgrep --glob semantics)


def _glob_regex(pattern: str) -> re.Pattern[str]:
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
        elif pattern[i] == "{":
            j = pattern.find("}", i)
            if j == -1:
                out += re.escape(pattern[i])
                i += 1
            else:
                out += "(?:" + "|".join(_glob_regex(p).pattern for p in pattern[i + 1 : j].split(",")) + ")"
                i = j + 1
        elif pattern[i] == "[":
            j = pattern.find("]", i)
            if j == -1:
                out += re.escape(pattern[i])
                i += 1
            else:
                out += pattern[i : j + 1]
                i = j + 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out)


def glob_matches(rel: str, pattern: str) -> bool:
    """A pattern without a slash matches the file name at any depth; one with a slash is anchored to the search directory."""
    pattern = pattern.replace("\\", "/")
    if pattern.startswith("./"):
        pattern = pattern[2:]
    rx = _glob_regex(pattern.lstrip("/"))
    if "/" not in pattern.rstrip("/"):
        return bool(rx.fullmatch(rel.rsplit("/", 1)[-1])) or bool(rx.fullmatch(rel))
    return bool(rx.fullmatch(rel))


# --------------------------------------------------------------------------- file listing


def _git(cwd: str, *args: str) -> Optional[bytes]:
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def list_files(cwd: str, hidden: bool, follow: bool = False) -> list[str]:
    """Files under cwd as relative forward-slash paths."""
    inside = _git(cwd, "rev-parse", "--is-inside-work-tree")
    files: list[str] = []
    if inside is not None and inside.strip() == b"true":
        listed = _git(cwd, "ls-files", "-co", "--exclude-standard", "-z")
        if listed is not None:
            files = [f for f in listed.decode("utf-8", "replace").split("\0") if f and os.path.isfile(os.path.join(cwd, f))]
    else:
        for root, dirs, names in os.walk(cwd, followlinks=follow):
            dirs[:] = [d for d in dirs if d != ".git"]
            files += [os.path.relpath(os.path.join(root, n), cwd).replace("\\", "/") for n in names]
    files = [f for f in files if not re.search(r"(^|/)\.git(/|$)", f)]
    if not hidden:
        files = [f for f in files if not any(part.startswith(".") for part in f.split("/"))]
    return files


# --------------------------------------------------------------------------- the service


class Ripgrep:
    def __init__(self, binary: Optional[str] = None, use_binary: bool = True) -> None:
        self.rg = (binary or shutil.which("rg")) if use_binary else None

    # ---- glob
    def glob(self, *, cwd: str, pattern: str, limit: int, hidden: bool = False, follow: bool = False) -> list[Entry]:
        if self.rg:
            args = ["--no-config", "--files", *(["--hidden"] if hidden else []), *(["--follow"] if follow else []), f"--glob={pattern}",
                    *([] if hidden else ["--glob=!**/.*"]), "--glob=!**/.git/**", "."]
            rows = self._run(cwd, args, limit, lambda line: _normalize(line))
            return [Entry(r) for r in rows]
        hits = sorted(f for f in list_files(cwd, hidden, follow) if glob_matches(f, pattern))
        return [Entry(f) for f in hits[:limit]]

    # ---- grep
    def grep(
        self, *, cwd: str, pattern: str, limit: int, file: Optional[str] = None, include: Optional[str] = None, literal: bool = False,
        case_sensitive: bool = True,
    ) -> list[Match]:
        if self.rg:
            return self._grep_rg(cwd, pattern, limit, file, include, literal, case_sensitive)
        try:
            rx = re.compile(re.escape(pattern) if literal else pattern, 0 if case_sensitive else re.IGNORECASE)
        except re.error as exc:
            raise InvalidPatternError(pattern, f"regex parse error: {exc}") from None
        files = [file] if file else sorted(list_files(cwd, hidden=True))
        if include:
            files = [f for f in files if glob_matches(f, include)]
        out: list[Match] = []
        for rel in files:
            p = Path(cwd) / rel
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
                data = p.read_bytes()
            except OSError:
                continue
            if b"\x00" in data[:8192]:
                continue  # binary
            offset = 0
            for n, raw in enumerate(data.split(b"\n"), 1):
                line = raw.decode("utf-8", "replace")
                subs = [Submatch(m.group(0), m.start(), m.end()) for m in rx.finditer(line)][:MAX_SUBMATCHES]
                if subs:
                    text = line.rstrip("\r")
                    out.append(Match(Entry(rel), n, offset, text if len(text) <= MAX_LINE_TEXT else text[:MAX_LINE_TEXT] + "...", subs))
                    if len(out) >= limit:
                        return out
                offset += len(raw) + 1
        return out

    def _grep_rg(self, cwd: str, pattern: str, limit: int, file: Optional[str], include: Optional[str], literal: bool, case_sensitive: bool) -> list[Match]:
        args = ["--no-config", "--json", "--hidden", "--no-messages", *(["--fixed-strings"] if literal else []),
                *(["--ignore-case"] if not case_sensitive else []), *([f"--glob={include}"] if include else []), "--glob=!**/.git/**", "--", pattern, file or "."]

        def parse(line: str) -> Optional[Match]:
            row = json.loads(line)
            if row.get("type") != "match":
                return None
            d = row["data"]
            text = d["lines"]["text"].rstrip("\r\n")
            return Match(
                Entry(_normalize(d["path"]["text"])), d["line_number"], d["absolute_offset"],
                text if len(text) <= MAX_LINE_TEXT else text[:MAX_LINE_TEXT] + "...",
                [Submatch(s["match"]["text"], s["start"], s["end"]) for s in d["submatches"][:MAX_SUBMATCHES]],
            )

        return self._run(cwd, args, limit, parse, pattern)  # type: ignore[return-value]

    def _run(self, cwd: str, args: list[str], limit: int, parse, pattern: Optional[str] = None) -> list:
        proc = subprocess.run([self.rg, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
        rows = [r for r in (parse(l) for l in proc.stdout.splitlines() if l) if r is not None]
        if len(rows) > limit:
            return rows[:limit]
        stderr = proc.stderr
        if pattern and proc.returncode == 2 and ("regex parse error" in stderr or "error parsing regex" in stderr):
            raise InvalidPatternError(pattern, stderr.strip())
        if proc.returncode not in (0, 1, 2):
            raise RipgrepError(stderr.strip() or f"ripgrep failed with code {proc.returncode}")
        return [] if proc.returncode == 1 else rows
