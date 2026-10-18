"""Bounding tool output (opencode: packages/core/src/tool-output.ts).

A tool result longer than 2000 lines or 50 KiB is cut; the complete text is written to a file the agent can search or read in
parts. Files are removed after seven days."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from harness.schema.message import TextContent
from harness.tool.registry import NormalizedResult

MAX_LINES = 2_000
MAX_BYTES = 50 * 1024
RETENTION_SECONDS = 7 * 24 * 3600
DIRECTORY = "tool-output"


def file_name() -> str:
    return "tool_" + f"{int(time.time() * 1000):012x}" + os.urandom(3).hex()


@dataclass
class ToolOutput:
    directory: Path
    max_lines: int = MAX_LINES
    max_bytes: int = MAX_BYTES

    def truncate(self, result: NormalizedResult) -> NormalizedResult:
        if result.metadata and result.metadata.get("truncated") is not None:
            return result
        text = "\n".join(c.text for c in result.content if isinstance(c, TextContent))
        lines = text.split("\n")
        if text.endswith("\n"):
            lines.pop()
        total_bytes = len(text.encode("utf-8"))
        if len(lines) <= self.max_lines and total_bytes <= self.max_bytes:
            return NormalizedResult(result.content, result.output, {**(result.metadata or {}), "truncated": False})

        kept: list[str] = []
        used = 0
        for line in lines[: self.max_lines]:
            size = len(line.encode("utf-8")) + (1 if kept else 0)
            if used + size > self.max_bytes:
                break
            kept.append(line)
            used += size
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / file_name()
        path.write_text(text, encoding="utf-8")
        shown = f"lines 1-{len(kept)}" if kept else "0 lines"
        marker = f"[showing {shown} of {len(lines)}; full output saved to {path}]"
        bounded = []
        remaining = len("\n".join(kept))
        seen_text = marked = False
        for item in result.content:
            if not isinstance(item, TextContent):
                bounded.append(item)
                continue
            if seen_text and remaining > 0:
                remaining -= 1
            seen_text = True
            if remaining >= len(item.text):
                bounded.append(item)
                remaining -= len(item.text)
                continue
            if remaining > 0:
                bounded.append(TextContent(text=item.text[:remaining]))
            if not marked:
                bounded.append(TextContent(text=marker))
            remaining = 0
            marked = True
        if not marked:
            bounded.append(TextContent(text=marker))
        return NormalizedResult(bounded, result.output, {**(result.metadata or {}), "truncated": True, "outputPath": str(path)})

    def cleanup(self, now: Optional[float] = None) -> int:
        cutoff = (now or time.time()) - RETENTION_SECONDS
        removed = 0
        if not self.directory.is_dir():
            return 0
        for p in self.directory.iterdir():
            if p.name.startswith("tool_") and p.is_file() and p.stat().st_mtime < cutoff:
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed
