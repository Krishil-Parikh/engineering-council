"""Command line for agent mode: the developers build the project from a finished meeting."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from meetings.config import load_settings
from team.engine import TeamConfig, TeamEngine


def printer(verbose: bool):
    def show(kind: str, data: dict) -> None:
        if kind == "plan":
            print("\nPlan:")
            for f in data["plan"]["features"]:
                after = f" (after {', '.join(f['depends_on'])})" if f["depends_on"] else ""
                print(f"  - {f['id']} -> {f['owner']}{after}: {f['title']}")
        elif kind == "feature-started":
            print(f"\n[start]   {data['feature']} ({data['owner']})")
        elif kind == "feature-done":
            print(f"[merged]  {data['feature']}: {data['detail']}")
        elif kind == "feature-failed":
            print(f"[FAILED]  {data['feature']}: {data['detail']}")
        elif kind == "feature-blocked":
            print(f"[blocked] {data['feature']}: {data['detail']}")
        elif kind == "conflict":
            print(f"[conflict] {data['feature']}: {', '.join(data['files'])}")
        elif kind == "conflict-talk":
            print(f"           talking with {', '.join(data['with_'])} (round {data['round']})")
        elif kind == "task" and verbose:
            print(f"          task {data['index']}/{data['total']} ({data['owner']}): {data['title']}")
        elif kind == "verification":
            print(f"[verify]  {data['failing']} failing command(s) (attempt {data['attempt'] + 1})")
        elif kind == "final":
            print(f"\n[final]   {data['branch']} is ready for you to review")

    return show


def build(argv: list[str]) -> int:
    """`build <meeting dir>`: the developers implement the specification in parallel, each in their own clone."""
    p = argparse.ArgumentParser(prog="python -m council build", description="Developers implement the specification on feature branches; you merge the result.")
    p.add_argument("directory", help="a finished meeting output directory")
    p.add_argument("--repo", help="an existing repository to build on (its current commit becomes main); default: a new empty project")
    p.add_argument("--workdir", help="where the team's remote and clones live (default: <dir>/team)")
    p.add_argument("--max-parallel", type=int, default=6, help="most features worked on at the same time")
    p.add_argument("--run-id", help="name this run (default: a timestamp); reuse a run id to resume")
    p.add_argument("--repair-rounds", type=int, default=2, help="repair rounds when the verification commands fail")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv[1:])
    settings = load_settings()
    config = TeamConfig(max_parallel=args.max_parallel, repair_rounds=args.repair_rounds)
    if args.run_id:
        config.run_id = args.run_id
    meeting = Path(args.directory)
    engine = TeamEngine(
        meeting, Path(args.workdir) if args.workdir else meeting / "team", api_key=settings.api_key, model=settings.model,
        source=Path(args.repo) if args.repo else None, config=config, on_event=printer(args.verbose),
    )
    result = asyncio.run(engine.run())
    merged = sum(1 for f in result.features if f.status == "merged")
    print(f"\n{merged}/{len(result.features)} features merged. Verification: {'PASSED' if result.passed else 'not verified'}.")
    print(f"Review branch {result.final_branch} in {engine.repo.origin} and merge it into main yourself. Report: {meeting / 'team_report.md'}")
    for w in result.warnings:
        print(f"  ! {w}")
    return 0 if result.passed else 2
