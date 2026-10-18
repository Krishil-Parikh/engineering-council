"""Command line for agent mode: the developers build the project from a finished meeting."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from meetings.config import load_settings
from team.engine import TeamConfig, TeamEngine
from team.events import describe, describe_talk


def printer(verbose: bool):
    """Plain text progress. Conversations only with --verbose; task-by-task lines too."""

    def show(kind: str, data: dict) -> None:
        if kind == "talk":
            if verbose:
                print(describe_talk(data)[1])
            return
        shown = describe(kind, data)
        if shown is None or (kind == "task" and not verbose):
            return
        style, text = shown
        print(("\n" if kind in ("plan", "feature-started", "final") else "") + text)

    return show


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def build(argv: list[str]) -> int:
    """`build <meeting dir>`: the developers implement the specification in parallel, each in their own clone."""
    p = argparse.ArgumentParser(prog="python -m council build", description="Developers implement the specification on feature branches; you merge the result.")
    p.add_argument("directory", help="a finished meeting output directory")
    p.add_argument("--repo", help="an existing repository to build on (its current state, uncommitted work included, is the starting point); default: a new empty project")
    p.add_argument("--workdir", help="where the team's remote and clones live (default: <dir>/team)")
    p.add_argument("--max-parallel", type=int, default=6, help="most features worked on at the same time")
    p.add_argument("--run-id", help="name this run (default: a timestamp); reuse a run id to resume")
    p.add_argument("--repair-rounds", type=int, default=2, help="repair rounds when the verification commands fail")
    p.add_argument("--publish", nargs="?", const="source", metavar="TARGET", help="push the finished branches to TARGET (a URL or path); with no value, to the repository given by --repo. Never main")
    p.add_argument("--publish-all", action="store_true", help="with --publish: also push the integration and every feature branch")
    p.add_argument("--pr", action="store_true", help="with --publish: open a pull request for the final branch (needs the GitHub CLI); you still do the merging")
    p.add_argument("--max-llm", type=int, default=4, help="model requests in flight at once, shared by all developers (lower it on a free tier)")
    p.add_argument("--git-fix-rounds", type=int, default=2, help="how many times a failed git step is diagnosed and fixed before the feature gives up")
    p.add_argument("--plain", action="store_true", help="plain text progress instead of the full-screen view")
    p.add_argument("--memory-dir", help="where cross-project memory lives (default: $COUNCIL_MEMORY_DIR or ~/.council/memory)")
    p.add_argument("--no-memory", action="store_true", help="neither use nor update cross-project memory")
    p.add_argument("--verbose", "-v", action="store_true", help="plain output: also show the conversations and each task")
    args = p.parse_args(argv[1:])
    settings = load_settings()
    memory_dir = None if args.no_memory else Path(args.memory_dir or os.environ.get("COUNCIL_MEMORY_DIR") or Path.home() / ".council" / "memory")
    config = TeamConfig(
        max_parallel=args.max_parallel, repair_rounds=args.repair_rounds, memory_dir=memory_dir, publish=args.publish, publish_all=args.publish_all,
        pull_request=args.pr, max_llm_concurrency=args.max_llm, git_fix_rounds=args.git_fix_rounds,
    )
    if args.run_id:
        config.run_id = args.run_id
    meeting = Path(args.directory)
    workdir = Path(args.workdir) if args.workdir else meeting / "team"

    def make_engine(on_event):
        return TeamEngine(meeting, workdir, api_key=settings.api_key, model=settings.model, source=Path(args.repo) if args.repo else None, config=config, on_event=on_event)

    if not args.plain and _interactive():
        from team.tui import run_team_tui

        app = run_team_tui(make_engine, meeting.name)
        engine, result = app.engine, app.result
        if result is None:
            print(f"The build did not finish{': ' + app.error if app.error else ' (stopped)'}. Finished work is in the branches under {workdir / 'remote' / 'origin.git'}; run again with the same --run-id to resume.")
            return 2
    else:
        engine = make_engine(printer(args.verbose))
        result = asyncio.run(engine.run())
    merged = sum(1 for f in result.features if f.status == "merged")
    print(f"\n{merged}/{len(result.features)} features merged. Verification: {'PASSED' if result.passed else 'not verified'}.")
    if result.lessons_learned:
        print(f"Learned {result.lessons_learned} lesson(s) for next time (memory: {memory_dir}).")
    if result.published_to:
        print(f"Published to {result.published_to}." + (f" Pull request: {result.pull_request_url}" if result.pull_request_url else ""))
    print(f"Review branch {result.final_branch} in {engine.repo.origin} and merge it into {engine.repo.main} yourself. Report: {meeting / 'team_report.md'}")
    for w in result.warnings:
        print(f"  ! {w}")
    return 0 if result.passed else 2
