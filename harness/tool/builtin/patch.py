"""The patch tool (opencode: tool/plugin/patch.ts). Verifies every hunk first, asks one permission for all files, then applies in order.

Deviations: no formatter pass (the formatter hook was dropped). opencode swaps patch for edit/write on gpt-* models; `use_patch` exposes
that decision so the harness facade can pick one set of tools per model."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field

from harness import file_mutation as FM
from harness.file_access import Target, resolve_path
from harness.permission import BlockedError, CorrectedError, DeclinedError
from harness.tool.builtin.deps import ToolDeps
from harness.tool.file_diff import FileDiff, file_diff
from harness.tool.info import ToolContext, ToolError, ToolInfo, ToolOptions, ToolResult
from harness.util import bom as Bom
from harness.util import patch as P

PermissionError_ = (DeclinedError, CorrectedError, BlockedError)
NAME = "patch"
DESCRIPTION = """Use the `patch` tool to edit files. Your patch language is a stripped‑down, file‑oriented diff format designed to be easy to parse and safe to apply. You can think of it as a high‑level envelope:

*** Begin Patch
[ one or more file sections ]
*** End Patch

Within that envelope, you get a sequence of file operations.
You MUST include a header to specify the action you are taking.
Each operation starts with one of three headers:

*** Add File: <path> - create a new file. Every following line is a + line (the initial contents).
*** Delete File: <path> - remove an existing file. Nothing follows.
*** Update File: <path> - patch an existing file in place (optionally with a rename).

Example patch:

```
*** Begin Patch
*** Add File: hello.txt
+Hello world
*** Update File: src/app.py
*** Move to: src/main.py
@@ def greet():
-print("Hi")
+print("Hello, world!")
*** Delete File: obsolete.txt
*** End Patch
```

It is important to remember:

