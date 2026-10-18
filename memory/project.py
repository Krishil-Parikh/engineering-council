"""Project memory: what an agent entering this repository would otherwise have to rediscover.

Two committed files, kept current by the team after every merge:

  docs/CODEMAP.md  a map of the whole codebase built from the code itself: the directory tree and, per file, its purpose (first docstring or
                   comment line) and its top-level classes and functions. Deterministic: no model is involved, so it is always accurate.
  docs/MEMORY.md   a running log of what the team did and decided: features merged (who, what, which files), design decisions, conflicts and
                   how they were resolved, failures. When the log outgrows its budget, the oldest entries are compacted into a checkpoint
                   by a summarizer and the newest ones stay verbatim, the same shape as the harness's session compaction.

Nothing here imports the model or the harness: the summarizer is passed in."""

from __future__ import annotations

import ast
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Optional

IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".pytest_cache", ".mypy_cache", ".idea", ".vscode", "coverage"}
TEXT_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb", ".c", ".h", ".cpp", ".cs", ".sh", ".sql", ".md", ".toml", ".json", ".yaml", ".yml", ".html", ".css"}
MAX_FILE_BYTES = 200_000
CHECKPOINT_HEADING = "## Checkpoint (earlier history, compacted)"
ENTRY_PREFIX = "### "


# ------------------------------------------------------------------ the code map

@dataclass
class FileInfo:
    path: str
    lines: int
    purpose: str = ""
    symbols: list[str] = field(default_factory=list)


def _python_info(text: str) -> tuple[str, list[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "", []
    doc = (ast.get_docstring(tree) or "").strip().splitlines()
    symbols = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")][:6]
            symbols.append(f"class {node.name}" + (f" ({', '.join(methods)})" if methods else ""))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            symbols.append(("async def " if isinstance(node, ast.AsyncFunctionDef) else "def ") + node.name)
    return (doc[0] if doc else ""), symbols


_SYMBOL = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\s+(\w+)|class\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s*)?\(|func\s+(\w+)|fn\s+(\w+)|def\s+(\w+))", re.M)


def _generic_info(path: Path, text: str) -> tuple[str, list[str]]:
    purpose = ""
    for line in text.splitlines()[:8]:
        stripped = line.strip().lstrip("#/*-– ").strip()
        if stripped and not stripped.startswith(("!", "<?", "import", "package", "use ")):
            purpose = stripped[:140]
            break
    if path.suffix == ".md":
        return purpose, []
    names = []
    for m in _SYMBOL.finditer(text):
        name = next((g for g in m.groups() if g), None)
        if name and name not in names:
            names.append(name)
    return purpose, names[:12]


def scan(root: Path, extra_ignored: Iterable[str] = ()) -> list[FileInfo]:
    root = Path(root)
    ignored = IGNORED_DIRS | set(extra_ignored)
    out: list[FileInfo] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in ignored and not d.startswith(".") or d in (".github",))
        for name in sorted(files):
            path = Path(current) / name
            if path.suffix.lower() not in TEXT_SUFFIXES or name in ("CODEMAP.md", "MEMORY.md"):
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            purpose, symbols = _python_info(text) if path.suffix == ".py" else _generic_info(path, text)
            out.append(FileInfo(path.relative_to(root).as_posix(), text.count("\n") + 1, purpose, symbols))
    return out


def render_codemap(files: list[FileInfo], project: str = "", max_chars: int = 24000) -> str:
    """Directory by directory: each file with its size, purpose and top-level symbols. Truncated cleanly if the repository is huge."""
    head = f"# Code map{' — ' + project if project else ''}\n\nGenerated from the code; do not edit by hand. Updated after every merge.\n\n"
    by_dir: dict[str, list[FileInfo]] = {}
    for f in files:
        by_dir.setdefault(os.path.dirname(f.path) or ".", []).append(f)
    body = ""
    shown = 0
    for directory in sorted(by_dir):
        section = f"## {directory}/\n\n"
        for f in by_dir[directory]:
            line = f"- `{os.path.basename(f.path)}` ({f.lines} lines)"
            if f.purpose:
                line += f": {f.purpose}"
            if f.symbols:
                line += f"\n  - {'; '.join(f.symbols)}"
            section += line + "\n"
        if len(head) + len(body) + len(section) > max_chars:
            body += f"\n_(map truncated: {len(files) - shown} more files in later directories)_\n"
            break
        body += section + "\n"
        shown += len(by_dir[directory])
    return head + body


def update_codemap(root: Path, project: str = "", path: str = "docs/CODEMAP.md") -> Path:
    target = Path(root) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(render_codemap(scan(root), project).encode("utf-8"))
    return target


# ------------------------------------------------------------------ the running log

Summarizer = Callable[[str, str], Awaitable[str]]  # (previous checkpoint, entries to fold in) -> new checkpoint


