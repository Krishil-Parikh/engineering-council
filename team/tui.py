"""Full-screen view of a team build: who is working on what, what they are saying to each other, and what git is doing.

The engine reports events (see team/events.py); this screen only listens. Nothing here changes how the build runs, and quitting the screen
cancels the build cleanly (finished work stays in the branches)."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, RichLog, Static, TabbedContent, TabPane

from meetings.clipboard import CopyOnSelect, SelectableLog
from team.events import describe, describe_talk
from team.tui_desk import ApprovalScreen, InterruptScreen, NoteScreen

STYLES = {"info": "cyan", "ok": "green", "warn": "yellow", "bad": "bold red", "dim": "dim"}
STATUS_STYLES = {"waiting": "dim", "working": "yellow", "conflict": "bold yellow", "merged": "green", "failed": "bold red", "blocked": "red", "dropped": "dim strike"}
GIT_EVENTS = {"git-trouble", "git-fixed", "git-unfixed", "git-gave-up"}
# the sprint process, shown on its own tab as well as in the activity log
SPRINT_EVENTS = {"sprint-planned", "standup", "impediment", "sprint-review", "sprint-report", "sprint-retro", "doc-sync", "agile-docs", "feature-dropped", "feature-requeued",
                 "approval-requested", "approval-answered", "interrupted", "directive-handled", "resumed", "note", "agile-warning"}


class TeamApp(CopyOnSelect, App):
    TITLE = "Engineering Council — team build"
    CSS = """
    #side { width: 32%; min-width: 34; max-width: 62; border-right: solid $primary-darken-2; }
    /* narrow terminals: the side panel is tucked away (press b to bring it up), so the main area gets the whole width */
    #tabs { width: 1fr; }
    .compact #side { display: none; }
    .compact.show-side #side { display: block; width: 100%; max-width: 100%; min-width: 0; border-right: none; }
    .compact.show-side #tabs { display: none; }
    .side-title { background: $primary-darken-2; padding: 0 1; text-style: bold; }
    #status { padding: 0 1; height: auto; }
    #features { height: 1fr; }
    RichLog { padding: 0 1; }
    """
    BINDINGS = [
        Binding("q", "quit_build", "Quit"),
        Binding("ctrl+c", "copy_or_quit", "Copy", show=False, priority=True),
        Binding("a", "tab('activity')", "Activity"),
        Binding("c", "tab('talk')", "Conversations"),
        Binding("g", "tab('git')", "Git"),
        Binding("s", "tab('summary')", "Summary"),
        Binding("r", "tab('sprint')", "Sprint"),
        Binding("i", "interrupt", "Interrupt / speak"),
        Binding("n", "note", "Note"),
        Binding("p", "approvals", "Decisions waiting"),
        Binding("b", "toggle_side", "Panels"),
    ]

    def __init__(self, project: str = "") -> None:
        super().__init__()
        self.project = project
        self.engine: Any = None
        self.result: Any = None
        self.error: Optional[str] = None
        self.finished = False
        self.started = time.monotonic()
        self.status: dict[str, str] = {}
        self.counts = {"talk": 0, "git_trouble": 0, "git_fixed": 0, "conflicts": 0}
        self._worker = None
        self.sprint, self.goal, self.day, self.paused = 0, "", 0, False
        self.waiting: list[dict] = []  # decisions waiting for the human, oldest first
        self._asking = False  # a decision dialog is open

    # ---- layout
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="side"):
                yield Static("FEATURES", classes="side-title")
                yield DataTable(id="features", cursor_type="none", zebra_stripes=True)
                yield Static("STATUS", classes="side-title")
                yield Static("Starting…", id="status")
            with TabbedContent(id="tabs", initial="activity"):
                with TabPane("Activity", id="activity"):
                    yield SelectableLog(id="activity-log", wrap=True, markup=False, highlight=False, auto_scroll=True)
                with TabPane("Sprint", id="sprint"):
                    yield SelectableLog(id="sprint-log", wrap=True, markup=False, highlight=False, auto_scroll=True)
                with TabPane("Conversations", id="talk"):
                    yield SelectableLog(id="talk-log", wrap=True, markup=False, highlight=False, auto_scroll=True)
                with TabPane("Git", id="git"):
                    yield SelectableLog(id="git-log", wrap=True, markup=False, highlight=False, auto_scroll=True)
                with TabPane("Summary", id="summary"):
                    yield SelectableLog(id="summary-log", wrap=True, markup=False, highlight=False, auto_scroll=False)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#features", DataTable)
        table.add_column("Feature", key="id")
        table.add_column("Owner", key="owner")
        table.add_column("Status", key="status")
        table.add_column("Now", key="now")
        self.sub_title = self.project
        self.set_interval(1.0, self._tick)
        if self.engine is not None:
            self._worker = self.run_worker(self._go(), exclusive=True, name="build")

    def start(self, engine: Any) -> None:
        """Attach the engine; if the screen is already up, begin."""
        self.engine = engine
        if self.is_running:
            self._worker = self.run_worker(self._go(), exclusive=True, name="build")

    async def _go(self) -> None:
        try:
            self.result = await self.engine.run()
            self.finished = True
            self._show_summary()
        except Exception as exc:  # noqa: BLE001 - shown, not hidden
            self.error = f"{type(exc).__name__}: {exc}"
            self.finished = True
            self.log_line("bad", f"The build stopped: {self.error}")
        self._tick()

    # ---- events from the engine
    def handle(self, kind: str, data: dict) -> None:
        """Called by the engine for every event, on the same event loop as the screen."""
        try:
            self._handle(kind, data)
        except Exception:  # noqa: BLE001 - a display problem must never stop the build
            pass

    def _handle(self, kind: str, d: dict) -> None:
        if kind == "plan":
            table = self.query_one("#features", DataTable)
            for f in d["plan"]["features"]:
                self.status[f["id"]] = "waiting"
                table.add_row(f["id"], f["owner"] or "", Text("waiting", style="dim"), "", key=f["id"])
        elif kind == "feature-started":
            self._set(d["feature"], "working")
        elif kind == "feature-done":
            self._set(d["feature"], "merged", "")
        elif kind == "feature-failed":
            self._set(d["feature"], "failed", d.get("detail", "")[:18])
        elif kind == "feature-dropped":
            self._set(d["feature"], "dropped", "")
        elif kind == "feature-requeued":
            self._set(d["feature"], "waiting", "retry")
        elif kind == "sprint-planned":
            self.sprint, self.goal, self.day = d["sprint"], d["goal"], 0
        elif kind == "day-start":
            self.day = d["day"]
        elif kind == "gate-freeze":
            self.paused = True
        elif kind == "gate-thaw":
            self.paused = False
        elif kind == "approval-requested":
            self.waiting.append(d)
            self._ask_next()
        elif kind == "approval-answered":
            self.waiting = [w for w in self.waiting if w.get("id") != d.get("id")]
        elif kind == "feature-blocked":
            self._set(d["feature"], "blocked", "waiting on a failed one")
        elif kind == "task":
            self._note(d["feature"], f"task {d['index']}/{d['total']}")
        elif kind == "conflict":
            self.counts["conflicts"] += 1
            self._set(d["feature"], "conflict", ", ".join(d["files"])[:18])
        elif kind == "talk":
            self.counts["talk"] += 1
            style, text = describe_talk(d)
            self.write("talk-log", style, text)
            return
        if kind == "git-trouble":
            self.counts["git_trouble"] += 1
        elif kind == "git-fixed":
            self.counts["git_fixed"] += 1
        shown = describe(kind, d)
        if shown is not None:
            self.log_line(*shown)
            if kind in GIT_EVENTS:
                self.write("git-log", *shown)
            if kind in SPRINT_EVENTS:
                self.write("sprint-log", *shown)
        self._tick()

    def _set(self, feature: str, status: str, now: Optional[str] = None) -> None:
        table = self.query_one("#features", DataTable)
        self.status[feature] = status
        try:
            table.update_cell(feature, "status", Text(status, style=STATUS_STYLES.get(status, "")))
            if now is not None:
                table.update_cell(feature, "now", now)
        except Exception:  # noqa: BLE001 - a feature that was not in the plan
            pass

    def _note(self, feature: str, text: str) -> None:
        try:
            self.query_one("#features", DataTable).update_cell(feature, "now", text)
        except Exception:  # noqa: BLE001
            pass

    # ---- output
    def write(self, log_id: str, style: str, text: str) -> None:
        self.query_one(f"#{log_id}", RichLog).write(Text(text, style=STYLES.get(style, "")))

    def log_line(self, style: str, text: str) -> None:
        self.write("activity-log", style, text)

    def _tick(self) -> None:
        total = len(self.status)
        merged = sum(1 for s in self.status.values() if s == "merged")
        working = sum(1 for s in self.status.values() if s == "working")
        elapsed = int(time.monotonic() - self.started)
        phase = "finished" if self.finished else "paused" if self.paused else "building"
        lines = [
            f"{phase} · {elapsed // 60}m{elapsed % 60:02d}s",
            f"features: {merged}/{total} merged, {working} in progress",
            f"conflicts: {self.counts['conflicts']} · conversations: {self.counts['talk']}",
            f"git trouble: {self.counts['git_trouble']} (fixed: {self.counts['git_fixed']})",
        ]
        if self.sprint:
            lines.insert(1, f"sprint {self.sprint}, day {self.day}: {self.goal[:46]}")
        if self.waiting:
            lines.append(f"{len(self.waiting)} decision(s) waiting for you: press p")
        if not self.finished and self.agile_desk() is not None:
            lines.append("i: interrupt and speak · n: leave a note")
        if self.finished:
            lines.append("press q to leave, s for the summary")
        if self.has_class("compact"):  # the status panel is hidden, so the headline goes in the title bar
            self.sub_title = f"{self.project} · {lines[0]} · {lines[1]}"
        try:
            self.query_one("#status", Static).update("\n".join(lines))
        except Exception:  # noqa: BLE001 - before the screen is built
            pass

    def _show_summary(self) -> None:
        r = self.result
        log = self.query_one("#summary-log", RichLog)
        log.write(Text(f"{'Verification passed' if r.passed else 'NOT verified'} · {sum(1 for f in r.features if f.status == 'merged')}/{len(r.features)} features merged", style="bold"))
        if r.final_branch:
            log.write(Text(f"Review branch {r.final_branch}. Nothing was merged into main; that is yours to do.", style="green"))
        for f in r.features:
            log.write(Text(f"  {f.id} ({f.owner}): {f.status} — {f.summary}", style=STATUS_STYLES.get(f.status, "")))
        for dev, u in r.usage.items():
            log.write(Text(f"  {dev}: {int(u['input_tokens']):,} in / {int(u['output_tokens']):,} out", style="dim"))
        for w in r.warnings:
            log.write(Text(f"  ! {w}", style="yellow"))
        self.log_line("ok" if r.passed else "warn", "build finished — press s for the summary")

    # ---- responsive layout
    COMPACT_BELOW = 100  # columns

    def on_resize(self, event: Any) -> None:
        """A narrow terminal gets the single-column layout; a wide one shows the side panel next to the tabs."""
        narrow = event.size.width < self.COMPACT_BELOW
        self.set_class(narrow, "compact")
        if not narrow:
            self.remove_class("show-side")
        self._tick()

    def action_toggle_side(self) -> None:
        if self.has_class("compact"):
            self.toggle_class("show-side")

    # ---- the human
    def agile_desk(self) -> Any:
        agile = getattr(self.engine, "agile", None)
        return getattr(agile, "desk", None)

    def _ask_next(self) -> None:
        """Opens the dialog for the oldest decision that is waiting, unless one is already open."""
        desk = self.agile_desk()
        if self._asking or not self.waiting or desk is None:
            return
        item = self.waiting[0]
        self._asking = True

        def answered(result) -> None:
            self._asking = False
            if result is not None:
                approved, text = result
                try:
                    desk.answer(item["id"], approved, text)
                except KeyError:
                    pass
                self.waiting = [w for w in self.waiting if w.get("id") != item["id"]]
            else:  # decided later: it stays in the list, at the back, until asked for with p
                self.waiting = self.waiting[1:] + self.waiting[:1]
                self._tick()
                return
            self._ask_next()

        self.push_screen(ApprovalScreen(item), answered)

    def action_approvals(self) -> None:
        self._ask_next()

    def action_interrupt(self) -> None:
        if self.agile_desk() is None or self.finished:
            self.notify("Interrupting needs a sprint run that is in progress.", severity="warning")
            return
        self.run_worker(self._interrupt(), exclusive=False, name="interrupt")

    async def _interrupt(self) -> None:
        desk = self.agile_desk()
        info = await desk.interrupt()
        status = {**desk.status(), "late": info.get("late", [])}
        self.push_screen(InterruptScreen(desk, status))

    def action_note(self) -> None:
        desk = self.agile_desk()
        if desk is None or self.finished:
            self.notify("Notes need a sprint run that is in progress.", severity="warning")
            return

        def saved(text) -> None:
            if text:
                desk.note(text)

        self.push_screen(NoteScreen(), saved)

    # ---- actions
    def action_tab(self, name: str) -> None:
        self.query_one("#tabs", TabbedContent).active = name

    async def action_copy_or_quit(self) -> None:
        """Ctrl+C copies the selection; with nothing selected it stops the build, as before."""
        if not self.copy_selection():
            await self.action_quit_build()

    async def action_quit_build(self) -> None:
        if self._worker is not None and not self.finished:
            self._worker.cancel()  # the engine closes its harnesses and agents on the way out
        self.exit(return_code=0 if (self.result is not None and self.result.passed) else 2)


def run_team_tui(make_engine: Callable[[Callable[[str, dict], None]], Any], project: str = "") -> TeamApp:
    """Shows the screen and runs the build inside it. `make_engine(on_event)` builds the engine wired to the screen."""
    app = TeamApp(project)
    app.start(make_engine(app.handle))
    app.run()
    return app
