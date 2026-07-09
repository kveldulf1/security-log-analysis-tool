"""Headless Textual Pilot suite for the TUI.

Covers the session-5 Definition of Done: login (pos/neg), start/stop a job,
findings rendering, the tool-logs level prompt, role-based menu visibility,
graceful quit, and the "invalid input never exits the app" guarantee that
every screen must uphold.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest
from textual.css.query import NoMatches

from security_log_analysis_tool.auth.passwords import hash_password
from security_log_analysis_tool.auth.store import UserStore
from security_log_analysis_tool.logging_setup import configure_logging, reset_logging
from security_log_analysis_tool.models import JobStatus, Role, User
from security_log_analysis_tool.pipeline.engine import AnalysisEngine, AnalysisResult
from security_log_analysis_tool.tui.app import SLATApp

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.timeout(30)]

_ROOT = Path(__file__).resolve().parents[2]
_RULES_PATH = str(_ROOT / "config" / "rules.yaml")

_ADMIN_USER = "admin1"
_ADMIN_PASSWORD = "AdminOnlyPass1!"
_ANALYST_USER = "analyst1"
_ANALYST_PASSWORD = "AnalystOnlyPass1!"


@pytest.fixture
def users_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "users.db"
    with UserStore(db_path) as store:
        store.add_user(
            User(
                username=_ADMIN_USER,
                password_hash=hash_password(_ADMIN_PASSWORD),
                role=Role.ADMIN,
            )
        )
        store.add_user(
            User(
                username=_ANALYST_USER,
                password_hash=hash_password(_ANALYST_PASSWORD),
                role=Role.ANALYST,
            )
        )
    return db_path


def make_app(users_db: Path, log_paths=None) -> SLATApp:
    return SLATApp(rules_path=_RULES_PATH, db_path=str(users_db), log_paths=log_paths)


async def _login(pilot, username: str, password: str) -> None:
    app = pilot.app
    app.screen.query_one("#username").value = ""
    app.screen.query_one("#password").value = ""
    await pilot.click("#username")
    await pilot.press(*username)
    await pilot.click("#password")
    await pilot.press(*password)
    await pilot.click("#login-button")
    await pilot.pause(0.3)


async def _wait_until(predicate, *, timeout: float = 5.0, interval: float = 0.05) -> None:
    """Poll ``predicate`` without blocking the event loop the app runs on.

    A blocking ``time.sleep`` here would starve Textual's own async
    processing (e.g. a worker's ``call_from_thread`` callback), so this
    yields via ``asyncio.sleep`` between checks instead.
    """

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition was never met")


# --- Login: positive and negative -------------------------------------------------


async def test_valid_login_reaches_main_menu(users_db: Path) -> None:
    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ADMIN_USER, _ADMIN_PASSWORD)

        assert app.principal is not None
        assert app.principal.username == _ADMIN_USER
        assert type(app.screen).__name__ == "MainMenuScreen"


async def test_invalid_password_shows_error_and_stays_on_login(users_db: Path) -> None:
    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ADMIN_USER, "not the password")

        assert app.principal is None
        assert type(app.screen).__name__ == "LoginScreen"
        error = app.screen.query_one("#login-error")
        assert "invalid username or password" in str(error.renderable)
        assert app.is_running


async def test_blank_login_fields_show_validation_message(users_db: Path) -> None:
    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#login-button")
        await pilot.pause(0.1)

        assert app.principal is None
        assert type(app.screen).__name__ == "LoginScreen"
        error = app.screen.query_one("#login-error")
        assert "Enter both" in str(error.renderable)
        assert app.is_running


# --- Start analysis: job appears, completes, findings render ----------------------


async def test_start_analysis_job_completes_and_findings_render(users_db: Path) -> None:
    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ADMIN_USER, _ADMIN_PASSWORD)

        await pilot.click("#start-analysis")
        await pilot.pause(0.1)
        assert type(app.screen).__name__ == "NewAnalysisScreen"

        await pilot.click("#submit")
        await pilot.pause(0.2)
        assert type(app.screen).__name__ == "JobsScreen"

        await _wait_until(
            lambda: any(j.status is JobStatus.DONE for j in app.job_queue.list_jobs())
        )
        await pilot.pause(0.6)  # let the poll timer refresh the table

        table = app.screen.query_one("#jobs-table")
        assert table.row_count == 1

        await pilot.click("#back")
        await pilot.pause(0.1)
        await pilot.click("#show-findings")
        await pilot.pause(0.5)

        findings_table = app.screen.query_one("#findings-table")
        assert findings_table.row_count > 0  # sample_logs always yields findings


async def test_new_analysis_missing_file_shows_error_and_stays(users_db: Path) -> None:
    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ADMIN_USER, _ADMIN_PASSWORD)
        await pilot.click("#start-analysis")
        await pilot.pause(0.1)

        files_input = app.screen.query_one("#files")
        files_input.value = "no/such/file.log"
        await pilot.click("#submit")
        await pilot.pause(0.1)

        assert type(app.screen).__name__ == "NewAnalysisScreen"
        error = app.screen.query_one("#analysis-error")
        assert "not found" in str(error.renderable)
        assert app.is_running


async def test_new_analysis_blank_input_shows_error_and_stays(users_db: Path) -> None:
    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ADMIN_USER, _ADMIN_PASSWORD)
        await pilot.click("#start-analysis")
        await pilot.pause(0.1)

        app.screen.query_one("#files").value = ""
        await pilot.click("#submit")
        await pilot.pause(0.1)

        assert type(app.screen).__name__ == "NewAnalysisScreen"
        error = app.screen.query_one("#analysis-error")
        assert "Enter at least one" in str(error.renderable)
        assert app.is_running


# --- Jobs: cancel semantics (STOP_OWN_JOB vs STOP_ANY_JOB), invalid input ---------


async def test_jobs_screen_cancel_with_no_jobs_shows_message(users_db: Path) -> None:
    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ADMIN_USER, _ADMIN_PASSWORD)
        await pilot.click("#jobs")
        await pilot.pause(0.1)

        await pilot.click("#cancel")
        await pilot.pause(0.1)

        assert type(app.screen).__name__ == "JobsScreen"
        error = app.screen.query_one("#jobs-error")
        assert "No jobs" in str(error.renderable)
        assert app.is_running


async def test_analyst_can_cancel_own_job(users_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def slow_analyze(self, files, fmt="auto"):
        time.sleep(2.0)
        return AnalysisResult(events=(), failures=(), findings=())

    monkeypatch.setattr(AnalysisEngine, "analyze", slow_analyze)

    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ANALYST_USER, _ANALYST_PASSWORD)
        await pilot.click("#start-analysis")
        await pilot.pause(0.1)
        await pilot.click("#submit")
        await pilot.pause(0.2)

        await _wait_until(lambda: bool(app.job_queue.list_jobs()))
        await pilot.pause(0.6)

        table = app.screen.query_one("#jobs-table")
        assert table.row_count == 1
        await pilot.click("#cancel")
        await pilot.pause(0.2)

        error = app.screen.query_one("#jobs-error")
        assert "lacks permission" not in str(error.renderable)


async def test_analyst_cannot_cancel_admins_job(
    users_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow_analyze(self, files, fmt="auto"):
        time.sleep(2.0)
        return AnalysisResult(events=(), failures=(), findings=())

    monkeypatch.setattr(AnalysisEngine, "analyze", slow_analyze)

    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ADMIN_USER, _ADMIN_PASSWORD)
        await pilot.click("#start-analysis")
        await pilot.pause(0.1)
        await pilot.click("#submit")
        await pilot.pause(0.2)
        await _wait_until(lambda: bool(app.job_queue.list_jobs()))

        # Log out and back in as the analyst, who did not submit this job.
        await pilot.click("#back")
        await pilot.pause(0.1)
        await pilot.click("#logout")
        await pilot.pause(0.2)
        await _login(pilot, _ANALYST_USER, _ANALYST_PASSWORD)

        await pilot.click("#jobs")
        await pilot.pause(0.6)
        table = app.screen.query_one("#jobs-table")
        assert table.row_count == 1

        await pilot.click("#cancel")
        await pilot.pause(0.2)

        assert type(app.screen).__name__ == "JobsScreen"
        error = app.screen.query_one("#jobs-error")
        assert "lacks permission" in str(error.renderable)
        assert app.is_running


# --- Tool logs: modal level prompt, filtering, admin-only DEBUG -------------------


async def test_tool_logs_prompts_for_level_and_filters(users_db: Path, tmp_path: Path) -> None:
    log_paths = configure_logging(log_dir=tmp_path / "logs", console=False)
    logger = __import__("logging").getLogger("test.tool_logs")
    logger.warning("a warning line")
    logger.info("an info line")
    reset_logging()

    app = make_app(users_db, log_paths=log_paths)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ADMIN_USER, _ADMIN_PASSWORD)

        await pilot.click("#show-logs")
        await pilot.pause(0.2)
        assert type(app.screen).__name__ == "LogLevelPromptScreen"

        await pilot.click("#level-warning")
        await pilot.pause(0.3)
        assert type(app.screen).__name__ == "ToolLogsScreen"

        log_widget = app.screen.query_one("#logs-view")
        rendered = "\n".join(strip.text for strip in log_widget.lines)
        assert "a warning line" in rendered
        assert "an info line" not in rendered


async def test_tool_logs_analyst_cannot_choose_debug(users_db: Path) -> None:
    app = make_app(users_db)  # no log_paths: content doesn't matter for this check
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ANALYST_USER, _ANALYST_PASSWORD)

        await pilot.click("#show-logs")
        await pilot.pause(0.2)
        assert type(app.screen).__name__ == "LogLevelPromptScreen"

        await pilot.click("#level-debug")
        await pilot.pause(0.1)

        # Rejected: still on the modal, with a validation message, app alive.
        assert type(app.screen).__name__ == "LogLevelPromptScreen"
        error = app.screen.query_one("#level-prompt-error")
        assert "VIEW_ALL_TOOL_LOGS" in str(error.renderable)
        assert app.is_running


async def test_tool_logs_admin_can_choose_debug(users_db: Path) -> None:
    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ADMIN_USER, _ADMIN_PASSWORD)

        await pilot.click("#show-logs")
        await pilot.pause(0.2)
        await pilot.click("#level-debug")
        await pilot.pause(0.2)

        assert type(app.screen).__name__ == "ToolLogsScreen"


# --- Role-based main menu visibility -----------------------------------------------


async def test_analyst_menu_hides_manage_users(users_db: Path) -> None:
    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ANALYST_USER, _ANALYST_PASSWORD)

        with pytest.raises(NoMatches):
            app.screen.query_one("#manage-users")


async def test_admin_menu_shows_manage_users(users_db: Path) -> None:
    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ADMIN_USER, _ADMIN_PASSWORD)

        button = app.screen.query_one("#manage-users")
        assert button is not None


# --- Logout and graceful quit ------------------------------------------------------


async def test_logout_returns_to_login_screen(users_db: Path) -> None:
    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ADMIN_USER, _ADMIN_PASSWORD)
        await pilot.click("#logout")
        await pilot.pause(0.2)

        assert app.principal is None
        assert type(app.screen).__name__ == "LoginScreen"
        assert app.is_running


async def test_quit_shuts_down_queue_with_no_leaked_threads(users_db: Path) -> None:
    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _login(pilot, _ADMIN_USER, _ADMIN_PASSWORD)

        worker_threads_before = [
            t for t in threading.enumerate() if t.name.startswith("slat-worker-")
        ]
        assert len(worker_threads_before) == 4

        await pilot.click("#quit")
        await _wait_until(lambda: not app.is_running, timeout=15.0)

    worker_threads_after = [t for t in threading.enumerate() if t.name.startswith("slat-worker-")]
    assert worker_threads_after == []


# --- Invalid input hammer: every screen, app never exits --------------------------


async def test_invalid_input_never_exits_any_screen(users_db: Path) -> None:
    app = make_app(users_db)
    async with app.run_test() as pilot:
        await pilot.pause()

        # Login screen: garbage credentials.
        await _login(pilot, "nobody", "wrong-password")
        assert app.is_running
        assert type(app.screen).__name__ == "LoginScreen"

        await _login(pilot, _ADMIN_USER, _ADMIN_PASSWORD)
        assert app.is_running

        # New analysis: blank, then a nonexistent file.
        await pilot.click("#start-analysis")
        await pilot.pause(0.1)
        app.screen.query_one("#files").value = ""
        await pilot.click("#submit")
        await pilot.pause(0.1)
        assert app.is_running
        assert type(app.screen).__name__ == "NewAnalysisScreen"

        app.screen.query_one("#files").value = "definitely/not/a/real/file.log"
        await pilot.click("#submit")
        await pilot.pause(0.1)
        assert app.is_running
        assert type(app.screen).__name__ == "NewAnalysisScreen"

        # Jobs: cancel with nothing submitted.
        await pilot.click("#back")
        await pilot.pause(0.1)
        await pilot.click("#jobs")
        await pilot.pause(0.1)
        await pilot.click("#cancel")
        await pilot.pause(0.1)
        assert app.is_running
        assert type(app.screen).__name__ == "JobsScreen"

        # Tool logs modal: cancel the prompt outright.
        await pilot.click("#back")
        await pilot.pause(0.1)
        await pilot.click("#show-logs")
        await pilot.pause(0.1)
        await pilot.click("#level-cancel")
        await pilot.pause(0.1)
        assert app.is_running
        assert type(app.screen).__name__ == "ToolLogsScreen"

        await pilot.click("#back")
        await pilot.pause(0.1)
        assert app.is_running
        assert type(app.screen).__name__ == "MainMenuScreen"
