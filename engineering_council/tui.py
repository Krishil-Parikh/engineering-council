"""Full-screen terminal UI: watch every member think, write, argue and decide, live."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional

from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Markdown,
    OptionList,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from engineering_council import questions as questions_mod
from engineering_council.config import Settings
from engineering_council.gemini_client import LLM, LLMError, LLMEvent
from engineering_council.meeting import (
    TOTAL_STAGES,
    MeetingError,
    MeetingResult,
    Reporter,
    meeting_dir,
    run_meeting,
)
from engineering_council.models import AGENT_IDS, SCRUM_MASTER, Answer, HumanQuestion, MeetingInput

STAGE_NAMES = ["Inspect", "Blind thinking", "Skill lens", "Conversation", "Questions", "Rethink", "Decisions", "Specification", "Design review", "Verify"]
ACTORS = (*AGENT_IDS, SCRUM_MASTER)
COLORS = {
    "DEV_1": "cyan",
    "DEV_2": "magenta",
    "DEV_3": "green",
    "DEV_4": "red",
    "DEV_5": "blue",
    "DEV_6": "bright_cyan",
    SCRUM_MASTER: "yellow",
    "COUNCIL": "white",
}
TAB_TITLES = {**{a: a.replace("_", " ").title() for a in AGENT_IDS}, SCRUM_MASTER: "Scrum Master"}
STREAM_CAP = 60_000
DOC_KEYS = {"p": "PRD.md", "t": "Technical_Approach.md", "d": "Design.md", "m": "minutes.md", "v": "verification_report.md"}


def actor_of(stage: str) -> str:
    """Which member a model call belongs to (stage names look like 'talk2:DEV_3', 'blind:DEV_1' or 'scrum:check1')."""
    if ":" in stage:
        who = stage.split(":", 1)[1]
        return who if who in ACTORS else SCRUM_MASTER
    return SCRUM_MASTER


def _color(who: str) -> str:
    return COLORS.get(who, "white")


# --------------------------------------------------------------------------- reporter


class TuiReporter(Reporter):
    """Routes everything the meeting reports into the app's widgets."""

    def __init__(self, app: "CouncilApp", auto_answers: bool) -> None:
        super().__init__(verbose=True, out=lambda text: None)
        self.app, self.auto_answers = app, auto_answers

    def stage(self, n: int, label: str) -> None:
        self.app.set_stage(n, label)

    def say(self, who: str, text: str) -> None:
        self.app.feed_line(Text.assemble((f"{who}: ", f"bold {_color(who)}"), text))

    def publish(self, kind: str, who: str, title: str, body: str) -> None:
        if kind == "talk":
            head, _, text = body.partition("\n")
            self.app.feed_line(Text.assemble((head + "\n", f"bold {_color(who)}"), text + "\n"))
        else:
            self.app.feed_panel(kind, who, title, body)

    def roster(self, skills: dict[str, str]) -> None:
        self.app.set_roster(skills)

    def note(self, text: str) -> None:
        self.app.feed_line(Text(text, style="dim"))

    def warn(self, text: str) -> None:
        self.app.feed_line(Text("! " + text, style="bold yellow"))
        self.app.activity(Text("! " + text, style="yellow"))

    def debug(self, text: str) -> None:
        self.app.activity(Text(text, style="dim"))

    def llm_event(self, ev: LLMEvent) -> None:
        self.app.on_llm(ev)

    async def ask(self, questions: list[HumanQuestion], interactive: bool, input_fn) -> list[Answer]:
        if self.auto_answers or not interactive:
            return questions_mod.ask(questions, interactive=False)
        answers = []
        for i, q in enumerate(questions, 1):
            answers.append(await self.app.ask_one(q, i, len(questions)))
        return answers


# --------------------------------------------------------------------------- screens


class QuestionScreen(ModalScreen[Answer]):
    """One product question. Enter on the pre-selected recommendation accepts the default."""

    BINDINGS = [Binding("escape", "default", "Accept default")]

    def __init__(self, q: HumanQuestion, index: int, total: int) -> None:
        super().__init__()
        self.q, self.index, self.total = q, index, total

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"Question {self.index}/{self.total}", id="q-count")
            yield Static(self.q.question, id="q-text")
            yield Static(f"Why it matters: {self.q.why_it_matters}", id="q-why")
            options = [f"{o}   (recommended)" if o == self.q.recommended_default else o for o in self.q.options]
            yield OptionList(*options, "✎  Custom answer…", id="q-options")
            yield Input(placeholder="Type your answer and press Enter", id="q-custom")
            yield Label("↑/↓ choose · Enter confirm · Esc accept the recommended default", id="q-hint")

    def on_mount(self) -> None:
        self.query_one("#q-custom").display = False
        opts = self.query_one(OptionList)
        if self.q.recommended_default in self.q.options:
            opts.highlighted = self.q.options.index(self.q.recommended_default)
        opts.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if idx == len(self.q.options):
            box = self.query_one("#q-custom", Input)
            box.display = True
            box.focus()
            return
        chosen = self.q.options[idx]
        source = "default" if chosen == self.q.recommended_default else "option"
        self.dismiss(Answer(question=self.q.question, answer=chosen, source=source))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            self.dismiss(Answer(question=self.q.question, answer=text, source="custom"))

    def action_default(self) -> None:
        self.dismiss(Answer(question=self.q.question, answer=self.q.recommended_default, source="default"))