- You must include a header with your intended action (Add/Delete/Update)
- You must prefix new lines with `+` even when creating a new file
"""


class Input(BaseModel):
    patchText: str = Field(description="The full patch text describing add, update, and delete operations")


def use_patch(model_id: str) -> bool:
    return "gpt-" in model_id and "oss" not in model_id and "gpt-4" not in model_id


@dataclass
class Prepared:
    hunk: P.Hunk
    target: Target
    before: str
    after: str
    content: str = ""
    move_target: Optional[Target] = None


def _message(exc: BaseException) -> str:
    if isinstance(exc, FileNotFoundError):
        return "file does not exist"
    if isinstance(exc, FM.FileKindError):
        return "path is a directory" if exc.actual == "directory" else f"path is {exc.actual}"
    return str(exc)


def _trim_diff(diff: str) -> str:
    lines = diff.split("\n")

    def is_content(l: str) -> bool:
        return l[:1] in ("+", "-", " ") and not l.startswith(("---", "+++"))

    content = [l for l in lines if is_content(l)]
    if not content:
        return diff
    indent: Optional[int] = None
    for l in content:
        value = l[1:]
        if value.strip():
            n = len(value) - len(value.lstrip())
            indent = n if indent is None else min(indent, n)
    if not indent:
        return diff
    return "\n".join(l[0] + l[1 + indent :] if is_content(l) else l for l in lines)


def _patch_file(change: Prepared, after: Optional[str] = None) -> FileDiff:
    hunk = change.hunk
    resource = (change.move_target.resource if change.move_target else None) or change.target.resource
    status = "added" if hunk.type == "add" else "deleted" if hunk.type == "delete" else "modified"
    diff = file_diff(change.target.absolute, change.before, change.after if after is None else after, status)
    diff.file = resource
    diff.patch = _trim_diff(diff.patch)
    return diff


def to_model_content(applied: list[dict]) -> str:
    return "\n".join(["Success. Updated the following files:"] + [f"{'A' if a['type'] == 'add' else 'D' if a['type'] == 'delete' else 'M'} {a['resource']}" for a in applied])


def make(deps: ToolDeps) -> ToolInfo:
    async def execute(inp: Input, ctx: ToolContext) -> ToolResult:
        applied: list[dict] = []
        try:
            parsed: Optional[list[P.Hunk]] = P.parse(inp.patchText)
            parse_error: Optional[P.ParseError] = None
        except P.ParseError as exc:
            parsed, parse_error = None, exc
        lock_targets = []
        for h in parsed or []:
            lock_targets.append(resolve_path(deps.location.directory, h.path))
            if h.type == "update" and h.move_path:
                lock_targets.append(resolve_path(deps.location.directory, h.move_path))

        def fail(operation: str, exc: BaseException) -> ToolError:
            done = ", ".join(a["resource"] for a in applied)
            return ToolError(f"{operation}: {_message(exc)}" + (f". Completed before failure: {done}" if done else ""))

        async with FM.with_lock(lock_targets):
            if not inp.patchText:
                raise ToolError("patchText is required")
            if parse_error is not None:
                raise ToolError(f"patch verification failed: {parse_error}")
            hunks = parsed or []
            if not hunks:
                raise ToolError("patch rejected: empty patch")
            prepared: list[Prepared] = []
            updates: dict[str, str] = {}

            async def resolve_target(value: str) -> Target:
                target = deps.access.resolve(value, "file")
                if target.external_directory:
                    await deps.access.authorize_external([target], deps.invocation(ctx), {"filepath": target.absolute, "parentDir": target.external_directory.directory})
                return target

            for hunk in hunks:
                try:
                    target = await resolve_target(hunk.path)
                    if hunk.type == "add":
                        content = hunk.contents if hunk.contents.endswith("\n") or hunk.contents == "" else hunk.contents + "\n"
                        prepared.append(Prepared(hunk, target, "", Bom.split(content).text, content))
                        continue
                    if hunk.type in ("delete", "update") and os.path.exists(target.absolute):
                        deps.file_time.check(ctx.session_id, target.absolute, target.resource)
                    if hunk.type == "delete":
                        try:
                            current = FM.read_text(target.absolute)
                        except (OSError, FM.FileKindError) as exc:
                            raise ToolError(f"patch verification failed: Failed to delete {target.resource}: {_message(exc)}") from None
                        prepared.append(Prepared(hunk, target, current.text, ""))
                        continue
                    original = updates.get(target.absolute)
                    if original is None:
                        try:
                            current = FM.read_text(target.absolute)
                        except (OSError, FM.FileKindError) as exc:
                            raise ToolError(f"patch verification failed: Failed to read file to update {target.absolute}: {_message(exc)}") from None
                        original = Bom.join(current.text, current.bom)
                    before = Bom.split(original).text
                    try:
                        update = P.derive(hunk.path, hunk.chunks, original)
                    except ValueError as exc:
                        raise ToolError(f"patch verification failed: {exc}") from None
                    move_target = await resolve_target(hunk.move_path) if hunk.move_path else None
                    joined = P.join_bom(update.content, update.bom)
                    prepared.append(Prepared(hunk, target, before, update.content, joined, move_target))
                    if not move_target:
                        updates[target.absolute] = joined
                except (ToolError, *PermissionError_):
                    raise
                except Exception as exc:  # noqa: BLE001
                    raise ToolError(f"Unable to prepare patch at {hunk.path}", exc) from None

            files = [_patch_file(c) for c in prepared]
            targets = [t for c in prepared for t in ([c.target] + ([c.move_target] if c.move_target else []))]
            resources = list(dict.fromkeys(t.resource for t in targets))
            await deps.assert_permission(
                ctx, "edit", resources, save=["*"],
                metadata={"filepath": ", ".join(t.resource for t in targets), "diff": "".join(f.patch + "\n" for f in files), "files": [f.to_json() for f in files]},
            )

            for change in prepared:
                hunk = change.hunk
                if hunk.type == "delete":
                    try:
                        os.remove(change.target.absolute)
                    except OSError as exc:
                        raise fail(f"Failed to delete {change.target.resource}", exc) from None
                    applied.append({"type": "delete", "resource": change.target.resource, "target": change.target.absolute})
                elif hunk.type == "update" and change.move_target:
                    mt = change.move_target
                    try:
                        FM.write(mt.absolute, mt.resource, change.content)
                    except OSError as exc:
                        raise fail(f"Failed to write {mt.resource}", exc) from None
                    if os.path.abspath(mt.absolute) != os.path.abspath(change.target.absolute):
                        try:
                            os.remove(change.target.absolute)
                        except OSError as exc:
                            raise fail(f"Wrote {mt.resource} but failed to remove {change.target.resource}", exc) from None
                    applied.append({"type": "update", "resource": mt.resource, "target": mt.absolute})
                else:
                    try:
                        FM.write(change.target.absolute, change.target.resource, change.content)
                    except OSError as exc:
                        raise fail(f"Failed to write {change.target.resource}", exc) from None
                    applied.append({"type": hunk.type, "resource": change.target.resource, "target": change.target.absolute})

            for item in applied:
                if item["type"] != "delete":
                    deps.file_time.record(ctx.session_id, item["target"])
            final_files = []
            for change in prepared:
                if change.hunk.type == "delete":
                    final_files.append(_patch_file(change))
                    continue
                t = change.move_target or change.target
                final_files.append(_patch_file(change, FM.read_text(t.absolute).text))
        output = {"applied": applied, "files": [f.to_json() for f in final_files]}
        return ToolResult(content=to_model_content(applied), output=output, metadata={"files": output["files"]})

    return ToolInfo(NAME, DESCRIPTION, Input, execute, ToolOptions(permission="edit"))
