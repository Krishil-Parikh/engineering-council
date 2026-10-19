"""What the gateway tells the terminal. Without this a stuck run and a working run look the same, so everything the team does is logged here: commands from the
browser, the phases, every stage of the meeting, the team's events, the questions waiting for you, and a heartbeat that says what a quiet run is waiting for."""

from __future__ import annotations

import logging
import logging.handlers
import sys
import time
from pathlib import Path
from typing import Any, Optional

NOISY = ("httpx", "httpcore", "grpc", "google", "urllib3", "asyncio", "watchfiles", "multipart", "a2a")


def setup_logging(level: str = "INFO", file: Optional[Path] = None) -> None:
    """Console (and a rotating file when given). Safe to call twice."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_gateway", False):
            root.removeHandler(handler)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)-18s %(message)s", "%H:%M:%S")
    try:  # a Windows console may not print every character a model writes; replace what it cannot show instead of failing
        sys.stderr.reconfigure(errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    console._gateway = True  # type: ignore[attr-defined]
    root.addHandler(console)
    if file is not None:
        file.parent.mkdir(parents=True, exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        rotating.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)-18s %(message)s"))
        rotating._gateway = True  # type: ignore[attr-defined]
        root.addHandler(rotating)
    chosen = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(chosen)
    for name in NOISY:  # their chatter is only useful when debugging them
        logging.getLogger(name).setLevel(logging.WARNING if chosen > logging.DEBUG else logging.INFO)


def one_line(text: Any, limit: int = 160) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def heartbeat_line(run: Any) -> Optional[tuple[int, str]]:
    """(level, text) describing a running workspace, or None when nothing is running. A long silence is a warning, and says what the run is waiting for."""
    if not getattr(run, "active", False):
        return None
    p = run.p
    quiet = time.monotonic() - getattr(p, "last_event_at", time.monotonic())
    working = [f"{a.get('name', a.get('id'))}: {one_line(a.get('activeTask'), 50)}" for a in p.agents.values()
               if a.get("status") in ("active", "speaking") and a.get("id") not in ("sme-01",)]
    waiting = [pending for pending in getattr(run.questions, "pending", {}).values()]
    base = f"{run.state} | phase {p.phase} | last activity {int(quiet)}s ago"
    if waiting:
        return logging.WARNING, f"WAITING FOR YOU ({len(waiting)} decision{'s' if len(waiting) != 1 else ''}) - answer it in the browser | {base}"
    detail = f" | working: {'; '.join(working[:4])}" if working else ""
    if quiet > 180:
        return logging.WARNING, f"no activity for {int(quiet)}s - the model may be slow or the run stuck | {base}{detail}"
    return logging.INFO, f"still running | {base}{detail}"