class StartScreen(ModalScreen[MeetingInput]):
    """Collects the meeting inputs when they were not given on the command line."""

    BINDINGS = [Binding("ctrl+s", "start", "Start meeting")]

    def __init__(self, base_output: str, prefill: Optional[MeetingInput] = None) -> None:
        super().__init__()
        self.base_output, self.prefill = base_output, prefill

    def compose(self) -> ComposeResult:
        p = self.prefill
        with VerticalScroll(id="start-form"):
            yield Label("Engineering Council — New Meeting", id="start-title")
            yield Label("Project name")
            yield Input(value=p.project_name if p else "", id="f-name")
            yield Label("Problem statement file (optional — or type it below)")
            yield Input(placeholder="e.g. problem.md", id="f-file")
            yield Label("Problem statement")
            yield TextArea(p.problem if p else "", id="f-problem")
            yield Label("Repository path or public GitHub URL (optional)")
            yield Input(value=(p.repo_path or p.github_url or "") if p else "", id="f-repo")
            yield Label("Constraints (comma separated, optional)")
            yield Input(value=", ".join(p.constraints) if p else "", id="f-constraints")
            yield Static("The problem statement and repository excerpts are sent to the Gemini API.", id="start-note")
            yield Static("", id="start-error")
            yield Button("Start meeting  (Ctrl+S)", variant="success", id="start-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_start()

    def action_start(self) -> None:
        try:
            self.dismiss(self._collect())
        except MeetingError as exc:
            self.query_one("#start-error", Static).update(Text(str(exc), style="bold red"))

    def _collect(self) -> MeetingInput:
        name = self.query_one("#f-name", Input).value.strip()
        problem = self.query_one("#f-problem", TextArea).text.strip()
        file = self.query_one("#f-file", Input).value.strip()
        if file:
            try:
                problem = Path(file).expanduser().read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise MeetingError(f"Cannot read {file!r}: {exc.strerror or exc}") from exc
        if not name:
            raise MeetingError("A project name is required.")
        if not problem:
            raise MeetingError("A problem statement is required.")
        repo = self.query_one("#f-repo", Input).value.strip()
        is_url = repo.lower().startswith(("http://", "https://"))
        if repo and not is_url and not Path(repo).expanduser().is_dir():
            raise MeetingError(f"Repository path is not a directory: {repo}")
        raw = self.query_one("#f-constraints", Input).value
        return MeetingInput(
            project_name=name,
            problem=problem,
            constraints=[c.strip() for c in raw.split(",") if c.strip()],
            repo_path=repo if repo and not is_url else None,
            github_url=repo if is_url else None,
            output_dir=self.base_output,
        )


# --------------------------------------------------------------------------- app


class CouncilApp(App):
    TITLE = "Engineering Council"
    CSS = """
    #side { width: 38; border-right: solid $primary-darken-2; padding: 0 1; }
    .side-title { text-style: bold; color: $accent; margin-top: 1; }
    #stages { height: auto; }
    #agents { height: auto; max-height: 12; }
    .stream { padding: 0 1; }
    #docs-view { padding: 0 1; }
    QuestionScreen, StartScreen { align: center middle; }
    #dialog { width: 86%; max-width: 110; height: auto; max-height: 90%; border: thick $accent; background: $surface; padding: 1 2; }
    #q-count { color: $accent; text-style: bold; }
    #q-text { text-style: bold; margin: 1 0; }
    #q-why { color: $text-muted; margin-bottom: 1; }
    #q-options { height: auto; max-height: 12; margin-bottom: 1; }
    #q-hint { color: $text-muted; margin-top: 1; }
    #start-form { width: 90%; max-width: 110; height: 90%; border: thick $accent; background: $surface; padding: 1 2; }
    #start-title { text-style: bold; color: $accent; margin-bottom: 1; }
    #f-problem { height: 8; }
    #start-note { color: $text-muted; margin: 1 0; }
    """
    BINDINGS = [
        Binding("q", "quit_app", "Quit"),
        Binding("f", "tab('feed')", "Feed"),
        Binding("1", "tab('DEV_1')", "Dev 1"),
        Binding("2", "tab('DEV_2')", "Dev 2"),
        Binding("3", "tab('DEV_3')", "Dev 3"),
        Binding("4", "tab('DEV_4')", "Dev 4"),
        Binding("5", "tab('DEV_5')", "Dev 5"),
        Binding("6", "tab('DEV_6')", "Dev 6"),
        Binding("7", "tab('SCRUM_MASTER')", "Scrum"),
        Binding("l", "tab('activity')", "Activity"),
        Binding("p", "doc('p')", "PRD"),
        Binding("t", "doc('t')", "Tech"),
        Binding("d", "doc('d')", "Design"),
        Binding("m", "doc('m')", "Minutes"),
        Binding("v", "doc('v')", "Verify"),
    ]

    def __init__(
        self,
        settings: Settings,
        llm: LLM,
        inp: Optional[MeetingInput] = None,
        *,
        base_output: str = "output",
        auto_answers: bool = False,
        resume: bool = False,
    ) -> None:
        super().__init__()
        self.settings, self.llm, self.inp = settings, llm, inp
        self.base_output, self.auto_answers, self.resume = base_output, auto_answers, resume
        self.reporter = TuiReporter(self, auto_answers)
        self.result: Optional[MeetingResult] = None
        self.error: Optional[str] = None
        self.stage_n = 0
        self.stage_label = ""
        self.finished = False
        self.actors: dict[str, dict] = {a: {"state": "idle", "chars": 0, "t0": 0.0, "calls": 0} for a in ACTORS}
        self.streams: dict[str, Text] = {a: Text() for a in ACTORS}
        self._dirty: set[str] = set()
        self.out_dir: Optional[Path] = None

    # ---- layout
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="side"):
                yield Static("STAGES", classes="side-title")
                yield Static(id="stages")
                yield Static("COUNCIL", classes="side-title")
                yield DataTable(id="agents", cursor_type="none", zebra_stripes=True)
                yield Static("STATUS", classes="side-title")
                yield Static("Starting…", id="status")
            with TabbedContent(id="tabs", initial="feed"):
                with TabPane("Feed", id="feed"):
                    yield RichLog(id="feed-log", wrap=True, markup=False, highlight=False, auto_scroll=True)
                for a in ACTORS:
                    with TabPane(TAB_TITLES[a], id=a):
                        with VerticalScroll(id=f"scroll-{a}"):
                            yield Static(Text("Waiting for this member to speak…", style="dim"), id=f"stream-{a}", classes="stream")
                with TabPane("Activity", id="activity"):
                    yield RichLog(id="activity-log", wrap=True, markup=False, highlight=False, auto_scroll=True)
                with TabPane("Documents", id="docs"):
                    with VerticalScroll(id="docs-scroll"):
                        yield Markdown("*Documents appear here when the meeting finishes. Press p / t / d / m / v.*", id="docs-view")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#agents", DataTable)
        table.add_column("Member", key="who", width=20)
        table.add_column("State", key="state", width=14)
        table.add_column("Out", key="chars", width=6)
        for a in ACTORS:
            table.add_row(Text(TAB_TITLES[a], style=f"bold {_color(a)}"), "idle", "0", key=a)
        self._render_stages()
        self.set_interval(0.2, self._flush_streams)
        self.set_interval(1.0, self._tick)
        if self.inp is not None:
            self._launch(self.inp)
        else:
            self.push_screen(StartScreen(self.base_output), self._launch)

    # ---- starting the meeting
    def _launch(self, inp: Optional[MeetingInput]) -> None:
        if inp is None:
            self.exit()
            return
        self.inp = inp
        self.out_dir = meeting_dir(inp)
        self.sub_title = f"{inp.project_name} · {self.settings.model}"
        self.set_status(f"Running → {self.out_dir}")
        self.feed_line(Text(f"Meeting: {inp.project_name}", style="bold"))
        self.feed_line(Text(f"Problem: {inp.problem[:400]}{'…' if len(inp.problem) > 400 else ''}", style="dim"))
        self.run_worker(self._go(inp), exclusive=True, name="meeting")

    async def _go(self, inp: MeetingInput) -> None:
        try:
            self.result = await run_meeting(
                inp, self.settings, self.llm, self.reporter, interactive=not self.auto_answers, resume=self.resume
            )
            ok = self.result.report.passed
            self.feed_rule("MEETING COMPLETE" if ok else "MEETING FINISHED — VERIFICATION FAILED")
            for name in ("PRD.md", "Technical_Approach.md", "Design.md", "minutes.md", "verification_report.md"):
                self.feed_line(Text(f"  {self.result.out_dir / name}", style="green" if ok else "yellow"))
            self.feed_line(Text("Press p / t / d / m / v to read the documents here, q to quit.", style="bold"))
            self.set_status("Complete ✔" if ok else "Done, but verification failed ✘ (press v)")
            self.show_doc("PRD.md")
        except (MeetingError, LLMError) as exc:
            self.error = str(exc)
            self.feed_panel("error", "COUNCIL", "The meeting stopped", str(exc))
            hint = f"Completed work is saved. Continue with:  python -m engineering_council resume \"{self.out_dir}\""
            self.feed_line(Text(hint, style="bold yellow"))
            self.set_status("Stopped ✘ — see Feed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # never lose the screen to a bug: show it
            self.error = f"{type(exc).__name__}: {exc}"
            self.feed_panel("error", "COUNCIL", "Unexpected error", self.error)
            self.set_status("Crashed ✘ — see Feed")
        finally:
            self.finished = True
            for a in ACTORS:
                if self.actors[a]["state"] in ("waiting", "writing", "thinking", "retrying"):
                    self._set_state(a, "stopped")

    # ---- feed / activity
    def _log(self, widget_id: str) -> RichLog:
        return self.query_one(widget_id, RichLog)

    def feed_line(self, renderable) -> None:
        self._log("#feed-log").write(renderable)

    def feed_rule(self, title: str) -> None:
        self._log("#feed-log").write(Rule(title, style="bold"))

    def feed_panel(self, kind: str, who: str, title: str, body: str) -> None:
        color = _color(who)
        self._log("#feed-log").write(
            Panel(Text(body or title), title=f"[bold {color}]{who}[/] · {kind}", subtitle=Text(title[:90], style="dim"), border_style=color),
            expand=True,
        )

    def activity(self, renderable) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._log("#activity-log").write(Text.assemble((stamp + " ", "dim"), renderable))

    def set_roster(self, skills: dict[str, str]) -> None:
        """Developers have picked their skills: show them on the tabs and in the council table."""
        from engineering_council.prompts import skill_label

        for agent, skill in skills.items():
            label = f"{agent.replace('_', ' ').title()} · {skill_label(skill)}"
            TAB_TITLES[agent] = label
            try:
                self.query_one(TabbedContent).get_tab(agent).label = label
            except Exception:
                pass
            try:
                self.query_one("#agents", DataTable).update_cell(agent, "who", Text(label, style=f"bold {_color(agent)}"))
            except Exception:
                pass
            self.feed_line(Text(f"{agent} takes the {skill_label(skill)} skill", style=f"bold {_color(agent)}"))

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    # ---- stages
    def set_stage(self, n: int, label: str) -> None:
        self.stage_n, self.stage_label = n, label
        self._render_stages()
        self.feed_rule(f"[{n}/{TOTAL_STAGES}] {label}")

    def _render_stages(self) -> None:
        text = Text()
        for i, name in enumerate(STAGE_NAMES, 1):
            if i < self.stage_n or (self.finished and self.error is None and self.stage_n):
                text.append(f" ✔ {i}. {name}\n", style="green")
            elif i == self.stage_n:
                text.append(f" ▶ {i}. {name}\n", style="bold yellow")
            else:
                text.append(f"   {i}. {name}\n", style="dim")
        self.query_one("#stages", Static).update(text)

    # ---- live model activity
    def on_llm(self, ev: LLMEvent) -> None:
        who = actor_of(ev.stage)
        if who not in self.actors:
            who = SCRUM_MASTER
        a = self.actors[who]
        stream = self.streams[who]
        if ev.kind == "start":
            a["t0"], a["calls"] = time.monotonic(), a["calls"] + 1
            self._set_state(who, "waiting")
            head = f"\n── {ev.stage} · attempt {ev.attempt} · {ev.info} ──\n"
            self._append(who, head, f"bold {_color(who)}")
            self.activity(Text(f"{ev.stage}: request sent (attempt {ev.attempt}, {ev.info})", style=_color(who)))
        elif ev.kind == "thought":
            self._set_state(who, "thinking")
            a["chars"] += len(ev.text)
            self._append(who, ev.text, "italic dim")
        elif ev.kind == "chunk":
            self._set_state(who, "writing")
            a["chars"] += len(ev.text)
            self._append(who, ev.text, "")
        elif ev.kind == "retry":
            self._set_state(who, "retrying")
            self._append(who, f"\n↻ {ev.info}\n", "bold yellow")
            self.activity(Text(f"{ev.stage}: {ev.info}", style="yellow"))
        elif ev.kind == "done":
            self._set_state(who, "done")
            self._append(who, f"\n✔ {ev.info}\n", "bold green")
            self.activity(Text(f"{ev.stage}: finished ({ev.info})", style="green"))
        elif ev.kind == "error":
            self._set_state(who, "failed")
            self._append(who, f"\n✘ {ev.info}\n", "bold red")
            self.activity(Text(f"{ev.stage}: FAILED — {ev.info}", style="bold red"))

    def _append(self, who: str, text: str, style: str) -> None:
        buf = self.streams[who]
        buf.append(text, style=style or None)
        if len(buf) > STREAM_CAP:
            self.streams[who] = buf[-int(STREAM_CAP * 0.75):]
        self._dirty.add(who)

    def _flush_streams(self) -> None:
        for who in list(self._dirty):
            self.query_one(f"#stream-{who}", Static).update(self.streams[who])
            self.query_one(f"#scroll-{who}", VerticalScroll).scroll_end(animate=False)
        self._dirty.clear()

    def _set_state(self, who: str, state: str) -> None:
        self.actors[who]["state"] = state
        self._refresh_row(who)

    def _refresh_row(self, who: str) -> None:
        a = self.actors[who]
        icon = {"idle": "·", "waiting": "⏳", "thinking": "💭", "writing": "✍", "retrying": "↻", "done": "✔", "failed": "✘", "stopped": "■"}[a["state"]]
        elapsed = f" {int(time.monotonic() - a['t0'])}s" if a["state"] in ("waiting", "thinking", "writing", "retrying") else ""
        style = {"done": "green", "failed": "red", "retrying": "yellow", "writing": "bold", "stopped": "dim"}.get(a["state"], "")
        table = self.query_one("#agents", DataTable)
        table.update_cell(who, "state", Text(f"{icon} {a['state']}{elapsed}", style=style))
        table.update_cell(who, "chars", str(a["chars"]))

    def _tick(self) -> None:
        for who, a in self.actors.items():
            if a["state"] in ("waiting", "thinking", "writing", "retrying"):
                self._refresh_row(who)

    # ---- human questions
    async def ask_one(self, q: HumanQuestion, index: int, total: int) -> Answer:
        self.set_status("Waiting for your answer…")
        self.feed_panel("question", "COUNCIL", q.question, f"{q.question}\n\nWhy it matters: {q.why_it_matters}\nOptions: {', '.join(q.options)}\nRecommended: {q.recommended_default}")
        fut: asyncio.Future[Answer] = asyncio.get_running_loop().create_future()
        self.push_screen(QuestionScreen(q, index, total), lambda r: fut.done() or fut.set_result(r))
        ans = await fut
        self.feed_line(Text.assemble(("You answered: ", "bold"), f"{ans.answer} ({ans.source})"))
        self.set_status("Running…")
        return ans

    # ---- documents / navigation
    def show_doc(self, name: str) -> bool:
        if not self.out_dir:
            return False
        try:
            text = (self.out_dir / name).read_text(encoding="utf-8")
        except OSError:
            return False
        self.query_one("#docs-view", Markdown).update(text)
        self.query_one("#docs-scroll", VerticalScroll).scroll_home(animate=False)
        self.query_one("#tabs", TabbedContent).active = "docs"
        return True

    def action_doc(self, key: str) -> None:
        if not self.show_doc(DOC_KEYS[key]):
            self.notify(f"{DOC_KEYS[key]} does not exist yet.", severity="warning")

    def action_tab(self, tab_id: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab_id

    def action_quit_app(self) -> None:
        if isinstance(self.screen, (QuestionScreen, StartScreen)):
            return  # don't let a stray key drop a question the meeting is waiting on
        self.workers.cancel_all()
        self.exit()


def run_tui(settings: Settings, llm: LLM, inp: Optional[MeetingInput], *, base_output: str, auto_answers: bool, resume: bool = False) -> CouncilApp:
    app = CouncilApp(settings, llm, inp, base_output=base_output, auto_answers=auto_answers, resume=resume)
    app.run()
    return app
