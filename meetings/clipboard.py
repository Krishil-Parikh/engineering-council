"""Selecting text in a full-screen view and copying it, the way opencode and Claude Code do.

Drag with the mouse over any text (the conversation, a document, a decision dialog) and it is copied the moment you let go; Ctrl+C copies the
current selection too. Textual does the selecting; this adds the copying:

  1. the terminal's clipboard escape sequence (OSC 52), which most modern terminals honour, including over SSH, and
  2. the operating system's own clipboard command (PowerShell on Windows, pbcopy on macOS, wl-copy/xclip/xsel on Linux) for terminals that
     ignore the sequence. Both are tried; a failure of either is silent, because copying is a convenience and must never break the screen."""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from typing import Optional


def native_command() -> Optional[list[str]]:
    """The command that puts its standard input on the system clipboard, or None."""
    if sys.platform == "win32":
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if shell:
            return [shell, "-NoProfile", "-NonInteractive", "-Command", "[Console]::InputEncoding=[Text.Encoding]::UTF8; Set-Clipboard -Value ([Console]::In.ReadToEnd())"]
        return None
    if sys.platform == "darwin":
        return ["pbcopy"] if shutil.which("pbcopy") else None
    for candidate in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if shutil.which(candidate[0]):
            return candidate
    return None


def native_copy(text: str) -> None:
    """Puts text on the system clipboard without blocking the screen."""
    command = native_command()
    if command is None:
        return

    def run() -> None:
        try:
            subprocess.run(command, input=text.encode("utf-8"), capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass

    threading.Thread(target=run, daemon=True).start()


class CopyOnSelect:
    """Mixin for a Textual App: copy what the mouse selected as soon as the button is released, and on Ctrl+C."""

    _last_copied: str = ""

    def on_mouse_up(self, event) -> None:
        self.set_timer(0.05, self.copy_selection)  # the selection settles just after the button comes up

    def copy_selection(self) -> bool:
        """Copies the selected text, if any. Returns whether something was copied."""
        try:
            text = self.screen.get_selected_text()
        except Exception:  # noqa: BLE001 - a screen without selectable content
            return False
        if not text or not text.strip():
            return False
        if text == self._last_copied:  # the same selection is not announced again by every later click
            return True
        self._last_copied = text
        try:
            self.copy_to_clipboard(text)
        except Exception:  # noqa: BLE001
            pass
        native_copy(text)
        self.notify(f"Copied {len(text):,} characters", timeout=1.5)
        return True

    def action_copy_selection(self) -> None:
        if not self.copy_selection():
            self.notify("Select text with the mouse first (drag over it); it is copied when you let go.", timeout=3)


def _selectable_log():
    """Built lazily so importing this module does not require Textual."""
    from rich.cells import cell_len  # noqa: F401
    from textual.strip import Strip
    from textual.widgets import RichLog

    class SelectableLog(RichLog):
        """A RichLog whose text can be selected with the mouse (highlighted while dragging) and copied. Textual's own RichLog cannot."""

        def plain_lines(self) -> list[str]:
            return ["".join(segment.text for segment in strip).rstrip() for strip in self.lines]

        def get_selection(self, selection):
            return selection.extract("\n".join(self.plain_lines())), "\n"

        def selection_updated(self, selection) -> None:
            self._line_cache.clear()
            self.refresh()

        def _render_line(self, y: int, scroll_x: int, width: int):
            strip = super()._render_line(y, scroll_x, width)
            selection = self.text_selection
            if selection is None or y >= len(self.lines):
                return strip
            span = selection.get_span(y)
            if span is None:
                return strip
            start, end = span
            start, end = max(0, start - scroll_x), width if end == -1 else min(width, end - scroll_x)
            if end <= start:
                return strip
            style = self.screen.get_component_rich_style("screen--selection")
            return Strip.join([strip.crop(0, start), strip.crop(start, end).apply_style(style), strip.crop(end, width)])

    return SelectableLog


def __getattr__(name: str):
    if name == "SelectableLog":
        value = _selectable_log()
        globals()["SelectableLog"] = value
        return value
    raise AttributeError(name)
