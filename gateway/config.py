"""Gateway settings, from the environment (and `python -m gateway` flags)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173", "http://127.0.0.1:5173")


@dataclass
class GatewaySettings:
    host: str = "127.0.0.1"
    port: int = 8000
    workspace_id: str = "workspace-demo"  # the workspace the frontend loads (VITE_WORKSPACE_ID)
    output_dir: Path = field(default_factory=lambda: Path("output"))  # where meetings and builds go: the same folder the terminal uses
    data_dir: Path = field(default_factory=lambda: Path(".gateway"))  # the event log that rebuilds a workspace after a restart
    token: Optional[str] = None  # when set, every request must present it (Bearer header, or ?token= for the event stream)
    cors_origins: tuple[str, ...] = DEFAULT_ORIGINS
    static_dir: Optional[Path] = None  # the built frontend, served from /
    repo: Optional[str] = None  # a repository to build on and publish to, when the brief does not name one
    a2a: bool = True  # the developers talk over A2A (always, outside tests)
    memory: bool = True  # cross-project memory
    unattended: bool = False  # approve every decision automatically (tests only)
    repair_rounds: int = 2  # rounds the team may spend fixing failing verification before the final branch
    rate_per_minute: int = 120  # commands per workspace
    heartbeat_seconds: float = 20.0  # how often a running workspace says what it is doing (0 = never)
    replay_window: int = 200  # recent events a new stream subscriber is replayed

    def __post_init__(self) -> None:
        # git commands run from other folders (the team's clone, the sandboxes), so every path handed to them must be absolute
        self.output_dir = Path(self.output_dir).expanduser().resolve()
        self.data_dir = Path(self.data_dir).expanduser().resolve()

    @staticmethod
    def from_env() -> "GatewaySettings":
        env = os.environ
        origins = tuple(o.strip() for o in env.get("GATEWAY_CORS_ORIGINS", "").split(",") if o.strip()) or DEFAULT_ORIGINS
        static = env.get("GATEWAY_STATIC")
        return GatewaySettings(
            host=env.get("GATEWAY_HOST", "127.0.0.1"), port=int(env.get("GATEWAY_PORT", "8000")), workspace_id=env.get("VITE_WORKSPACE_ID", "workspace-demo"),
            output_dir=Path(env.get("GATEWAY_OUTPUT", "output")), data_dir=Path(env.get("GATEWAY_DATA", ".gateway")), token=env.get("GATEWAY_TOKEN") or None,
            cors_origins=origins, static_dir=Path(static) if static else None, repo=env.get("GATEWAY_REPO") or None,
        )
