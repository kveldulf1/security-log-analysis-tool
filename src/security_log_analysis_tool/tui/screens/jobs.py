"""Jobs screen: live-updating table of queued/running/finished jobs, with cancel.

Cancelling enforces ``STOP_OWN_JOB`` vs ``STOP_ANY_JOB`` at this screen too
(the service-layer objects already enforce it independently) — an analyst
cancelling someone else's job gets a validation message, not a crash; an
admin may cancel any job. The table polls :meth:`JobQueue.list_jobs`, a
thread-safe, lock-guarded read, so no ``call_from_thread`` is needed here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Static

from ...auth.authz import AuthorizationError, require
from ...models import Permission

if TYPE_CHECKING:
    from ..app import SLATApp

_POLL_INTERVAL_SECONDS = 0.5


class JobsScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        with Vertical(id="jobs-box"):
            yield Static("Jobs — select a row, then Cancel to stop it", id="title")
            yield DataTable(id="jobs-table")
            yield Static("", id="jobs-error", classes="error")
            yield Button("Cancel selected", id="cancel")
            yield Button("Back", id="back")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns("Job", "Status", "Submitted by", "Files", "Findings")
        self._refresh_jobs()
        self.set_interval(_POLL_INTERVAL_SECONDS, self._refresh_jobs)

    def _refresh_jobs(self) -> None:
        app: SLATApp = self.app  # type: ignore[assignment]
        table = self.query_one(DataTable)
        table.clear()
        jobs = sorted(app.job_queue.list_jobs(), key=lambda j: j.submitted_at, reverse=True)
        for job in jobs:
            table.add_row(
                job.job_id[:8],
                job.status.value,
                job.submitted_by,
                str(len(job.files)),
                str(len(job.findings)),
                key=job.job_id,
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self._cancel_selected()
        elif event.button.id == "back":
            from .main_menu import MainMenuScreen

            app: SLATApp = self.app  # type: ignore[assignment]
            app.switch_screen(MainMenuScreen())

    def _cancel_selected(self) -> None:
        app: SLATApp = self.app  # type: ignore[assignment]
        table = self.query_one(DataTable)
        error = self.query_one("#jobs-error", Static)

        if table.row_count == 0:
            error.update("No jobs to cancel.")
            return

        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        job_id = row_key.value
        job = app.job_queue.get(job_id) if job_id else None
        if job is None:
            error.update("Selected job no longer exists.")
            return

        assert app.principal is not None  # only reachable after login
        permission = (
            Permission.STOP_OWN_JOB
            if job.submitted_by == app.principal.username
            else Permission.STOP_ANY_JOB
        )
        try:
            require(app.principal, permission)
        except AuthorizationError as exc:
            error.update(str(exc))
            return

        if app.job_queue.cancel(job_id):
            error.update("")
            self._refresh_jobs()
        else:
            error.update("Job already finished; cannot cancel.")
