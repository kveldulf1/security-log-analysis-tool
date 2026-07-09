"""Main menu: launch analysis, manage jobs, view findings/logs, log out, quit.

The "Manage users" entry is shown only to a principal holding
``Permission.MANAGE_USERS`` (admin) — the same enforcement the CLI's ``users``
command already applies at the service layer; hiding it here is a convenience,
not the security boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Static

from ...auth.authz import has_permission
from ...models import Permission

if TYPE_CHECKING:
    from ..app import SLATApp


class MainMenuScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        app: SLATApp = self.app  # type: ignore[assignment]
        principal = app.principal
        assert principal is not None  # only reachable after a successful login

        with Vertical(id="menu-box"):
            yield Static(f"Logged in as {principal.username} ({principal.role.value})", id="whoami")
            yield Button("Start analysis", id="start-analysis")
            yield Button("Stop analysis / jobs", id="jobs")
            yield Button("Show findings", id="show-findings")
            yield Button("Show tool logs", id="show-logs")
            if has_permission(principal.role, Permission.MANAGE_USERS):
                yield Button("Manage users (admin)", id="manage-users")
            yield Button("Logout", id="logout")
            yield Button("Quit", id="quit")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        app: SLATApp = self.app  # type: ignore[assignment]

        if button_id == "start-analysis":
            from .new_analysis import NewAnalysisScreen

            app.switch_screen(NewAnalysisScreen())
        elif button_id == "jobs":
            from .jobs import JobsScreen

            app.switch_screen(JobsScreen())
        elif button_id == "show-findings":
            from .findings import FindingsScreen

            app.switch_screen(FindingsScreen())
        elif button_id == "show-logs":
            from .tool_logs import ToolLogsScreen

            app.switch_screen(ToolLogsScreen())
        elif button_id == "manage-users":
            app.notify(
                "Use the `security-log-analysis-tool users` CLI command to manage accounts.",
                title="Manage users",
            )
        elif button_id == "logout":
            self._logout()
        elif button_id == "quit":
            app.action_request_quit()

    def _logout(self) -> None:
        from .login import LoginScreen

        app: SLATApp = self.app  # type: ignore[assignment]
        app.principal = None
        app.switch_screen(LoginScreen())
