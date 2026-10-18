"""Finding configuration (opencode: packages/core/src/config/discovery.ts, without the managed/MDM sources).

Project configuration lives in the directories from the working directory up to the filesystem root: `.harness/`, plus `.claude/`
and `.agents/` for skills compatibility, and `harness.json(c)` files. The global configuration directory and `~/.claude`,
`~/.agents` are separate roots that must not re-enter through the project walk."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from harness.location import Location
from harness.util import fs
from harness.util.global_paths import GlobalPaths

NAMES = ["harness.json", "harness.jsonc"]
PROJECT_DIR = ".harness"
COMPAT_DIRS = (".claude", ".agents")


@dataclass
class Options:
    project: bool = True  # false skips the working-directory walk
    global_: bool = True  # false skips the global directory, ~/.claude and ~/.agents
    claude: bool = True  # false skips ~/.claude and project .claude directories
    file: Optional[str] = None  # an explicit config file
    content: Optional[str] = None  # inline config text


@dataclass
class Sources:
    global_: Optional[Path]
    explicit: Optional[Path]
    direct: list[Path] = field(default_factory=list)  # harness.json(c) files found in project directories, lowest priority first
    project: list[tuple[Path, bool]] = field(default_factory=list)  # (.harness directory, exists)
    claude: list[Path] = field(default_factory=list)
    agents: list[Path] = field(default_factory=list)


def discover(location: Location, paths: GlobalPaths, options: Optional[Options] = None) -> Sources:
    options = options or Options()
    global_dir = paths.config
    global_agents = paths.home / ".agents"
    global_claude = paths.home / ".claude"
    config_directories = [global_dir]
    global_roots = [fs.resolve(p) for p in [*config_directories, global_claude, global_agents]]
    current = fs.resolve(location.directory)
    if fs.resolve(global_dir) == current or not options.project:
        directories: list[Path] = []
    else:
        # Unlike opencode (which walks to the filesystem root) the walk stops at the user's home when the project is inside it.
        home = fs.resolve(paths.home)
        directories = fs.up(["."], location.directory, stop=home if fs.contains(home, current) else None)
    discovered: list[tuple[Path, Path]] = []  # (as spelled, resolved)
    for directory in directories:
        parent = fs.resolve(directory)
        for name in [*COMPAT_DIRS, PROJECT_DIR, *reversed(NAMES)]:
            discovered.append((directory / name, fs.resolve(parent / name)))

    global_enabled = options.global_
    global_files = [fs.resolve(global_dir / n) for n in NAMES]
    if global_enabled:
        visible = [item for item, resolved in discovered if resolved not in global_roots and resolved not in global_files]
    else:
        visible = [item for item, resolved in discovered if not any(resolved == r or fs.contains(r, resolved) for r in global_roots)]

    special = {PROJECT_DIR, *COMPAT_DIRS}
    return Sources(
        global_=global_dir if global_enabled else None,
        explicit=Path(options.file).resolve() if options.file else None,
        direct=[p for p in reversed(visible) if p.name not in special],
        project=[(p, p.is_dir()) for p in reversed([p for p in visible if p.name == PROJECT_DIR])],
        claude=[] if not options.claude else list(dict.fromkeys([*([global_claude] if global_enabled else []), *reversed([p for p in visible if p.name == ".claude"])])),
        agents=list(dict.fromkeys([*([global_agents] if global_enabled else []), *reversed([p for p in visible if p.name == ".agents"])])),
    )
