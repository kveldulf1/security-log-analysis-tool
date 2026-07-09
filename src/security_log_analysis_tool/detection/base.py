"""Shared detector infrastructure: the ``Rule`` protocol and a sliding-window counter.

Every concrete detector in this package turns a stream of same-source ``LogEvent``\\ s
into zero or more ``Finding``\\ s. Detectors are pure functions of the events they are
given — no I/O, no global state — so they are trivially unit-testable and, per the
architecture, reusable unchanged by a future incremental (watch-mode) pipeline that
feeds them a growing window instead of one final batch.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from ..models import Evidence, Finding, LogEvent, Severity
from ..redaction import redact

# Evidence excerpts are capped so a single oversized/adversarial line cannot bloat a
# report or export — consistent with the parser's own MAX_LINE_LENGTH bound.
MAX_EXCERPT_LENGTH = 500


def new_finding_id() -> str:
    """Return a fresh opaque finding identifier."""

    return uuid.uuid4().hex


def make_evidence(event: LogEvent) -> Evidence:
    """Build a redacted, length-capped evidence pointer from a source event."""

    excerpt = redact(event.raw or event.message or "")[:MAX_EXCERPT_LENGTH]
    return Evidence(file=event.file, line_no=event.line_no, excerpt=excerpt)


def group_by_ip(events: Sequence[LogEvent]) -> dict[str, list[LogEvent]]:
    """Group events by IP, dropping events with no IP (nothing to correlate on)."""

    grouped: dict[str, list[LogEvent]] = defaultdict(list)
    for event in events:
        if event.ip is not None:
            grouped[event.ip].append(event)
    return grouped


@runtime_checkable
class Rule(Protocol):
    """Structural type for a detector.

    ``evaluate`` receives every event of the rule's configured source — already
    filtered and time-sorted by the engine — and returns the findings it detects.
    """

    rule_id: str
    severity: Severity

    def evaluate(self, events: Sequence[LogEvent]) -> list[Finding]: ...


@dataclass
class SlidingWindowCounter:
    """Tracks events per key within a trailing time window.

    ``add`` evicts entries older than ``window_seconds`` relative to the latest
    event recorded for that key, giving callers an O(window) view of "how many
    times did this key show up recently" without unbounded memory growth. Callers
    must add events for a given key in non-decreasing timestamp order (the engine
    sorts events before handing them to a rule), otherwise eviction is unreliable.
    """

    window_seconds: int
    _entries: dict[str, list[LogEvent]] = field(default_factory=lambda: defaultdict(list))

    def add(self, key: str, event: LogEvent) -> list[LogEvent]:
        """Record ``event`` under ``key`` and return the current window contents."""

        bucket = self._entries[key]
        bucket.append(event)
        cutoff = event.timestamp - timedelta(seconds=self.window_seconds)
        bucket[:] = [e for e in bucket if e.timestamp >= cutoff]
        return bucket

    def window_as_of(self, key: str, as_of: datetime) -> list[LogEvent]:
        """Return ``key``'s recorded events still within the window at ``as_of``.

        Unlike :meth:`add`, this does not record a new event — it lets a caller
        (e.g. a brute-force-then-success rule) inspect "how many failures are
        still recent" at the moment of a different, non-failure event.
        """

        cutoff = as_of - timedelta(seconds=self.window_seconds)
        return [e for e in self._entries.get(key, []) if e.timestamp >= cutoff]
