"""Noticing that a file changed under the agent (opencode: file/time.ts).

When a session reads or writes a file, the file's modification time is remembered for that session. Before the session edits or overwrites
the file, the remembered time is compared with the file's current time: if something else changed the file in between (another process, a
git checkout or rebase, a teammate's merge), the edit is refused with a message asking the model to read the file again, instead of
silently applying a change that was made against text that no longer exists.

A file the session never read is not refused: the edit tool's exact-match requirement already protects those, and creating a file needs
no earlier read. Only the history of this session counts, so one session's reads never excuse another's."""

from __future__ import annotations

import os
import time
from typing import Optional

from harness.tool.info import ToolError


def _stamp(path: str) -> Optional[tuple[int, int]]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _when(ns: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ns / 1e9))


class FileTime:
    def __init__(self) -> None:
        self._seen: dict[tuple[str, str], tuple[int, int]] = {}

    @staticmethod
    def _key(session_id: str, path: str) -> tuple[str, str]:
        return session_id, os.path.normcase(os.path.abspath(path))

    def record(self, session_id: str, path: str) -> None:
        """The session has just read or written this file."""
        stamp = _stamp(path)
        if stamp is not None:
            self._seen[self._key(session_id, path)] = stamp

    def check(self, session_id: str, path: str, shown: Optional[str] = None) -> None:
        """Raises ToolError when the file has changed since this session last read or wrote it."""
        before = self._seen.get(self._key(session_id, path))
        now = _stamp(path)
        if before is None or now is None or before == now:
            return
        raise ToolError(
            f"{shown or path} has been modified since it was last read (last read: {_when(before[0])}, now: {_when(now[0])}).\n\n"
            "Read the file again before modifying it, so your change is made against what is there now."
        )

    def forget(self, session_id: str) -> None:
        for key in [k for k in self._seen if k[0] == session_id]:
            del self._seen[key]
