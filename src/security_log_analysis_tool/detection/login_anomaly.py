"""Rapid-success-after-failures detector.

Flags a login that succeeds shortly after a streak of failures from the same IP —
independent of, and with a lower threshold than, the brute-force-success
escalation, so shorter failure streaks that still look anomalous are not missed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from ..config import RuleConfig
from ..models import Finding, LogEvent
from .base import make_evidence, new_finding_id

_FAILURE_MARKER = "Failed password"
_SUCCESS_MARKER = "Accepted password"
_DEFAULT_MIN_FAILURES = 3
_DEFAULT_MAX_GAP_SECONDS = 30


class RapidSuccessAfterFailuresRule:
    def __init__(self, config: RuleConfig) -> None:
        self.rule_id = config.id
        self.severity = config.severity
        self._min_failures = int(config.params.get("min_failures", _DEFAULT_MIN_FAILURES))
        self._max_gap_seconds = int(config.params.get("max_gap_seconds", _DEFAULT_MAX_GAP_SECONDS))

    def evaluate(self, events: Sequence[LogEvent]) -> list[Finding]:
        streaks: dict[str, list[LogEvent]] = defaultdict(list)
        findings: list[Finding] = []
        for event in events:
            if event.ip is None:
                continue
            message = event.message or ""
            if _FAILURE_MARKER in message:
                streaks[event.ip].append(event)
            elif _SUCCESS_MARKER in message:
                streak = streaks[event.ip]
                gap = self._gap_seconds(streak, event)
                if streak and len(streak) >= self._min_failures and gap is not None:
                    findings.append(self._build_finding(event.ip, streak, event, gap))
                streaks[event.ip] = []
        return findings

    def _gap_seconds(self, streak: Sequence[LogEvent], success: LogEvent) -> float | None:
        if not streak:
            return None
        gap = (success.timestamp - streak[-1].timestamp).total_seconds()
        return gap if 0 <= gap <= self._max_gap_seconds else None

    def _build_finding(
        self, ip: str, streak: Sequence[LogEvent], success: LogEvent, gap: float
    ) -> Finding:
        evidence = tuple(make_evidence(e) for e in (*streak, success))
        return Finding(
            finding_id=new_finding_id(),
            rule_id=self.rule_id,
            severity=self.severity,
            title=f"Rapid success after failures from {ip}",
            description=(
                f"A login from {ip} succeeded {gap:.0f}s after {len(streak)} consecutive failures."
            ),
            ip=ip,
            first_seen=streak[0].timestamp,
            last_seen=success.timestamp,
            count=len(streak) + 1,
            evidence=evidence,
        )
