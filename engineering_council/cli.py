"""Command line entry: interactive prompts, stage progress, and concise error messages."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from engineering_council import __version__
from engineering_council.config import ConfigError, Settings, load_settings
from engineering_council.gemini_client import GeminiClient, LLM, LLMError
from engineering_council.meeting import (
    MeetingError,
    MeetingResult,
    Reporter,
    load_saved_input,
    meeting_dir,
    revise_meeting,
    run_meeting,
)
from engineering_council.models import MeetingInput


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m engineering_council",
        description="Run a structured multi-agent engineering meeting that produces PRD.md, "
        "Technical_Approach.md and Design.md.",
        epilog="Other commands:  build <dir>    the developers build the project from a finished meeting\n"
        "                resume <dir>   continue an interrupted meeting\n"
        "                revise <dir> --feedback \"...\"   targeted revision of finished documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"engineering-council {__version__}")
    p.add_argument("--name", help="project name")
    p.add_argument("--problem", help="problem statement text")
    p.add_argument("--problem-file", help="Markdown/text file containing the problem statement")
    p.add_argument("--repo", help="local repository path or public GitHub URL (optional)")
    p.add_argument("--constraint", action="append", default=[], help="repeatable: platform, deadline, budget, tech...")
    p.add_argument("--output", default="output", help="base output directory (default: ./output)")
    p.add_argument("--yes", "-y", action="store_true", help="skip confirmation and accept default answers")
    p.add_argument("--verbose", "-v", action="store_true", help="show diagnostic details")
    p.add_argument("--plain", action="store_true", help="plain scrolling output instead of the full-screen TUI")
    return p


def _ask(prompt: str, default: str = "") -> str:
    try:
        value = input(prompt).strip()
    except EOFError:
        return default
    return value or default


def _read_problem_file(path: str) -> str:
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise MeetingError(f"Cannot read problem file {path!r}: {exc.strerror or exc}") from exc
    if not text:
        raise MeetingError(f"Problem file {path!r} is empty.")
    return text


def _typed_problem() -> str:
    print("Describe the problem (finish with an empty line):")
    lines: list[str] = []
    while True:
        try:
            line = input("> ")
        except EOFError:
            break
        if not line.strip():
            if lines:
                break
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def gather_input(args: argparse.Namespace) -> MeetingInput:
    print("\nEngineering Council — New Meeting")
    name = args.name or _ask("Project name: ")
    problem = args.problem
    if not problem and args.problem_file:
        problem = _read_problem_file(args.problem_file)
    if not problem:
        pf = _ask("Problem statement file (optional, Enter to type it): ")
        problem = _read_problem_file(pf) if pf else _typed_problem()
    repo = args.repo if args.repo is not None else ("" if args.yes else _ask("Repository path or GitHub URL (optional): "))
    constraints = list(args.constraint)
    if not constraints and not args.yes:
        raw = _ask("Constraints (comma separated, optional): ")
        constraints = [c.strip() for c in raw.split(",") if c.strip()]
    name, problem = (name or "").strip(), (problem or "").strip()
    if not name:
        raise MeetingError("A project name is required.")
    if not problem:
        raise MeetingError("A problem statement is required.")
    if len(problem) > 20_000:
        raise MeetingError("The problem statement is longer than 20,000 characters; please shorten it.")
    repo = (repo or "").strip()
    is_url = repo.lower().startswith(("http://", "https://"))
    if repo and not is_url and not Path(repo).expanduser().is_dir():
        raise MeetingError(f"Repository path is not a directory: {repo}")
    return MeetingInput(
        project_name=name,
        problem=problem,
        constraints=constraints,
        repo_path=repo if repo and not is_url else None,
        github_url=repo if is_url else None,
        output_dir=args.output,
    )


def input_from_args(args: argparse.Namespace) -> MeetingInput | None:
    """Build the meeting input from flags alone. None means the TUI form should ask for the rest."""
    problem = args.problem or (_read_problem_file(args.problem_file) if args.problem_file else "")
    if not (args.name and problem):
        return None
    repo = (args.repo or "").strip()
    is_url = repo.lower().startswith(("http://", "https://"))
    if repo and not is_url and not Path(repo).expanduser().is_dir():
        raise MeetingError(f"Repository path is not a directory: {repo}")
    return MeetingInput(
        project_name=args.name.strip(), problem=problem.strip(), constraints=list(args.constraint),
        repo_path=repo if repo and not is_url else None, github_url=repo if is_url else None, output_dir=args.output,
    )


def _interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def finish_tui(app) -> int:
    """After the full-screen UI closes, leave a short summary in the normal terminal."""
    if app.result is not None:
        print_summary(app.result)
        return 0 if app.result.report.passed else 2
    if app.error:
        print(f"\nError: {app.error}", file=sys.stderr)
    if app.out_dir is not None and (app.out_dir / "meeting.json").exists():
        print(f"Completed stages are saved. Continue with:  python -m engineering_council resume \"{app.out_dir}\"")
    return 1 if app.error else 130


def confirm(inp: MeetingInput, settings: Settings, assume_yes: bool) -> None:
    print("\nConfiguration")
    print(f"  Project:     {inp.project_name}")
    print(f"  Model:       {settings.model}")
    print(f"  Repository:  {inp.repo_path or inp.github_url or '(none, greenfield)'}")
    print(f"  Constraints: {', '.join(inp.constraints) or '(none)'}")
    print(f"  Output:      {meeting_dir(inp)}")
    print("  Note: the problem statement and any repository excerpts are sent to the Gemini API.")
    if not assume_yes and _ask("Start the meeting? [Y/n]: ", "y").lower() not in ("y", "yes"):
        raise MeetingError("Cancelled before any model call was made.")


def print_summary(result: MeetingResult) -> None:
    status = {}
    for d in result.decisions:
        status[d.status] = status.get(d.status, 0) + 1
    print("\nOutput:")
    for name in ("PRD.md", "Technical_Approach.md", "Design.md", "minutes.md", "verification_report.md"):
        print(f"  {result.out_dir / name}")
    print(f"\nDecisions: {', '.join(f'{n} {s}' for s, n in sorted(status.items())) or 'none'}")
    open_items = [d for d in result.decisions if d.status != "DECIDED"]
    for d in open_items:
        print(f"  ! {d.decision_id} [{d.status}] {d.statement}")
    print(f"Verification: {'PASSED' if result.report.passed else 'FAILED (see verification_report.md)'}")
    if result.warnings:
        print(f"Warnings: {len(result.warnings)} (listed in meeting.json)")
    print(f"\nTo request changes:  python -m engineering_council revise \"{result.out_dir}\" --feedback \"...\"")


def _make_llm(settings: Settings) -> LLM:
    return GeminiClient(settings)


def main(argv: list[str] | None = None, llm_factory=_make_llm) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    try:
        if argv and argv[0] == "build":
            return _build(argv)
        if argv and argv[0] in ("resume", "revise"):
            return _sub(argv, llm_factory)
        args = build_parser().parse_args(argv)
        settings = load_settings()
        if not args.plain and _interactive_terminal():
            from engineering_council.tui import run_tui  # imported lazily: --plain and tests never need Textual

            app = run_tui(settings, llm_factory(settings), input_from_args(args), base_output=args.output, auto_answers=args.yes)
            return finish_tui(app)
        inp = gather_input(args)
        confirm(inp, settings, args.yes)
        result = asyncio.run(
            run_meeting(inp, settings, llm_factory(settings), Reporter(args.verbose), interactive=not args.yes)
        )
        print_summary(result)
        return 0 if result.report.passed else 2
    except (ConfigError, MeetingError, LLMError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. Completed stages are saved; continue with `resume <dir>`.", file=sys.stderr)
        return 130


_DANGEROUS = ("git push", "gh pr merge", "sudo", "rm -rf", "rm -fr", "git reset --hard", "git clean", "gh repo delete", "npm publish", "twine upload", "gh release")


def _build(argv: list[str]) -> int:
    """`build <meeting dir>`: the pod implements the specification with the coding harness (files, shell, git, subagents, memory)."""
    from coding_harness import cli as hcli
    from coding_harness.llm_gemini import GeminiChatModel
    from engineering_council.build import build_project

    p = argparse.ArgumentParser(prog="python -m engineering_council build", description="Developers implement the specification in <dir>/project.")
    p.add_argument("directory", help="a finished meeting output directory")
    p.add_argument("--project-dir", help="where to build (default: <dir>/project)")
    p.add_argument("--yes", "-y", action="store_true", help="approve ordinary permission prompts automatically (pushes and other risky commands are always refused)")
    p.add_argument("--fix-rounds", type=int, default=2, help="repair rounds when the verification commands fail")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv[1:])
    settings = load_settings()
    out_dir = Path(args.directory)

    async def safe_yes(req: dict) -> dict:
        risky = [r for r in req["resources"] if req["action"] == "shell" and r.startswith(_DANGEROUS)]
        return {"reply": "reject", "message": "Not allowed in unattended builds; leave it for the user."} if risky else {"reply": "session"}

    model = GeminiChatModel(settings.api_key, settings.model)
    result = asyncio.run(build_project(
        out_dir, model, project_dir=Path(args.project_dir) if args.project_dir else None,
        asker=safe_yes if args.yes else hcli.terminal_asker, observer=hcli.Printer(args.verbose), fix_rounds=args.fix_rounds,
        on_step=lambda text: print(f"\n== {text}"),
    ))
    print(f"\nBuilt in {result.project_dir}\nVerification: {'PASSED' if result.passed else 'not verified'}  (report: {out_dir / 'build_report.md'})")
    for w in result.warnings:
        print(f"  ! {w}")
    return 0 if result.passed else 2


def _sub(argv: list[str], llm_factory) -> int:
    cmd = argv[0]
    p = argparse.ArgumentParser(prog=f"python -m engineering_council {cmd}")
    p.add_argument("directory", help="the meeting output directory")
    p.add_argument("--yes", "-y", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--plain", action="store_true", help="plain scrolling output instead of the TUI")
    if cmd == "revise":
        p.add_argument("--feedback", help="what to change")
    args = p.parse_args(argv[1:])
    settings = load_settings()
    out_dir = Path(args.directory)
    if not (out_dir / "meeting.json").exists():
        raise MeetingError(f"{out_dir} is not a meeting directory (no meeting.json).")
    rep = Reporter(args.verbose)
    if cmd == "resume":
        inp = load_saved_input(out_dir)
        inp = inp.model_copy(update={"output_dir": str(out_dir.parent)})
        if not args.plain and _interactive_terminal():
            from engineering_council.tui import run_tui

            return finish_tui(run_tui(settings, llm_factory(settings), inp, base_output=str(out_dir.parent), auto_answers=args.yes, resume=True))
        result = asyncio.run(run_meeting(inp, settings, llm_factory(settings), rep, interactive=not args.yes, resume=True))
    else:
        feedback = (args.feedback or _ask("What should change? ")).strip()
        if not feedback:
            raise MeetingError("Feedback is required.")
        result = asyncio.run(revise_meeting(out_dir, feedback, settings, llm_factory(settings), rep))
    print_summary(result)
    return 0 if result.report.passed else 2


if __name__ == "__main__":
    sys.exit(main())
