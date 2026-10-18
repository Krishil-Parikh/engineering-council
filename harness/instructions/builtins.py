"""Built-in instruction sources: the date and the environment (opencode: packages/core/src/instructions/builtins.ts)."""

from __future__ import annotations

import sys
from datetime import date
from typing import Callable

from harness.instructions import index as I
from harness.location import Location
from harness.util.global_paths import GlobalPaths


def load(location: Location, paths: GlobalPaths, today: Callable[[], date] = date.today) -> I.List:
    return I.combine([
        I.make(I.Definition(
            key="core/date",
            read=lambda: today().strftime("%a %b %d %Y"),
            render_initial=lambda d: f"Today's date: {d}",
            render_changed=lambda _p, d: f"Today's date is now: {d}",
        )),
        I.make(I.Definition(
            key="core/environment",
            read=lambda: "\n".join([
                "<env>",
                f"  Working directory: {location.directory}",
                f"  Workspace root folder: {location.project_directory}",
                f"  Is directory a git repo: {'yes' if location.vcs == 'git' else 'no'}",
                f"  Platform: {sys.platform}",
                f"  Prefer {paths.tmp} over generic system temporary directories such as /tmp; it is pre-created and approved for external access.",
                "</env>",
            ]),
            render_initial=lambda env: "\n".join(["Here is some useful information about the environment you are running in:", env]),
            render_changed=lambda _p, env: "\n".join(["The environment you are running in is now:", env]),
        )),
    ])