def split_log(text: str) -> tuple[str, list[str]]:
    """(checkpoint text, entries). An entry is a '### ' section."""
    checkpoint = ""
    if CHECKPOINT_HEADING in text:
        after = text.split(CHECKPOINT_HEADING, 1)[1]
        checkpoint = re.split(r"\n(?=## (?!#))", after, maxsplit=1)[0].strip()
    entries = re.findall(rf"(?ms)^{ENTRY_PREFIX}.*?(?=^{ENTRY_PREFIX}|\Z)", text.split("## Log", 1)[1] if "## Log" in text else "")
    return checkpoint, [e.strip() for e in entries]


def render_log(checkpoint: str, entries: list[str], project: str = "") -> str:
    head = f"# Project memory{' — ' + project if project else ''}\n\nWhat the team did and decided, newest last. Read this before changing something that looks deliberate.\n\n"
    if checkpoint:
        head += f"{CHECKPOINT_HEADING}\n\n{checkpoint.strip()}\n\n"
    return head + "## Log\n\n" + "\n\n".join(entries) + ("\n" if entries else "")


def entry(title: str, lines: list[str], when: Optional[float] = None) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(when or time.time()))
    return f"{ENTRY_PREFIX}{stamp} {title}\n" + "\n".join(f"- {l}" for l in lines)


class ProjectLog:
    """docs/MEMORY.md. `budget` is the most characters the log may use before the oldest entries are folded into the checkpoint; `keep`
    entries (the newest) always stay verbatim."""

    def __init__(self, root: Path, project: str = "", path: str = "docs/MEMORY.md", budget: int = 12000, keep: int = 6) -> None:
        self.file, self.project, self.budget, self.keep = Path(root) / path, project, budget, keep

    def read(self) -> tuple[str, list[str]]:
        return split_log(self.file.read_text(encoding="utf-8")) if self.file.exists() else ("", [])

    def text(self) -> str:
        return self.file.read_text(encoding="utf-8") if self.file.exists() else ""

    async def add(self, title: str, lines: list[str], summarize: Optional[Summarizer] = None) -> None:
        checkpoint, entries = self.read()
        entries.append(entry(title, lines))
        text = render_log(checkpoint, entries, self.project)
        if len(text) > self.budget and len(entries) > self.keep:
            old, entries = entries[: -self.keep], entries[-self.keep:]
            folded = "\n\n".join(old)
            if summarize is not None:
                try:
                    new_checkpoint = (await summarize(checkpoint, folded)).strip()
                except Exception:  # noqa: BLE001 - losing a summary must not lose the log
                    new_checkpoint = ""
            else:
                new_checkpoint = ""
            checkpoint = new_checkpoint or _mechanical_checkpoint(checkpoint, old)
            text = render_log(checkpoint, entries, self.project)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_bytes(text.encode("utf-8"))


def _mechanical_checkpoint(previous: str, folded: list[str], limit: int = 3000) -> str:
    """Without a summarizer: keep each folded entry's title and first line, and drop the oldest lines past the limit."""
    lines = [l for l in previous.splitlines() if l.strip()]
    for e in folded:
        parts = e.splitlines()
        lines.append(parts[0].removeprefix(ENTRY_PREFIX) + (": " + parts[1].lstrip("- ").strip() if len(parts) > 1 else ""))
    text = "\n".join(f"- {l.lstrip('- ')}" for l in lines)
    while len(text) > limit and len(lines) > 1:
        lines.pop(0)
        text = "\n".join(f"- {l.lstrip('- ')}" for l in lines)
    return text


CHECKPOINT_PROMPT = """You maintain the long-term memory of a software project. Merge the previous checkpoint and the older log entries below into ONE updated checkpoint.

Keep: decisions and why they were made, constraints that must be respected, who owns which area, recurring problems and how they were solved, anything unfinished.
Drop: routine detail, anything superseded, timestamps. Write short bullet points grouped under these headings, nothing else: Decisions, Ownership, Problems and fixes, Open items. Maximum 40 lines.

PREVIOUS CHECKPOINT
{previous}

OLDER LOG ENTRIES
{entries}
"""


def relevant(text: str, query: str, limit: int = 3000) -> str:
    """The parts of a memory file most relevant to a query (its words), for putting in a prompt without the whole file."""
    words = {w for w in re.findall(r"[a-z0-9_]{3,}", query.lower())}
    if not text.strip() or not words:
        return text[:limit]
    blocks = re.split(r"\n(?=#{2,3} |- `)", text)
    scored = sorted(((sum(1 for w in words if w in b.lower()), i, b) for i, b in enumerate(blocks)), key=lambda t: (-t[0], t[1]))
    chosen = sorted([t for t in scored if t[0] > 0][:12], key=lambda t: t[1])
    out = ""
    for _, _, b in chosen:
        if len(out) + len(b) > limit:
            break
        out += b.strip() + "\n"
    return out or text[:limit]
