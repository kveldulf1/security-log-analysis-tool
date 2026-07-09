"""Login screen: authenticate against the app's shared :class:`AuthService`.

Invalid credentials, a locked account, or blank fields all produce an inline
message and leave the user on this screen — login never crashes the app and
never silently retries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Static

from ...auth.service import AuthenticationError, Principal

if TYPE_CHECKING:
    from ..app import SLATApp


class LoginScreen(Screen[None]):
    """First screen shown on launch and after logout."""

    def compose(self) -> ComposeResult:
        with Vertical(id="login-box"):
            yield Static("Security Log Analysis Tool", id="title")
            yield Input(placeholder="username", id="username")
            yield Input(placeholder="password", password=True, id="password")
            yield Static("", id="login-error", classes="error")
            yield Button("Log in", id="login-button", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "login-button":
            self._attempt_login()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._attempt_login()

    def _attempt_login(self) -> None:
        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value
        error = self.query_one("#login-error", Static)

        if not username or not password:
            error.update("Enter both a username and a password.")
            return

        error.update("Authenticating…")
        self._do_login(username, password)

    @work(thread=True, exclusive=True)
    def _do_login(self, username: str, password: str) -> None:
        app: SLATApp = self.app  # type: ignore[assignment]
        try:
            principal = app.auth_service.login(username, password)
        except AuthenticationError as exc:
            app.call_from_thread(self._show_error, str(exc))
            return
        app.call_from_thread(self._login_succeeded, principal)

    def _show_error(self, message: str) -> None:
        self.query_one("#login-error", Static).update(message)
        self.query_one("#password", Input).value = ""

    def _login_succeeded(self, principal: Principal) -> None:
        from .main_menu import MainMenuScreen

        app: SLATApp = self.app  # type: ignore[assignment]
        app.principal = principal
        app.switch_screen(MainMenuScreen())
