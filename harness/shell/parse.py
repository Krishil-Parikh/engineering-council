"""Turning a command line into permission resources (opencode: packages/core/src/shell/parse.ts, the tree-sitter path).

Every simple command the line runs (including those inside substitutions, pipelines and lists) becomes a permission `resource` (its
source text, with any redirections) plus a `save` pattern ("<prefix> *", the prefix length coming from the arity table). `cd`-like
commands do not become commands: their arguments become `directories` that the caller checks against the project boundary.

Deviation: opencode also ships a PowerShell grammar and a hand-written "portable" scanner. We parse bash with tree-sitter-bash and
handle PowerShell with a conservative splitter (statement separators and whitespace outside quotes), which over-approximates the
commands that will run."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from harness.shell import select as Select
from harness.shell._arity import ARITY

CWD = {"cd", "chdir", "popd", "pushd", "push-location", "set-location"}
PREFIX_LENGTH = max(ARITY.values())
_POWERSHELL_PATH_FLAG = re.compile(r"^-(?:p(?:ath|at|a)?|lp|l(?:i(?:t(?:e(?:r(?:a(?:l(?:p(?:a(?:t(?:h)?)?)?)?)?)?)?)?)?)?|psp(?:a(?:t(?:h)?)?)?):?$", re.I)
_BASH_WORD_TYPES = {"command_name", "word", "string", "raw_string", "concatenation"}


@dataclass
class Result:
    commands: list[dict[str, str]] = field(default_factory=list)  # {"resource", "save"}
    directories: list[str] = field(default_factory=list)


class ScanError(Exception):
    pass


@lru_cache(maxsize=1)
def _bash_parser():
    import tree_sitter_bash
    import tree_sitter

    return tree_sitter.Parser(tree_sitter.Language(tree_sitter_bash.language()))


def prefix(tokens: list[str]) -> list[str]:
    for length in range(len(tokens), 0, -1):
        arity = ARITY.get(" ".join(tokens[:length]))
        if arity is not None:
            return tokens[:arity]
    return tokens[:1]


def _expand_known_directory(value: str) -> Optional[str]:
    # Unknown shell expressions cannot be resolved safely during permission analysis.
    if "$" in value or "`" in value or value.startswith("("):
        return None
    resolved = value.replace("\0", "$")
    if resolved == "~":
        return os.path.expanduser("~")
    if resolved.startswith("~/") or (os.name == "nt" and resolved.startswith("~\\")):
        return os.path.join(os.path.expanduser("~"), resolved[2:])
    return resolved


def _env(key: str) -> Optional[str]:
    if os.name != "nt":
        return os.environ.get(key)
    for k, v in os.environ.items():
        if k.lower() == key.lower():
            return v
    return None


def _directory_argument(value: str, powershell: bool, cwd: str, shell: str) -> Optional[str]:
    quote = value[:1]
    text = value[1:-1] if quote in ('"', "'") and value[-1:] == quote and len(value) >= 2 else value
    if not powershell:
        return _expand_known_directory(text)
    text = re.sub(r"\$\{env:([^}]+)\}", lambda m: _env(m.group(1)) or "", text, flags=re.I)
    text = re.sub(r"\$env:([A-Za-z_][A-Za-z0-9_]*)", lambda m: _env(m.group(1)) or "", text, flags=re.I)

    def auto(m: re.Match) -> str:
        key = (m.group(1) or m.group(2) or "").upper()
        return os.path.expanduser("~") if key == "HOME" else cwd if key == "PWD" else os.path.dirname(shell)

    text = re.sub(r"\$(?:\{(HOME|PWD|PSHOME)\}|(HOME|PWD|PSHOME)(?=$|[\\/]))", auto, text, flags=re.I)
    return _expand_known_directory(text)


def _directory_args(parts: list[tuple[str, str]], powershell: bool, cwd: str, shell: str) -> list[str]:
    if not powershell:
        return [d for d in (_directory_argument(t, False, cwd, shell) for _, t in parts[1:] if not t.startswith("-")) if d is not None]
    out: list[str] = []
    path = False
    end_of_parameters = False
    for kind, text in parts[1:]:
        if not end_of_parameters and text == "--":
            end_of_parameters = True
            continue
        if path:
            value = _directory_argument(text, True, cwd, shell)
            if value:
                out.append(value)
            path = False
            continue
        if not end_of_parameters and kind == "command_parameter":
            path = bool(_POWERSHELL_PATH_FLAG.match(text))
            continue
        value = _directory_argument(text, True, cwd, shell)
        if value:
            out.append(value)
    return out


def _walk_commands(node):
    if node.type == "command":
        yield node
    for child in node.children:
        yield from _walk_commands(child)


def _text(node) -> str:
    return node.text.decode("utf-8", "replace")


def scan_bash(command: str, shell: str, cwd: str) -> Result:
    tree = _bash_parser().parse(command.encode("utf-8"))
    result = Result()
    for node in _walk_commands(tree.root_node):
        parts = [("word", _text(c)) for c in node.children if c.type in _BASH_WORD_TYPES]
        tokens = [t for _, t in parts]
        if not tokens:
            continue
        if tokens[0] in CWD:
            result.directories.extend(_directory_args(parts, False, cwd, shell))
            continue
        owner = node.parent if node.parent is not None and node.parent.type == "redirected_statement" else node
        result.commands.append({"resource": _text(owner).strip(), "save": f"{' '.join(prefix(tokens))} *"})
    return result


def _split_powershell(command: str) -> list[str]:
    statements, buf, quote, i = [], [], "", 0
    while i < len(command):
        c = command[i]
        if quote:
            buf.append(c)
            if c == quote:
                quote = ""
        elif c in "'\"":
            quote = c
            buf.append(c)
        elif c in ";|\n" or command.startswith(("&&", "||"), i):
            statements.append("".join(buf))
            buf = []
            i += 1 if c in ";|\n" else 2
            continue
        else:
            buf.append(c)
        i += 1
    statements.append("".join(buf))
    return [s.strip() for s in statements if s.strip()]


def _tokens(statement: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r"""(?:[^\s'"]|'[^']*'|"[^"]*")+""", statement):
        text = m.group(0)
        out.append(("command_parameter" if re.match(r"^-[A-Za-z_?]", text) else "word", text))
    return out


def scan_powershell(command: str, shell: str, cwd: str) -> Result:
    result = Result()
    for statement in _split_powershell(command):
        parts = _tokens(statement)
        if not parts:
            continue
        name = parts[0][1].lower()
        if name in CWD:
            result.directories.extend(_directory_args(parts, True, cwd, shell))
            continue
        result.commands.append({"resource": statement, "save": f"{' '.join(prefix([t for _, t in parts][:PREFIX_LENGTH]))} *"})
    return result


def scan(command: str, shell: str, cwd: str) -> Result:
    """Raises ScanError when the line cannot be analysed."""
    try:
        if Select.ps(shell):
            return scan_powershell(command, shell, cwd)
        return scan_bash(command, shell, cwd)
    except Exception as exc:  # noqa: BLE001
        raise ScanError(f"Failed to parse shell command: {exc}") from exc
