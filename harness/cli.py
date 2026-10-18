"""`python -m harness`: the coding agent in a terminal.

    python -m harness                      an interactive session in the current directory
    python -m harness "fix the failing test"      run one task and exit
    python -m harness -c                   continue the most recent session here
    python -m harness sessions | stats | export <id> | import <file>

Inside a session, lines starting with / are commands: /help lists them. Ctrl+C stops the agent's current work without leaving the session."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Any, Callable, Optional, TextIO

from harness.app import Harness
from harness.session import portable
from harness.session import stats as Stats

DIM, BOLD, RED, GREEN, YELLOW, RESET = "\x1b[2m", "\x1b[1m", "\x1b[31m", "\x1b[32m", "\x1b[33m", "\x1b[0m"
HELP = """/help                this list
/new                 start a new session
/sessions            list this directory's sessions
/agent <name>        switch agent (build, plan, ...)
/undo                rewind to before your last message (files too); /redo brings it back
/compact             summarize the older conversation now
/stats               tokens, cost, tools used
/export [file]       save this session as JSON (or .md for a transcript)
/title               name the session
/exit                leave
anything else starting with /  runs a command (init, review, or one from your commands folder)"""


def summary(tool: str, data: Any) -> str:
    if isinstance(data, dict):
        for key in ("command", "path", "pattern", "name", "description", "id"):
            if key in data:
                return str(data[key]).replace("\n", " ")[:100]
    return ""


class Printer:
    """Shows what the agent does as it happens."""

    def __init__(self, out: TextIO, verbose: bool = False, color: bool = True) -> None:
        self.out, self.verbose, self.color = out, verbose, color
        self._tools: dict[str, str] = {}
        self._mid_line = False

    def c(self, code: str, text: str) -> str:
        return f"{code}{text}{RESET}" if self.color else text

    def _nl(self) -> None:
        if self._mid_line:
            self.out.write("\n")
            self._mid_line = False

    def __call__(self, kind: str, data: dict) -> None:
        if kind == "text.delta":
            self.out.write(data["text"])
            self.out.flush()
            self._mid_line = not data["text"].endswith("\n")
        elif kind == "reasoning.delta" and self.verbose:
            self.out.write(self.c(DIM, data["text"]))
        elif kind == "tool.input.started":
            self._tools[data["call"]] = data["tool"]
        elif kind == "tool.called":
            self._nl()
            name = self._tools.get(data["call"], "tool")
            self.out.write(f"{self.c(YELLOW, '>')} {self.c(BOLD, name)} {self.c(DIM, summary(name, data.get('input')))}\n")
        elif kind == "tool.failed":
            self._nl()
            self.out.write(self.c(RED, f"  x {str(data['error']).splitlines()[0][:200] if data['error'] else 'failed'}") + "\n")
        elif kind == "retry.scheduled":
            self._nl()
            self.out.write(self.c(DIM, f"  the model failed ({str(data['error'])[:80]}); retry {data['attempt']}") + "\n")
        elif kind == "step.failed":
            self._nl()
            self.out.write(self.c(RED, f"  step failed: {data['error']}") + "\n")
        elif kind == "compaction.started":
            self._nl()
            self.out.write(self.c(DIM, "  summarizing the older conversation…") + "\n")
        elif kind == "plugin.error":
            self._nl()
            self.out.write(self.c(YELLOW, f"  plugin problem ({data['hook']}): {data['message']}") + "\n")
        self.out.flush()


def make_approver(auto: bool, ask: Callable[[str], str], out: TextIO):
    async def approve(request) -> Any:
        if auto:
            return "once"
        shown = ", ".join(request.resources)[:200]
        out.write(f"\n{YELLOW}?{RESET} Allow {BOLD}{request.action}{RESET}: {shown}\n")
        answer = (await asyncio.to_thread(ask, "  [y]es once / [a]lways / [n]o (or type why not): ")).strip()
        if answer.lower() in ("y", "yes", "o", "once", ""):
            return "once"
        if answer.lower() in ("a", "always"):
            return "always"
        return ("reject", None if answer.lower() in ("n", "no") else answer)

    return approve


class Cli:
    def __init__(self, harness: Harness, out: TextIO, ask: Callable[[str], str], directory: Path) -> None:
        self.h, self.out, self.ask, self.directory = harness, out, ask, directory
        self.session_id: Optional[str] = None
        self.agent: Optional[str] = None

    def say(self, text: str = "") -> None:
        self.out.write(text + "\n")

    async def turn(self, text: str) -> None:
        """Runs one prompt; Ctrl+C interrupts the agent's work instead of the program."""
        sid = self.session_id or self.h.new_session(self.agent).id
        self.session_id = sid
        loop = asyncio.get_running_loop()
        previous = signal.getsignal(signal.SIGINT)

        def interrupt(*_: Any) -> None:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.h.sessions.interrupt(sid)))

        try:
            signal.signal(signal.SIGINT, interrupt)
        except ValueError:  # not the main thread (tests)
            previous = None
        try:
            result = await self.h.prompt(text, sid, self.agent)
        finally:
            if previous is not None:
                signal.signal(signal.SIGINT, previous)
        if result.outcome == "interrupted":
            self.say(f"\n{DIM}(stopped){RESET}")
        elif result.outcome == "failed":
            self.say(f"\n{RED}The run failed: {result.error}{RESET}")
        self.say()

    # ------------------------------------------------------------------ slash commands

    async def command(self, line: str) -> bool:
        """Returns False to leave."""
        name, _, rest = line[1:].partition(" ")
        rest = rest.strip()
        h = self.h
        if name in ("exit", "quit", "q"):
            return False
        if name == "help":
            self.say(HELP)
        elif name == "new":
            self.session_id = None
            self.say("New session.")
        elif name == "sessions":
            for s in h.store.list(str(self.directory)):
                self.say(f"{s.id}  {s.title or '(untitled)'}" + ("  [rewound]" if s.revert else ""))
        elif name == "agent":
            if not rest or h.agents.get(rest) is None:
                self.say("Agents: " + ", ".join(a.id for a in h.agents.list() if not a.hidden))
            else:
                self.agent = rest
                self.say(f"Using the {rest} agent.")
        elif name == "undo":
            await self.undo()
        elif name == "redo":
            if self.session_id and h.revert.unstage(self.session_id):
                self.say("Brought back what you undid.")
            else:
                self.say("Nothing to redo.")
        elif name == "compact":
            if self.session_id is None:
                self.say("There is no conversation yet.")
            else:
                result = await h.sessions.compact(self.session_id)
                self.say("Summarized." if result.outcome == "succeeded" else f"Could not summarize: {result.error.message if result.error else result.outcome}")
        elif name == "stats":
            self.say(Stats.render(Stats.collect(h.store, self.session_id) if self.session_id else Stats.collect(h.store, directory=str(self.directory))))
        elif name == "export":
            self.export(rest or None)
        elif name == "title":
            if self.session_id:
                self.say(await h.titles.generate(self.session_id) or "(no new title)")
        else:
            try:
                result = await h.command(name, rest, self.session_id)
            except Exception as exc:  # noqa: BLE001 - shown, not fatal
                self.say(f"{RED}{exc}{RESET}")
            else:
                self.session_id = result.session_id
                self.say()
        return True

    async def undo(self) -> None:
        if self.session_id is None:
            self.say("There is nothing to undo.")
            return
        points = self.h.revert.points(self.session_id)
        if not points:
            self.say("There is nothing to undo.")
            return
        state = self.h.revert.stage(self.session_id, points[-1]["message_id"])
        files = ", ".join(state.files) or "no files"
        self.say(f"Rewound to before: {points[-1]['text']!r}. Files put back: {files}. (/redo undoes this; sending a new message makes it final.)")

    def export(self, target: Optional[str]) -> None:
        if self.session_id is None:
            self.say("There is no conversation yet.")
            return
        path = Path(target or f"{self.session_id}.json")
        if path.suffix == ".md":
            path.write_text(portable.to_markdown(self.h.store, self.session_id), encoding="utf-8")
        else:
            path.write_text(portable.dumps(portable.export_session(self.h.store, self.session_id)), encoding="utf-8")
        self.say(f"Saved {path}")

    # ------------------------------------------------------------------ the loop

    async def repl(self) -> None:
        self.say(f"{BOLD}harness{RESET} in {self.directory}  {DIM}(/help for commands, Ctrl+C stops the agent, /exit leaves){RESET}")
        while True:
            try:
                line = (await asyncio.to_thread(self.ask, f"{GREEN}>{RESET} ")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line.startswith("/"):
                if not await self.command(line):
                    break
                continue
            await self.turn(line)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m harness", description="The coding agent in your terminal.")
    p.add_argument("words", nargs="*", help="a task to run and exit (or: sessions | stats | export <id> | import <file>)")
    p.add_argument("-d", "--directory", default=".", help="the project directory (default: here)")
    p.add_argument("-a", "--agent", help="the agent to use (default: build)")
    p.add_argument("-m", "--model", help="the model id")
    p.add_argument("-s", "--session", help="continue this session")
    p.add_argument("-c", "--continue", dest="resume", action="store_true", help="continue the most recent session in this directory")
    p.add_argument("-y", "--yes", action="store_true", help="allow every action without asking")
    p.add_argument("-o", "--output", help="export: where to write")
    p.add_argument("--markdown", action="store_true", help="export: a readable transcript instead of JSON")
    p.add_argument("--days", type=int, help="stats: only the last N days")
    p.add_argument("--no-snapshots", action="store_true", help="do not take file snapshots (turns off /undo's file restore)")
    p.add_argument("--no-title", action="store_true", help="do not ask the model to name new sessions")
    p.add_argument("-v", "--verbose", action="store_true", help="show the model's reasoning")
    return p


def main(argv: Optional[list[str]] = None, *, llm: Any = None, ask: Callable[[str], str] = input, out: Optional[TextIO] = None) -> int:
    out = out or sys.stdout
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    directory = Path(args.directory).resolve()
    if not directory.is_dir():
        print(f"Not a directory: {directory}", file=sys.stderr)
        return 1
    printer = Printer(out, args.verbose, color=getattr(out, "isatty", lambda: False)())
    try:
        harness = Harness(
            directory, llm=llm, model=args.model, snapshots=not args.no_snapshots, on_event=printer, auto_title=not args.no_title,
            approve=make_approver(args.yes, ask, out),
        )
    except KeyError:
        print("Set GEMINI_API_KEY (in the environment or a .env file) to use the harness.", file=sys.stderr)
        return 1
    cli = Cli(harness, out, ask, directory)
    words = args.words
    if words and words[0] in ("sessions", "stats", "export", "import") and (len(words) == 1 or words[0] in ("export", "import")):
        return asyncio.run(admin(cli, words, args))
    if args.session:
        if harness.store.get(args.session) is None:
            print(f"No such session: {args.session}", file=sys.stderr)
            return 1
        cli.session_id = args.session
    elif args.resume:
        recent = harness.store.list(str(directory))
        cli.session_id = recent[0].id if recent else None
    cli.agent = args.agent

    async def go() -> int:
        try:
            if words:
                await cli.turn(" ".join(words))
            else:
                await cli.repl()
        finally:
            await harness.close()
        return 0

    return asyncio.run(go())


async def admin(cli: Cli, words: list[str], args: argparse.Namespace) -> int:
    h = cli.h
    try:
        if words[0] == "sessions":
            await cli.command("/sessions")
        elif words[0] == "stats":
            cli.say(Stats.render(Stats.collect(h.store, args.session, str(cli.directory) if not args.session else None, args.days)))
        elif words[0] == "export":
            if len(words) < 2:
                print("export needs a session id", file=sys.stderr)
                return 1
            cli.session_id = words[1]
            cli.export(args.output or (f"{words[1]}.md" if args.markdown else None))
        elif words[0] == "import":
            if len(words) < 2:
                print("import needs a file", file=sys.stderr)
                return 1
            info = portable.import_session(h.store, portable.loads(Path(words[1]).read_text(encoding="utf-8")), str(cli.directory))
            cli.say(f"Imported as {info.id} ({info.title or 'untitled'}). Continue it with: python -m harness -s {info.id}")
    except (KeyError, portable.ImportError_, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        await h.close()
    return 0
