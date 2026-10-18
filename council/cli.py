"""`python -m council ...`: `run` for the whole pipeline, meetings by default, `build` for agent mode. Each module also has its own entry point."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "run":
        from council.pipeline import run

        return run(argv[1:])
    if argv and argv[0] == "build":
        from team.cli import build

        return build(argv)
    from meetings.cli import main as meetings_main

    return meetings_main(argv)


if __name__ == "__main__":
    sys.exit(main())
