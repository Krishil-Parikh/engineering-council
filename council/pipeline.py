"""`python -m council run`: from one prompt to a built project, in one go.

    your prompt  ->  kickoff meeting and Q&A (PRD, Technical_Approach, Design)  ->  you read and accept the documents
                 ->  sprints: planning, work days, standups, review, report, retrospective, document sync  ->  a final branch for you to merge

You can interrupt the team at any time in the full-screen view (press i), leave it a note (n), and every major decision waits for you."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Optional

from meetings.cli import _interactive_terminal, build_parser, confirm, gather_input, input_from_args, print_summary
from meetings.config import ConfigError, load_settings
from meetings.gemini_client import GeminiClient, LLMError
from meetings.meeting import MeetingError, Reporter, load_saved_input, run_meeting
from team.cli import add_build_arguments, execute_build
from team.agile.playbook import AgileStopped


def make_parser() -> argparse.ArgumentParser:
    p = build_parser()
    p.prog = "python -m council run"
    p.description = "From a prompt to a built project: a kickoff meeting, your approval of the documents, then the team builds in sprints. You can interrupt it at any time."
    p.epilog = None
    add_build_arguments(p, skip=frozenset({"--repo", "--plain", "--verbose", "-v"}))  # the meeting's flags of those names serve the build too
    p.add_argument("--from-meeting", metavar="DIR", help="skip the meeting and build from this finished meeting directory")
    return p


def kickoff(args: argparse.Namespace) -> Optional[Path]:
    """Phase one: the meeting. Returns the meeting directory, or None when it did not finish."""
    settings = load_settings()
    if not args.plain and _interactive_terminal():
        from meetings.tui import run_tui

        app = run_tui(settings, GeminiClient(settings), input_from_args(args), base_output=args.output, auto_answers=args.yes, a2a=not args.no_a2a)
        if app.result is None:
            if app.error:
                print(f"\nThe meeting did not finish: {app.error}", file=sys.stderr)
            if app.out_dir is not None and (app.out_dir / "meeting.json").exists():
                print(f"Completed stages are saved. Continue with:  python -m council resume \"{app.out_dir}\"")
            return None
        print_summary(app.result)
        return app.result.out_dir
    inp = gather_input(args)
    confirm(inp, settings, args.yes)
    result = asyncio.run(run_meeting(inp, settings, GeminiClient(settings), Reporter(args.verbose), interactive=not args.yes, a2a=not args.no_a2a))
    print_summary(result)
    return result.out_dir


def carry_repo(args: argparse.Namespace, meeting: Path) -> None:
    """The repository named on the meeting's start form (or by --repo) is also the one the team builds on. A GitHub URL is cloned next to the
    meeting first, because the team works from a local copy."""
    if (args.repo or "").strip():
        repo = args.repo.strip()
    else:
        try:
            saved = load_saved_input(meeting)
        except MeetingError:
            return
        repo = (saved.repo_path or saved.github_url or "").strip()
    if repo.lower().startswith(("http://", "https://")):
        target = meeting / "source"
        if not target.exists():
            print(f"Cloning {repo} so the team can build on it…")
            done = subprocess.run(["git", "clone", "--depth", "1", "--", repo, str(target)], capture_output=True, text=True)
            if done.returncode != 0:
                raise MeetingError(f"Could not clone {repo}: {done.stderr.strip()[-300:]}")
        repo = str(target)
    args.repo = repo or None


def run(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    args = make_parser().parse_args(argv)
    try:
        if args.from_meeting:
            meeting = Path(args.from_meeting)
            if not (meeting / "specification.json").exists():
                raise MeetingError(f"{meeting} has no specification.json: it is not a finished meeting.")
        else:
            meeting = kickoff(args)
            if meeting is None:
                return 1
        carry_repo(args, meeting)
        print("\nThe meeting is done. The documents are put in front of you next; nothing is built until you accept them.\n")
        return execute_build(args, meeting)
    except AgileStopped as exc:
        print(f"\nStopped: {exc}. Nothing was built. Revise the documents (python -m council revise <dir> --feedback \"...\") and run again.")
        return 3
    except (ConfigError, MeetingError, LLMError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. Finished work is saved; run again with the same --run-id (and --from-meeting) to resume.", file=sys.stderr)
        return 130
