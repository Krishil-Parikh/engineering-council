"""The human's dialogs in the team screen: decide something, interrupt the team and speak to it, leave a note for the next standup.

These only call the `HumanDesk` (team/agile/desk.py); they hold no logic of their own, so a web front end can offer the same three actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, RichLog, Static

DIALOG_CSS = """
ApprovalScreen, InterruptScreen, NoteScreen { align: center middle; }
#dialog { width: 110; max-width: 96%; height: auto; max-height: 92%; border: thick $primary; background: $surface; padding: 1 2; }
#dialog-title { text-style: bold; padding-bottom: 1; }
#dialog-body { height: auto; max-height: 24; border: round $primary-darken-2; padding: 0 1; }
#dialog-log { height: 10; border: round $primary-darken-2; margin: 1 0; }
#dialog Input { margin: 1 0; }
#dialog Horizontal { height: auto; align-horizontal: right; }
#dialog Button { margin-left: 2; }
"""

KINDS = ("note", "scope", "rethink")


def read_documents(detail: str, limit: int = 60_000) -> str:
    """For a documents approval, the full text of the files the detail names (paths on lines starting with '- ')."""
    parts = []
    for line in detail.splitlines():
        if line.startswith("- "):
            path = Path(line[2:].strip())
            try:
                parts.append(f"━━ {path.name} ━━\n{path.read_text(encoding='utf-8')}")
            except OSError:
                continue
    return "\n\n".join(parts)[:limit]


def parse_spoken(text: str) -> tuple[str, str | None]:
    """'/scope drop the admin panel' -> ('drop the admin panel', 'scope'). Without a prefix the scrum master classifies it."""
    text = text.strip()
    for kind in KINDS:
        if text.lower().startswith(f"/{kind} "):
            return text[len(kind) + 2:].strip(), kind
    return text, None


class ApprovalScreen(ModalScreen):
    """Something the team needs the human to decide. Dismisses with (approved, feedback)."""

    DEFAULT_CSS = DIALOG_CSS
    BINDINGS = [("escape", "later", "Decide later")]

    def __init__(self, item: dict[str, Any]) -> None:
        super().__init__()
        self.item = item

    def compose(self) -> ComposeResult:
        detail = self.item.get("detail", "")
        body = read_documents(detail) if self.item.get("kind") == "docs" else ""
        with Vertical(id="dialog"):
            yield Static(f"{self.item.get('title', 'Decision needed')}", id="dialog-title")
            with VerticalScroll(id="dialog-body"):
                yield Static(Text(body or detail), id="dialog-detail")
            yield Input(placeholder="If you decline: what should change?  (optional)", id="feedback")
            with Horizontal():
                yield Button("Decide later (Esc)", id="later")
                yield Button("Decline", variant="error", id="decline")
                yield Button("Approve", variant="success", id="approve")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "later":
            self.dismiss(None)
        else:
            self.dismiss((event.button.id == "approve", self.query_one("#feedback", Input).value.strip()))

    def action_later(self) -> None:
        self.dismiss(None)


class InterruptScreen(ModalScreen):
    """The team is paused. Speak to it as often as you like; work resumes when you press Resume."""

    DEFAULT_CSS = DIALOG_CSS
    BINDINGS = [("escape", "resume", "Resume work")]

    def __init__(self, desk: Any, status: dict[str, Any]) -> None:
        super().__init__()
        self.desk, self.status = desk, status

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("The team is paused", id="dialog-title")
            with VerticalScroll(id="dialog-body"):
                yield Static(Text(self.describe()), id="dialog-detail")
            yield RichLog(id="dialog-log", wrap=True, markup=False)
            yield Input(placeholder="Tell the team (Enter to send). Prefix /note, /scope or /rethink to say what kind, or just write.", id="spoken")
            with Horizontal():
                yield Button("Resume work (Esc)", variant="success", id="resume")

    def describe(self) -> str:
        s = self.status
        lines = [f"phase: {s.get('phase')} · sprint {s.get('sprint')} · day {s.get('day')}", f"goal: {s.get('goal') or '-'}"]
        for dev in s.get("workers", []):
            lines.append(f"  {dev}: {s.get('resting', {}).get(dev, 'working')}")
        for text in s.get("open_impediments", []):
            lines.append(f"  impediment: {text}")
        late = s.get("late") or []
        if late:
            lines.append(f"  still finishing a step: {', '.join(late)}")
        return "\n".join(lines)

    def on_mount(self) -> None:
        self.query_one("#spoken", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text, kind = parse_spoken(event.value)
        event.input.value = ""
        if not text:
            return
        log = self.query_one("#dialog-log", RichLog)
        log.write(Text(f"you: {text}", style="bold"))
        log.write(Text("the scrum master is working on it…", style="dim"))
        self.run_worker(self._say(text, kind), exclusive=False)

    async def _say(self, text: str, kind: str | None) -> None:
        log = self.query_one("#dialog-log", RichLog)
        try:
            directive = await self.desk.say(text, kind)
            log.write(Text(f"{directive.kind}: {directive.effect}", style="green"))
        except Exception as exc:  # noqa: BLE001 - shown to the person, who can try again
            log.write(Text(f"could not be applied: {exc}", style="red"))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        await self.action_resume()

    async def action_resume(self) -> None:
        await self.desk.release()
        self.dismiss(None)


class NoteScreen(ModalScreen):
    """A note for the next standup; the team does not stop."""

    DEFAULT_CSS = DIALOG_CSS
    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Note for the next standup (the team keeps working)", id="dialog-title")
            yield Input(placeholder="What should the team know?  Enter to send, Esc to cancel", id="note")

    def on_mount(self) -> None:
        self.query_one("#note", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)
