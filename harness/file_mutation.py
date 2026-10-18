"""Writing files (opencode: packages/core/src/file-mutation.ts).

Mutations of the same file are serialized by resolved path, so two tool calls in one step cannot interleave a read-modify-write.
Locking is process-local: it serializes cooperating changes; external writes can still race. A UTF-8 BOM that a file had is
kept, and at most one is ever written."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional

from harness.util import bom as Bom
from harness.util import fs

_locks: dict[str, asyncio.Lock] = {}  # shared across everything in the process that addresses the same file


@asynccontextmanager
async def with_lock(targets: list[str]) -> AsyncIterator[None]:
    """Hold the locks of every target, acquired in sorted order so two multi-file mutations cannot deadlock."""
    loop = id(asyncio.get_running_loop())  # a lock belongs to one event loop
    keys = sorted({str(fs.resolve(t)) for t in targets})
    held: list[asyncio.Lock] = []
    try:
        for k in keys:
            lock = _locks.setdefault(f"{loop}:{k}", asyncio.Lock())
            await lock.acquire()
            held.append(lock)
        yield
    finally:
        for lock in reversed(held):
            lock.release()


@dataclass
class WriteResult:
    operation: str
    target: str
    resource: str
    existed: bool


@dataclass
class ReadText:
    text: str
    bom: bool


class FileKindError(Exception):
    def __init__(self, path: str, actual: str) -> None:
        super().__init__(f"{path} is a {actual}")
        self.path, self.actual = path, actual


def read_text(target: str) -> ReadText:
    """Raises FileNotFoundError, or FileKindError when the path is a directory."""
    p = Path(target)
    if p.is_dir():
        raise FileKindError(target, "directory")
    split = Bom.decode_bytes(p.read_bytes())
    return ReadText(split.text, split.bom)


def sync_text_bom(target: str, bom: bool) -> str:
    text, replacement = Bom.sync_bytes(Path(target).read_bytes(), bom)
    if replacement is not None:
        Path(target).write_bytes(replacement)
    return text


def write(target: str, resource: str, content: str | bytes) -> WriteResult:
    p = Path(target)
    existed = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return WriteResult("write", target, resource, existed)


def write_text_preserving_bom(target: str, resource: str, content: str) -> WriteResult:
    p = Path(target)
    nxt = Bom.split(content)
    current: Optional[bytes] = None
    if p.is_dir():
        raise FileKindError(target, "directory")
    if p.exists():
        with open(p, "rb") as fh:
            current = fh.read(3)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(Bom.join(nxt.text, bool(current and Bom.has(current)) or nxt.bom).encode("utf-8"))
    return WriteResult("write", target, resource, current is not None)
