"""Command line for agent mode: the developers build the project from a finished meeting.

By default the build runs as sprints (see team/agile): the documents are put in front of the human for approval first, then the team plans a
sprint, works in days, meets for standups, reviews, reports and looks back, and the human can interrupt at any time. In the full-screen view
that is the `i` key; in plain mode decisions are asked at the prompt."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from meetings.config import load_settings
from team.agile.ceremonies import AgileConfig
from team.engine import TeamConfig, TeamEngine
from team.events import describe, describe_talk


def printer(verbose: bool, ask: Optional[Any] = None):
    """Plain text progress. Conversations only with --verbose; task-by-task lines too. `ask(event_data)` is told when a decision needs the human."""

    def show(kind: str, data: dict) -> None:
        if kind == "approval-requested" and ask is not None:
            ask(data)
        if kind == "talk":
            if verbose:
                print(describe_talk(data)[1])
            return
        shown = describe(kind, data)
        if shown is None or (kind == "task" and not verbose):
            return
        style, text = shown
        print(("\n" if kind in ("plan", "feature-started", "final") else "") + text, flush=True)

    return show


def use_github_credentials() -> bool:
    """Private repositories need credentials for every git command that reaches GitHub (the clone here, the push at the end). If the GitHub CLI is
    signed in, its credentials are used for github.com for this process; nothing is written to any git configuration. Returns whether it was set up."""
    if shutil.which("gh") is None or subprocess.run(["gh", "auth", "status"], capture_output=True).returncode != 0:
        return False
    key = "credential.https://github.com.helper"
    # git reads these `'key=value'` pairs from the environment; an empty value first resets the helper list for github.com, so the GitHub CLI's
    # account is the one used (an environment variable cannot be empty on Windows, which is why this older form is used instead of GIT_CONFIG_KEY_n)
    extra = f"'{key}=' '{key}=!gh auth git-credential'"
    os.environ["GIT_CONFIG_PARAMETERS"] = f"{os.environ['GIT_CONFIG_PARAMETERS']} {extra}" if os.environ.get("GIT_CONFIG_PARAMETERS") else extra
    return True


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def add_build_arguments(p: argparse.ArgumentParser, skip: frozenset[str] = frozenset()) -> None:
    """The flags of a build. `skip` leaves out flags the caller already defines (the combined `run` command shares --repo, --plain and --verbose)."""

    def add(*names: str, **kw: Any) -> None:
        if not (set(names) & skip):
            p.add_argument(*names, **kw)

    add("--repo", help="an existing repository to build on (its current state, uncommitted work included, is the starting point); default: a new empty project")
    add("--workdir", help="where the team's remote and clones live (default: <dir>/team)")
    add("--max-parallel", type=int, default=6, help="most features worked on at the same time")
    add("--run-id", help="name this run (default: a timestamp); reuse a run id to resume")
    add("--repair-rounds", type=int, default=2, help="repair rounds when the verification commands fail")
    add("--publish", nargs="?", const="source", metavar="TARGET", help="push the finished branches to TARGET (a URL or path); with no value, to the repository given by --repo. Never main")
    add("--publish-all", action="store_true", help="with --publish: also push the integration and every feature branch")
    add("--pr", action="store_true", help="with --publish: open a pull request for the final branch (needs the GitHub CLI); you still do the merging")
    add("--max-llm", type=int, default=4, help="model requests in flight at once, shared by all developers (lower it on a free tier)")
    add("--git-fix-rounds", type=int, default=2, help="how many times a failed git step is diagnosed and fixed before the feature gives up")
    add("--plain", action="store_true", help="plain text progress instead of the full-screen view")
    add("--memory-dir", help="where cross-project memory lives (default: $COUNCIL_MEMORY_DIR or ~/.council/memory)")
    add("--no-memory", action="store_true", help="neither use nor update cross-project memory")
    add("--verbose", "-v", action="store_true", help="plain output: also show the conversations and each task")
    sprint = p.add_argument_group("sprints", "the team builds in sprints with standups, review and retrospective (the default)")
    sprint.add_argument("--no-agile", action="store_true", help="one flat run with no sprints, no ceremonies and no approvals")
    sprint.add_argument("--sprint-capacity", type=int, help="tasks per sprint (default: 8 for the first, then the team's own velocity)")
    sprint.add_argument("--max-days", type=int, default=4, help="work days in a sprint before it is timeboxed")
    sprint.add_argument("--steps-per-day", type=int, default=40, help="most model steps a developer takes in one work day")
    sprint.add_argument("--unattended", action="store_true", help="approve every decision automatically (for CI and tests); by default you decide the documents and every major change")


def config_from_args(args: argparse.Namespace) -> tuple[TeamConfig, Optional[Path]]:
    memory_dir = None if args.no_memory else Path(args.memory_dir or os.environ.get("COUNCIL_MEMORY_DIR") or Path.home() / ".council" / "memory")
    agile = None if args.no_agile else AgileConfig(
        capacity=args.sprint_capacity, max_days=args.max_days, steps_per_day=args.steps_per_day, approvals="approve" if args.unattended else "ask",
    )
    config = TeamConfig(
        max_parallel=args.max_parallel, repair_rounds=args.repair_rounds, memory_dir=memory_dir, publish=args.publish, publish_all=args.publish_all,
        pull_request=args.pr, max_llm_concurrency=args.max_llm, git_fix_rounds=args.git_fix_rounds, agile=agile,
    )
    if args.run_id:
        config.run_id = args.run_id
    return config, memory_dir


def plain_asker(get_engine):
    """In plain mode a decision is asked at the prompt (on a thread, so the team keeps working while the human reads)."""

    def ask(data: dict) -> None:
        def worker() -> None:
            print(f"\n=== {data['title']} ===\n{data.get('detail', '')}", flush=True)
            try:
                reply = input("Approve? [y = yes / anything else = no, and say what should change]: ").strip()
            except EOFError:
                reply = "n"
            approved = reply.lower() in ("y", "yes")
            engine = get_engine()
            loop = engine.loop
            loop.call_soon_threadsafe(lambda: engine.agile.desk.answer(data["id"], approved, "" if approved else reply))

        threading.Thread(target=worker, daemon=True).start()

    return ask


def execute_build(args: argparse.Namespace, meeting: Path) -> int:
    """Builds from a finished meeting directory. Shared by `build` and the combined `run`."""
    settings = load_settings()
    config, memory_dir = config_from_args(args)
    workdir = Path(args.workdir) if args.workdir else meeting / "team"
    repo = (args.repo or "").strip()
    source = Path(repo).expanduser() if repo and not repo.lower().startswith(("http://", "https://")) and Path(repo).expanduser().is_dir() else None
    holder: dict[str, Any] = {}

    def make_engine(on_event):
        engine = TeamEngine(meeting, workdir, api_key=settings.api_key, model=settings.model, source=source, config=config, on_event=on_event)
        holder["engine"] = engine
        return engine

    if not args.plain and _interactive():
        from team.tui import run_team_tui

        app = run_team_tui(make_engine, meeting.name)
        engine, result = app.engine, app.result
        if result is None:
            print(f"The build did not finish{': ' + app.error if app.error else ' (stopped)'}. Finished work is in the branches under {workdir / 'remote' / 'origin.git'}; run again with the same --run-id to resume.")
            return 2
    else:
        if config.agile is not None and config.agile.approvals == "ask":
            print("Plain mode: you will be asked about the documents and every major decision here. To interrupt and steer the team while it works, use the full-screen view (drop --plain).")

        async def go():
            engine = make_engine(printer(args.verbose, plain_asker(lambda: holder["engine"]) if config.agile is not None and config.agile.approvals == "ask" else None))
            engine.loop = asyncio.get_running_loop()
            return engine, await engine.run()

        engine, result = asyncio.run(go())
    merged = sum(1 for f in result.features if f.status == "merged")
    print(f"\n{merged}/{len(result.features)} features merged. Verification: {'PASSED' if result.passed else 'not verified'}.")
    if result.sprints:
        print(f"{len(result.sprints)} sprint(s): " + "; ".join(f"#{n} {done}/{planned} tasks" for n, _, planned, done in result.sprints) + ". Sprint documents are in docs/agile/ on the final branch.")
    if result.lessons_learned:
        print(f"Learned {result.lessons_learned} lesson(s) for next time (memory: {memory_dir}).")
    if result.published_to:
        print(f"Published to {result.published_to}." + (f" Pull request: {result.pull_request_url}" if result.pull_request_url else ""))
    print(f"Review branch {result.final_branch} in {engine.repo.origin} and merge it into {engine.repo.main} yourself. Report: {meeting / 'team_report.md'}")
    for w in result.warnings:
        print(f"  ! {w}")
    return 0 if result.passed else 2


def build(argv: list[str]) -> int:
    """`build <meeting dir>`: the developers implement the specification in parallel, each in their own clone."""
    p = argparse.ArgumentParser(prog="python -m council build", description="Developers implement the specification on feature branches; you merge the result.")
    p.add_argument("directory", help="a finished meeting output directory")
    add_build_arguments(p)
    args = p.parse_args(argv[1:])
    use_github_credentials()
    from team.agile.playbook import AgileStopped

    try:
        return execute_build(args, Path(args.directory))
    except AgileStopped as exc:
        print(f"\nStopped: {exc}. Nothing was built. Revise the documents (python -m council revise <dir> --feedback \"...\") and run again.")
        return 3
