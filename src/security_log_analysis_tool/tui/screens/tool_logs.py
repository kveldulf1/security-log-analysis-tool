"""Tool logs screen: a modal prompts for a minimum level, then the JSON log is
filtered to it.

DEBUG is gated behind ``Permission.VIEW_ALL_TOOL_LOGS`` (admin) — an analyst
choosing DEBUG gets a validation message and stays on the prompt rather than
being shown a level they aren't entitled to. Reading and filtering the log
file is real (potentially large) file I/O, so it runs on a worker thread and
hands the result back via ``app.call_from_thread``.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, RichLog, Static

from ...auth.authz import AuthorizationError, has_permission, require
from ...models import Permission

if TYPE_CHECKING:
    from ..app import SLATApp

_LEVELS: tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_LEVEL_VALUES: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
_MAX_LINES = 500


class LogLevelPromptScreen(ModalScreen[str | None]):
    """Modal: pick the minimum log level to display."""

    def compose(self) -> ComposeResult:
        with Vertical(id="level-box"):
            yield Static("Minimum log level to show:", id="title")
            yield Static("", id="level-prompt-error", classes="error")
            for level in _LEVELS:
                yield Button(level, id=f"level-{level.lower()}")
            yield Button("Cancel", id="level-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "level-cancel":
            self.dismiss(None)
            return

        level = (button_id or "").removeprefix("level-").upper()
        app: SLATApp = self.app  # type: ignore[assignment]
        assert app.principal is not None  # only reachable after login

        needs_admin = level == "DEBUG" and not has_permission(
            app.principal.role, Permission.VIEW_ALL_TOOL_LOGS
        )
        if needs_admin:
            self.query_one("#level-prompt-error", Static).update(
                "DEBUG requires VIEW_ALL_TOOL_LOGS (admin). Choose another level."
            )
            return
        self.dismiss(level)


class ToolLogsScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        with Vertical(id="logs-box"):
            yield Static("Tool logs", id="title")
            yield Static("", id="logs-error", classes="error")
            yield RichLog(id="logs-view", wrap=False, markup=False)
            yield Button("Change level", id="change-level")
            yield Button("Back", id="back")
        yield Footer()

    def on_mount(self) -> None:
        app: SLATApp = self.app  # type: ignore[assignment]
        error = self.query_one("#logs-error", Static)
        assert app.principal is not None  # only reachable after login
        try:
            require(app.principal, Permission.VIEW_OWN_TOOL_LOGS)
        except AuthorizationError as exc:
            error.update(str(exc))
            return
        self._prompt_for_level()

    def _prompt_for_level(self) -> None:
        app: SLATApp = self.app  # type: ignore[assignment]
        app.push_screen(LogLevelPromptScreen(), self._level_chosen)

    def _level_chosen(self, level: str | None) -> None:
        if level is None:
            return
        self.query_one("#logs-error", Static).update(f"Showing {level} and above…")
        self._load_logs(level)

    @work(thread=True, exclusive=True)
    def _load_logs(self, level: str) -> None:
        app: SLATApp = self.app  # type: ignore[assignment]
        threshold = _LEVEL_VALUES[level]

        if app.log_paths is None:
            app.call_from_thread(self._show_error, "Tool logs are not available in this session.")
            return

        try:
            raw_lines = app.log_paths.json.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            app.call_from_thread(self._show_error, f"Could not read log file: {exc}")
            return

        lines: list[str] = []
        for raw_line in raw_lines[-_MAX_LINES:]:
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            record_level = _LEVEL_VALUES.get(record.get("level", ""), logging.NOTSET)
            if record_level >= threshold:
                lines.append(
                    f"{record.get('timestamp', '?')} {record.get('level', '?')} "
                    f"{record.get('message', '')}"
                )

        app.call_from_thread(self._show_lines, lines)

    def _show_error(self, message: str) -> None:
        self.query_one("#logs-error", Static).update(message)

    def _show_lines(self, lines: list[str]) -> None:
        log_widget = self.query_one("#logs-view", RichLog)
        log_widget.clear()
        if not lines:
            self.query_one("#logs-error", Static).update("No log entries at or above this level.")
        else:
            self.query_one("#logs-error", Static).update("")
            for line in lines:
                log_widget.write(line)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "change-level":
            self._prompt_for_level()
        elif event.button.id == "back":
            from .main_menu import MainMenuScreen

            app: SLATApp = self.app  # type: ignore[assignment]
            app.switch_screen(MainMenuScreen())
