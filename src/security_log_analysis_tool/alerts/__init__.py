"""Alert dispatcher: the app-level hook system for detection findings.

Job completion dispatches findings at or above ``min_severity`` to every
configured sink. A sink is untrusted at the call site — a down SMTP server or
a toast that fails to render must never fail the analysis that discovered a
real threat — so each sink runs in its own try/except and :meth:`dispatch`
always returns a per-sink outcome instead of raising.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..config import AlertConfig, load_env_file
from ..models import Finding, Severity
from .email_sink import EmailSink, build_email_sink_from_env
from .toast_sink import ToastSink

logger = logging.getLogger(__name__)


@runtime_checkable
class AlertSink(Protocol):
    """A destination for finding notifications. Implementations must not raise."""

    name: str

    def send(self, findings: tuple[Finding, ...], *, job_id: str) -> None:
        """Notify about ``findings`` from ``job_id``. May raise; the dispatcher catches it."""


@dataclass(frozen=True, slots=True)
class SinkOutcome:
    sink: str
    ok: bool
    error: str | None = None


class AlertDispatcher:
    """Filters findings by severity and fans them out to every configured sink."""

    def __init__(
        self, sinks: tuple[AlertSink, ...], *, min_severity: Severity = Severity.HIGH
    ) -> None:
        self._sinks = sinks
        self._min_severity = min_severity

    def dispatch(self, findings: tuple[Finding, ...], *, job_id: str) -> tuple[SinkOutcome, ...]:
        eligible = tuple(f for f in findings if f.severity >= self._min_severity)
        if not eligible:
            return ()

        outcomes: list[SinkOutcome] = []
        for sink in self._sinks:
            try:
                sink.send(eligible, job_id=job_id)
            except Exception as exc:  # noqa: BLE001 - a sink must never fail the caller
                logger.warning("alert sink %s failed: %s", sink.name, exc)
                outcomes.append(SinkOutcome(sink=sink.name, ok=False, error=str(exc)))
            else:
                outcomes.append(SinkOutcome(sink=sink.name, ok=True))
        return tuple(outcomes)


def _default_alert_env() -> dict[str, str]:
    """SMTP settings for alerting: ``.env`` file values overlaid by real env vars.

    The ``.env`` file is looked up in the current directory by default (the
    documented run-from-project-root flow); set ``SLAT_ENV_FILE`` to an absolute
    path when invoking from elsewhere (cron, CI, a service wrapper).
    """

    env_file = Path(os.environ.get("SLAT_ENV_FILE", ".env"))
    return {**load_env_file(env_file), **os.environ}


def build_dispatcher(
    alerts: AlertConfig, *, env: Mapping[str, str] | None = None
) -> AlertDispatcher:
    """Build an :class:`AlertDispatcher` from the ``alerts:`` section of ``rules.yaml``.

    The single place that maps a sink *name* to a live sink object, so the wired
    entry points (the ``analyze`` CLI, and the job queue behind the TUI) dispatch
    through identical wiring. When ``env`` is omitted, ``.env`` file values plus
    the real environment are used (see :func:`_default_alert_env`). Alerting is
    best-effort by design: an unknown sink name, an email sink with no SMTP
    environment, or a malformed SMTP setting is skipped with a log message,
    never an error.
    """

    environment = _default_alert_env() if env is None else dict(env)
    sinks: list[AlertSink] = []
    for name in alerts.sinks:
        if name == "toast":
            sinks.append(ToastSink())
        elif name == "email":
            try:
                email = build_email_sink_from_env(environment)
            except Exception as exc:  # noqa: BLE001 - alerting must never fail the caller
                logger.warning("email sink misconfigured (%s); skipping", exc)
                continue
            if email is None:
                logger.info("email sink configured but SMTP environment is missing; skipping")
            else:
                sinks.append(email)
        else:
            logger.warning("unknown alert sink %r in config; skipping", name)
    return AlertDispatcher(tuple(sinks), min_severity=alerts.min_severity)


__all__ = [
    "AlertDispatcher",
    "AlertSink",
    "EmailSink",
    "SinkOutcome",
    "ToastSink",
    "build_dispatcher",
    "build_email_sink_from_env",
]
