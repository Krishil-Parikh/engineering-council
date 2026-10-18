"""Command line for agent mode: the developers build the project from a finished meeting."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from meetings.config import load_settings

_DANGEROUS = ("git push", "gh pr merge", "sudo", "rm -rf", "rm -fr", "git reset --hard", "git clean", "gh repo delete", "npm publish", "twine upload", "gh release")


def build(argv: list[str]) -> int:
    """`build <meeting dir>`: the pod implements the specification with the coding harness (files, shell, git, subagents, memory)."""
    from harness.legacy import cli as hcli
    from harness.legacy.llm_gemini import GeminiChatModel
    from team.build import build_project

    p = argparse.ArgumentParser(prog="python -m council build", description="Developers implement the specification in <dir>/project.")
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
