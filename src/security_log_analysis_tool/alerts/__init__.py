"""Alert dispatcher: the app-level hook system for detection findings.

Job completion dispatches findings at or above ``min_severity`` to every
configured sink. A sink is untrusted at the call site — a down SMTP server or
a toast that fails to render must never fail the analysis that discovered a
real threat — so each sink runs in its own try/except and :meth:`dispatch`
always returns a per-sink outcome instead of raising.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

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


__all__ = [
    "AlertDispatcher",
    "AlertSink",
    "EmailSink",
    "SinkOutcome",
    "ToastSink",
    "build_email_sink_from_env",
]
