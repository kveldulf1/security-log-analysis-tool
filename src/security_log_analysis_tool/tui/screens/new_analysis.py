"""Start-analysis screen: choose log files, submit a job to the shared queue.

Every failure mode — blank input, a file that doesn't exist, a role lacking
``RUN_ANALYSIS``, or a full queue — shows an inline message and leaves the
user on this screen; nothing here raises out to the app.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Static

from ...auth.authz import AuthorizationError, require
from ...models import Permission
from ...pipeline.queue import QueueFull

if TYPE_CHECKING:
    from ..app import SLATApp

_DEFAULT_FILES = "sample_logs/access.log sample_logs/auth.log"


class NewAnalysisScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        with Vertical(id="analysis-box"):
            yield Static("Start a new analysis", id="title")
            yield Static("Log file path(s), separated by spaces:")
            yield Input(value=_DEFAULT_FILES, id="files")
            yield Static("", id="analysis-error", classes="error")
            yield Button("Submit", id="submit", variant="primary")
            yield Button("Back", id="back")
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self._submit()
        elif event.button.id == "back":
            self._back()

    def _back(self) -> None:
        from .main_menu import MainMenuScreen

        app: SLATApp = self.app  # type: ignore[assignment]
        app.switch_screen(MainMenuScreen())

    def _submit(self) -> None:
        app: SLATApp = self.app  # type: ignore[assignment]
        error = self.query_one("#analysis-error", Static)
        raw = self.query_one("#files", Input).value.strip()

        if not raw:
            error.update("Enter at least one file path.")
            return

        assert app.principal is not None  # only reachable after login
        try:
            require(app.principal, Permission.RUN_ANALYSIS)
        except AuthorizationError as exc:
            error.update(str(exc))
            return

        files = raw.split()
        missing = [f for f in files if not Path(f).is_file()]
        if missing:
            error.update(f"File(s) not found: {', '.join(missing)}")
            return

        try:
            app.job_queue.submit(files, submitted_by=app.principal.username)
        except QueueFull as exc:
            error.update(str(exc))
            return

        from .jobs import JobsScreen

        app.switch_screen(JobsScreen())
