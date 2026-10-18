"""UTF-8 byte-order marks (opencode: packages/util/src/bom.ts). A BOM is kept when a file had one and never doubled."""

from __future__ import annotations

import re
from typing import NamedTuple, Optional

BOM = "﻿"


class Split(NamedTuple):
    bom: bool
    text: str


def split(text: str) -> Split:
    stripped = re.sub(r"^﻿+", "", text)
    return Split(len(stripped) != len(text), stripped)


def join(text: str, bom: bool) -> str:
    stripped = split(text).text
    return BOM + stripped if bom else stripped


def has(content: bytes) -> bool:
    return content[:3] == b"\xef\xbb\xbf"


def decode_bytes(content: bytes) -> Split:
    return split(content.decode("utf-8", errors="replace"))


def sync_bytes(content: bytes, bom: bool) -> tuple[str, Optional[bytes]]:
    """(text, replacement bytes or None when the file already has the canonical BOM state)."""
    decoded = content.decode("utf-8", errors="replace")
    current = split(decoded)
    canonical = BOM + current.text if bom else current.text
    return current.text, (None if decoded == canonical else canonical.encode("utf-8"))
