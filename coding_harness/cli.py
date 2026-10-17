"""Terminal front end: `python -m coding_harness [prompt]` runs one task, with no prompt it opens an interactive session."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from coding_harness.agents import prompt_text
from coding_harness.runner import HarnessError, Runner
from coding_harness.session import Session
from coding_harness.types import Event
from coding_harness.workspace import Workspace

DIM, BOLD, RED, GREEN, YELLOW, RESET = "\x1b[2m", "\x1b[1m", "\x1b[31m", "\x1b[32m", "\x1b[33m", "\x1b[0m"


def _arg_summary(tool: str, args: dict[str, Any]) -> str:
    for key in ("command", "path", "pattern", "url", "description"):
        if key in args:
            return str(args[key]).replace("\n", " ")[:100]
    return ""


class Printer:
    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self._mid_line = False

    def __call__(self, e: Event) -> None:
        d = e.data
        who = f"{DIM}[{d.get('agent', '')}]{RESET} " if d.get("agent") not in (None, "build") else ""
        if e.kind == "text":
            sys.stdout.write(d["text"])
            sys.stdout.flush()
            self._mid_line = not d["text"].endswith("\n")
        elif e.kind == "thought" and self.verbose:
            sys.stdout.write(f"{DIM}{d['text']}{RESET}")
        elif e.kind == "tool_start":
            self._nl()
            print(f"{who}{YELLOW}>{RESET} {BOLD}{d['tool']}{RESET} {DIM}{_arg_summary(d['tool'], d['args'])}{RESET}")
        elif e.kind == "tool_end":
            if d.get("error"):
                print(f"  {RED}x {d['output'].splitlines()[0][:160] if d['output'] else 'failed'}{RESET}")
            elif d.get("diff"):
                lines = d["diff"].splitlines()
                for ln in lines[:24]:
                    colour = GREEN if ln.startswith("+") and not ln.startswith("+++") else RED if ln.startswith("-") and not ln.startswith("---") else DIM
                    print(f"  {colour}{ln}{RESET}")
                if len(lines) > 24:
                    print(f"  {DIM}... {len(lines) - 24} more diff lines{RESET}")
            elif self.verbose:
                print(f"  {DIM}{d['output'][:300]}{RESET}")
        elif e.kind == "retry":
            self._nl()
            print(f"{DIM}  model {d['reason']}: retry {d['attempt']} in {d['delay']}s{RESET}")
        elif e.kind == "compaction":
            self._nl()
            print(f"{DIM}  [context] {d.get('mode')}{RESET}")
        elif e.kind == "subagent_start":
            self._nl()
            print(f"{who}{YELLOW}>{RESET} subagent {BOLD}{d['agent']}{RESET} {DIM}{d['description']}{RESET}")
        elif e.kind == "note":
            self._nl()
            print(f"{DIM}  {d['text']}{RESET}")

    def _nl(self) -> None:
        if self._mid_line:
            sys.stdout.write("\n")
            self._mid_line = False


async def terminal_asker(request: dict[str, Any]) -> dict[str, Any]:
    res = ", ".join(request["resources"])
    print(f"\n{YELLOW}Permission needed:{RESET} {BOLD}{request['action']}{RESET} {res}")
    diff = request.get("metadata", {}).get("diff")
    if diff:
        print(DIM + "\n".join(diff.splitlines()[:30]) + RESET)
    ans = (await asyncio.to_thread(input, "  [y] once  [a] always  [n] no  (or type feedback): ")).strip()
    if ans.lower() in ("y", "yes", ""):
        return {"reply": "once"}
    if ans.lower() in ("a", "always"):
        return {"reply": "always"}
    if ans.lower() in ("n", "no"):
        return {"reply": "reject"}
    return {"reply": "reject", "message": ans}


async def always_yes(request: dict[str, Any]) -> dict[str, Any]:
    return {"reply": "session"}


async def terminal_questions(questions: list[dict[str, Any]]) -> list[str]:
    answers = []
    for q in questions:
        print(f"\n{BOLD}{q.get('question', '')}{RESET}")
        opts = q.get("options") or []
        for i, o in enumerate(opts, 1):
            label = o.get("label", o) if isinstance(o, dict) else o
            print(f"  {i}. {label}")
        raw = (await asyncio.to_thread(input, "  > ")).strip()
        answers.append(opts[int(raw) - 1].get("label", raw) if raw.isdigit() and 0 < int(raw) <= len(opts) and isinstance(opts[int(raw) - 1], dict) else raw)
    return answers


def make_model(name: str):
    from coding_harness.llm_gemini import GeminiChatModel

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set (put it in the environment or a .env file).")
    return GeminiChatModel(key, name)


async def repl(runner: Runner, session: Session, agent: str) -> None:
    print(f"{BOLD}coding_harness{RESET} {DIM}agent={agent} dir={runner.ws.cwd} session={session.id}{RESET}")
    print(f"{DIM}/undo  /compact  /agent NAME  /init  /todos  /sessions  /exit{RESET}")
    while True:
        try:
            line = (await asyncio.to_thread(input, f"\n{BOLD}you>{RESET} ")).strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not line:
            continue
        if line in ("/exit", "/quit"):
            return
        if line == "/undo":
            print(f"{DIM}reverted: {', '.join(runner.undo(session)) or 'nothing to undo'}{RESET}")
            continue
        if line == "/compact":
            print(f"{DIM}{'compacted' if await runner.compact(session) else 'nothing to compact'}{RESET}")
            continue
        if line == "/todos":
            for t in session.todos:
                print(f"  [{t['status']}] {t['content']}")
            continue
        if line == "/sessions":
            for s in Session.list(runner.ws)[:15]:
                print(f"  {s['id']}  {s['agent']:8} {s.get('title') or ''}")
            continue
        if line.startswith("/agent"):
            name = line.split(maxsplit=1)[1] if " " in line else ""
            if name in runner.agents:
                agent = name
                print(f"{DIM}agent: {agent}{RESET}")
            else:
                print(f"{DIM}agents: {', '.join(runner.agents)}{RESET}")
            continue
        if line.startswith("/init"):
            line = prompt_text("init.txt").replace("$ARGUMENTS", line[5:].strip() or "(none)")
        try:
            res = await runner.run(session, line, agent)
        except HarnessError as exc:
            print(f"\n{RED}{exc}{RESET}")
            continue
        except KeyboardInterrupt:
            print(f"\n{DIM}interrupted{RESET}")
            continue
        print(f"\n{DIM}[{res.steps} steps, {res.usage['input_tokens']} in / {res.usage['output_tokens']} out tokens{'; ' + res.stopped if res.stopped != 'completed' else ''}]{RESET}")


async def amain(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="coding_harness", description="Terminal coding agent with files, shell, git/GitHub, memory and subagents.")
    p.add_argument("prompt", nargs="*", help="Task to run once; omit for an interactive session")
    p.add_argument("-d", "--dir", default=".", help="Project directory (default: current)")
    p.add_argument("-a", "--agent", default=None, help="build (default), plan, explore or general")
    p.add_argument("-m", "--model", default=os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite"))
    p.add_argument("--yes", action="store_true", help="Approve every permission prompt automatically (dangerous)")
    p.add_argument("--resume", metavar="SESSION", help="Continue a saved session")
    p.add_argument("--continue", dest="cont", action="store_true", help="Continue the most recent session")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    try:
        from dotenv import load_dotenv

        load_dotenv(Path.cwd() / ".env")
    except ImportError:
        pass
    ws = Workspace(args.dir)
    runner = Runner(ws, make_model(args.model), asker=always_yes if args.yes else terminal_asker, ask_user=terminal_questions, observer=Printer(args.verbose))
    agent = args.agent or runner.cfg.default_agent
    try:
        if args.resume:
            session = runner.resume_session(args.resume)
        elif args.cont and (rows := [r for r in Session.list(ws) if not r.get("parent_id")]):
            session = runner.resume_session(rows[0]["id"])
        else:
            session = runner.new_session(agent)
        if args.prompt:
            res = await runner.run(session, " ".join(args.prompt), agent)
            print(f"\n\n{DIM}[{res.steps} steps; session {session.id}]{RESET}")
            return 0 if res.stopped == "completed" else 2
        await repl(runner, session, agent)
        return 0
    except HarnessError as exc:
        print(f"{RED}{exc}{RESET}", file=sys.stderr)
        return 1
    finally:
        await runner.close()


def main() -> None:
    try:
        raise SystemExit(asyncio.run(amain()))
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == "__main__":
    main()
