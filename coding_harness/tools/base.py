"""The tool contract: a name, a JSON schema, one async `run`, and a context carrying everything a tool may touch."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from coding_harness.permission import PermissionDenied, Permissions, Rule, Ruleset
from coding_harness.types import ToolResult, ToolSpec
from coding_harness.workspace import Workspace

if TYPE_CHECKING:  # pragma: no cover
    from coding_harness.jobs import JobManager
    from coding_harness.session import Session

MAX_LINES = 2000
MAX_BYTES = 50 * 1024


class ToolFailure(Exception):
    """An expected failure the model should read and react to (bad path, no match, declined)."""


class FileTime:
    """Remembers the modification time of every file the agent read so an edit never overwrites changes it has not seen."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def record(self, path: Path) -> None:
        try:
            self._seen[str(path)] = path.stat().st_mtime_ns
        except OSError:
            pass

    def was_read(self, path: Path) -> bool:
        return str(path) in self._seen

    def assert_fresh(self, path: Path) -> None:
        if not path.exists():
            return
        seen = self._seen.get(str(path))
        if seen is None:
            raise ToolFailure(f"You must read {path.name} with the read tool before changing it.")
        if path.stat().st_mtime_ns != seen:
            raise ToolFailure(f"{path.name} changed on disk since you last read it. Read it again before changing it.")


@dataclass
class ToolContext:
    session_id: str
    agent: str
    call_id: str
    workspace: Workspace
    cwd: Path
    permissions: Permissions
    rules: Ruleset
    file_time: FileTime
    jobs: "JobManager"
    session: "Session"
    spawn: Callable[..., Any] | None = None  # (agent, prompt, description, session_id, background) -> dict
    ask_user: Callable[[list[dict[str, Any]]], Any] | None = None
    emit: Callable[[str, dict[str, Any]], None] = lambda kind, data: None
    path_locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)  # extra environment for spawned commands (e.g. a git identity)

    async def permit(self, action: str, resources: list[str], save: list[str] | None = None, metadata: dict[str, Any] | None = None) -> None:
        try:
            await self.permissions.assert_(action, resources, self.rules, save=save, metadata=metadata)
        except PermissionDenied as exc:
            raise ToolFailure(str(exc)) from None

    async def authorize_path(self, path: Path, kind: str = "file") -> None:
        """Paths outside the project (and its scratch directory) need an explicit external_directory approval."""
        if self.workspace.inside(path):
            return
        base = path if kind == "directory" else path.parent
        await self.permit("external_directory", [f"{base.as_posix()}/*"], save=[f"{base.as_posix()}/*"])

    def lock_for(self, path: Path) -> asyncio.Lock:
        return self.path_locks.setdefault(str(path), asyncio.Lock())


class Tool:
    name = ""
    permission = ""  # rule action this tool is gated by (defaults to its name); "" = ungated
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    def description(self, ctx: Any = None) -> str:
        return ""

    def spec(self, ctx: Any = None) -> ToolSpec:
        return ToolSpec(self.name, self.description(ctx), self.parameters)

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:  # pragma: no cover - abstract
        raise NotImplementedError


_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


def validate_args(args: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Light JSON-schema check: required keys and primitive types, with the common string->number/bool coercions."""
    props = schema.get("properties", {})
    out = dict(args)
    problems: list[str] = []
    for key in schema.get("required", []):
        if key not in out or out[key] is None:
            problems.append(f"missing required argument '{key}'")
    for key, val in list(out.items()):
        spec = props.get(key)
        if spec is None:
            out.pop(key)  # unknown arguments are ignored rather than failing the call
            continue
        want = spec.get("type")
        if want in ("integer", "number") and isinstance(val, str):
            try:
                out[key] = int(val) if want == "integer" else float(val)
            except ValueError:
                pass
        if want == "boolean" and isinstance(val, str) and val.lower() in ("true", "false"):
            out[key] = val.lower() == "true"
        if want in _TYPES and not isinstance(out[key], _TYPES[want]) or (want in ("integer", "number") and isinstance(out[key], bool)):
            problems.append(f"argument '{key}' must be {want}")
    if problems:
        raise ToolFailure("Invalid arguments: " + "; ".join(problems))
    return out


def clip_lines(text: str, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES, tail: bool = False) -> tuple[str, bool]:
    lines = text.split("\n")
    over = len(lines) > max_lines or len(text.encode("utf-8", "ignore")) > max_bytes
    if not over:
        return text, False
    chosen = lines[-max_lines:] if tail else lines[:max_lines]
    kept: list[str] = []
    size = 0
    for line in (reversed(chosen) if tail else chosen):
        size += len(line.encode("utf-8", "ignore")) + 1
        if size > max_bytes:
            break
        kept.append(line)
    if tail:
        kept.reverse()
    return "\n".join(kept), True


def truncate_result(result: ToolResult, out_dir: Path, hint: str) -> ToolResult:
    """Bound what goes back to the model. The complete output is saved to a file the agent can grep or read in parts."""
    if result.metadata.get("truncated") is not None:
        return result
    kept, cut = clip_lines(result.output)
    if not cut:
        result.metadata["truncated"] = False
        return result
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"tool_{os.urandom(6).hex()}.txt"
    path.write_text(result.output, encoding="utf-8")
    result.output = f"{kept}\n\n...output truncated ({len(result.output.splitlines())} lines). Full output saved to: {path}\n{hint}"
    result.metadata.update(truncated=True, output_file=str(path))
    return result


def default_rules() -> Ruleset:
    return [Rule("*", "*", "allow")]
