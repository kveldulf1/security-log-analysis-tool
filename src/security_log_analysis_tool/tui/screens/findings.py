"""Findings screen: severity-colored table of findings across finished jobs.

Mirrors ``report/console.py``'s severity styling and redaction so the TUI and
CLI never disagree about what's safe to show.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Static

from ...auth.authz import AuthorizationError, require
from ...models import JobStatus, Permission, Severity
from ...redaction import redact

if TYPE_CHECKING:
    from ..app import SLATApp

_POLL_INTERVAL_SECONDS = 1.0

_SEVERITY_STYLE = {
    Severity.LOW: "dim",
    Severity.MEDIUM: "yellow",
    Severity.HIGH: "bold dark_orange",
    Severity.CRITICAL: "bold red",
}


class FindingsScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        with Vertical(id="findings-box"):
            yield Static("Findings across all completed jobs", id="title")
            yield Static("", id="findings-error", classes="error")
            yield DataTable(id="findings-table")
            yield Button("Back", id="back")
        yield Footer()

    def on_mount(self) -> None:
        app: SLATApp = self.app  # type: ignore[assignment]
        error = self.query_one("#findings-error", Static)
        assert app.principal is not None  # only reachable after login
        try:
            require(app.principal, Permission.VIEW_FINDINGS)
        except AuthorizationError as exc:
            error.update(str(exc))
            return

        table = self.query_one(DataTable)
        table.add_columns("Severity", "Rule", "Title", "IP", "Count")
        self._refresh_findings()
        self.set_interval(_POLL_INTERVAL_SECONDS, self._refresh_findings)

    def _refresh_findings(self) -> None:
        app: SLATApp = self.app  # type: ignore[assignment]
        table = self.query_one(DataTable)
        table.clear()

        findings = [
            finding
            for job in app.job_queue.list_jobs()
            if job.status is JobStatus.DONE
            for finding in job.findings
        ]
        findings.sort(key=lambda f: -int(f.severity))

        for finding in findings:
            style = _SEVERITY_STYLE.get(finding.severity, "")
            severity_cell = (
                Text(finding.severity.name, style=style) if style else finding.severity.name
            )
            table.add_row(
                severity_cell,
                finding.rule_id,
                redact(finding.title),
                finding.ip or "-",
                str(finding.count),
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            from .main_menu import MainMenuScreen

            app: SLATApp = self.app  # type: ignore[assignment]
            app.switch_screen(MainMenuScreen())
