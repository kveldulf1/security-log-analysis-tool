"""Textual front-end: login -> main menu -> analysis / jobs / findings / logs.

Job execution runs on the shared :class:`JobQueue`'s own worker threads, which
never touch widgets directly — screens only poll thread-safe, lock-guarded
reads (``JobQueue.list_jobs``/``get``) from Textual's own event loop. Screens
that block on I/O they own (login's password hash/verify, reading the log
files) run that work via a ``@work(thread=True)`` worker and hand results
back through ``app.call_from_thread`` — the only place any of these screens
touch a widget from outside the UI thread.
"""

from __future__ import annotations

from textual import work
from textual.app import App
from textual.binding import Binding

from ..alerts import AlertDispatcher, build_dispatcher
from ..auth.service import AuthService, Principal
from ..auth.store import UserStore
from ..config import AppConfig, load_rules
from ..logging_setup import LoggingPaths
from ..models import Job
from ..pipeline.engine import AnalysisEngine
from ..pipeline.queue import EngineWorker, JobQueue

_DEFAULT_RULES_PATH = "config/rules.yaml"
_MAX_PENDING_JOBS = 32
_WORKER_COUNT = 4
_SHUTDOWN_TIMEOUT_SECONDS = 10.0


class SLATApp(App[None]):
    """The Security Log Analysis Tool terminal interface."""

    CSS = """
    Screen {
        align: center middle;
    }

    #title {
        text-style: bold;
        padding: 1 0;
    }

    .error {
        color: red;
        height: auto;
        min-height: 1;
        padding: 0 0 1 0;
    }

    Vertical {
        width: auto;
        height: auto;
    }

    DataTable {
        width: 90;
        height: 15;
    }

    RichLog {
        width: 90;
        height: 15;
        border: solid $primary;
    }
    """

    TITLE = "Security Log Analysis Tool"
    BINDINGS = [Binding("ctrl+q", "request_quit", "Quit", priority=True)]

    def __init__(
        self,
        *,
        rules_path: str = _DEFAULT_RULES_PATH,
        db_path: str | None = None,
        log_paths: LoggingPaths | None = None,
        alert_dispatcher: AlertDispatcher | None = None,
    ) -> None:
        super().__init__()
        self.config: AppConfig = load_rules(rules_path)
        self.log_paths = log_paths
        self.principal: Principal | None = None

        self._store = UserStore(db_path)
        self.auth_service = AuthService(self._store)

        # Injectable so tests can observe (or silence) alerting; by default a
        # completed job's findings fan out to the sinks configured in rules.yaml.
        self._alert_dispatcher = (
            build_dispatcher(self.config.alerts) if alert_dispatcher is None else alert_dispatcher
        )
        engine = AnalysisEngine(self.config)
        self.job_queue: JobQueue = JobQueue(
            EngineWorker(engine),
            max_pending=_MAX_PENDING_JOBS,
            workers=_WORKER_COUNT,
            on_done=self._dispatch_job_alerts,
        )

    def _dispatch_job_alerts(self, job: Job) -> None:
        self._alert_dispatcher.dispatch(tuple(job.findings), job_id=job.job_id)

    def on_mount(self) -> None:
        from .screens.login import LoginScreen

        self.push_screen(LoginScreen())

    def on_unmount(self) -> None:
        # Safety net for any exit path (including an uncaught exception) that
        # skips ``action_request_quit`` — both calls below are idempotent.
        self.job_queue.shutdown(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        self._store.close()

    @work(thread=True, exclusive=True)
    def action_request_quit(self) -> None:
        """Drain the queue off the UI thread, then exit — never freezes the app."""

        self.job_queue.shutdown(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        self._store.close()
        self.call_from_thread(self.exit)
