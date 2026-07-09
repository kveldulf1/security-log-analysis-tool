"""Brute-force detection: repeated authentication failures per IP, and the
CRITICAL escalation when a subsequent success follows from the same IP.

One ``RuleConfig`` instance backs one stateful rule object for the lifetime of an
analysis run, so ``web-brute-force`` and ``ssh-brute-force`` (same ``type``,
different ``source``) never share counters.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..config import RuleConfig
from ..models import Finding, LogEvent, LogSource
from .base import SlidingWindowCounter, make_evidence, new_finding_id

_DEFAULT_STATUSES = (401, 403)
_DEFAULT_SUCCESS_STATUSES = (200, 302)
_DEFAULT_THRESHOLD = 5

_AUTH_FAILURE_MARKER = "Failed password"
_AUTH_SUCCESS_MARKER = "Accepted password"


def _is_web_failure(
    event: LogEvent, statuses: frozenset[int], match_paths: tuple[str, ...]
) -> bool:
    if event.status not in statuses:
        return False
    return not match_paths or any((event.path or "").startswith(p) for p in match_paths)


def _is_auth_failure(event: LogEvent) -> bool:
    return _AUTH_FAILURE_MARKER in (event.message or "")


def _is_web_success(event: LogEvent, statuses: frozenset[int]) -> bool:
    return event.status in statuses


def _is_auth_success(event: LogEvent) -> bool:
    return _AUTH_SUCCESS_MARKER in (event.message or "")


class BruteForceRule:
    """Flags an IP the moment its failure count in the trailing window hits threshold."""

    def __init__(self, config: RuleConfig) -> None:
        self.rule_id = config.id
        self.severity = config.severity
        self._source = config.source
        self._threshold = int(config.params.get("threshold", _DEFAULT_THRESHOLD))
        self._statuses = frozenset(config.params.get("statuses", _DEFAULT_STATUSES))
        self._match_paths = tuple(config.params.get("match_paths", ()))
        self._counter = SlidingWindowCounter(config.window_seconds)
        self._flagged: set[str] = set()

    def _is_failure(self, event: LogEvent) -> bool:
        if self._source == LogSource.WEB:
            return _is_web_failure(event, self._statuses, self._match_paths)
        return _is_auth_failure(event)

    def evaluate(self, events: Sequence[LogEvent]) -> list[Finding]:
        findings: list[Finding] = []
        for event in events:
            if event.ip is None or not self._is_failure(event):
                continue
            window = self._counter.add(event.ip, event)
            if len(window) >= self._threshold and event.ip not in self._flagged:
                self._flagged.add(event.ip)
                findings.append(self._build_finding(event.ip, window))
        return findings

    def _build_finding(self, ip: str, window: Sequence[LogEvent]) -> Finding:
        return Finding(
            finding_id=new_finding_id(),
            rule_id=self.rule_id,
            severity=self.severity,
            title=f"Brute-force attempt from {ip}",
            description=(
                f"{len(window)} authentication failures from {ip} within "
                f"{self._counter.window_seconds}s (threshold {self._threshold})."
            ),
            ip=ip,
            first_seen=window[0].timestamp,
            last_seen=window[-1].timestamp,
            count=len(window),
            evidence=tuple(make_evidence(e) for e in window),
        )


class BruteForceSuccessRule:
    """Escalates to CRITICAL when a success follows recent failures from one IP."""

    def __init__(self, config: RuleConfig) -> None:
        self.rule_id = config.id
        self.severity = config.severity
        self._source = config.source
        self._threshold = int(config.params.get("threshold", _DEFAULT_THRESHOLD))
        self._statuses = frozenset(config.params.get("statuses", _DEFAULT_STATUSES))
        self._success_statuses = frozenset(
            config.params.get("success_statuses", _DEFAULT_SUCCESS_STATUSES)
        )
        self._match_paths = tuple(config.params.get("match_paths", ()))
        self._counter = SlidingWindowCounter(config.window_seconds)
        self._flagged: set[str] = set()

    def _is_failure(self, event: LogEvent) -> bool:
        if self._source == LogSource.WEB:
            return _is_web_failure(event, self._statuses, self._match_paths)
        return _is_auth_failure(event)

    def _is_success(self, event: LogEvent) -> bool:
        if self._source == LogSource.WEB:
            return _is_web_success(event, self._success_statuses)
        return _is_auth_success(event)

    def evaluate(self, events: Sequence[LogEvent]) -> list[Finding]:
        findings: list[Finding] = []
        for event in events:
            if event.ip is None:
                continue
            if self._is_failure(event):
                self._counter.add(event.ip, event)
                continue
            if not self._is_success(event):
                continue
            window = self._counter.window_as_of(event.ip, event.timestamp)
            if len(window) >= self._threshold and event.ip not in self._flagged:
                self._flagged.add(event.ip)
                findings.append(self._build_finding(event.ip, window, event))
        return findings

    def _build_finding(self, ip: str, window: Sequence[LogEvent], success: LogEvent) -> Finding:
        evidence = tuple(make_evidence(e) for e in (*window, success))
        return Finding(
            finding_id=new_finding_id(),
            rule_id=self.rule_id,
            severity=self.severity,
            title=f"Brute-force followed by successful login from {ip}",
            description=(
                f"{len(window)} authentication failures from {ip} were followed by a "
                "successful login within the same window — the attack likely succeeded."
            ),
            ip=ip,
            first_seen=window[0].timestamp,
            last_seen=success.timestamp,
            count=len(window) + 1,
            evidence=evidence,
        )
