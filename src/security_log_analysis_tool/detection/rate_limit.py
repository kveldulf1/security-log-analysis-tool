"""Rate-limit abuse detector: repeated 429 responses from one IP."""

from __future__ import annotations

from collections.abc import Sequence

from ..config import RuleConfig
from ..models import Finding, LogEvent
from .base import SlidingWindowCounter, make_evidence, new_finding_id

_DEFAULT_STATUSES = (429,)
_DEFAULT_THRESHOLD = 5


class RateLimitAbuseRule:
    def __init__(self, config: RuleConfig) -> None:
        self.rule_id = config.id
        self.severity = config.severity
        self._threshold = int(config.params.get("threshold", _DEFAULT_THRESHOLD))
        self._statuses = frozenset(config.params.get("statuses", _DEFAULT_STATUSES))
        self._counter = SlidingWindowCounter(config.window_seconds)
        self._flagged: set[str] = set()

    def evaluate(self, events: Sequence[LogEvent]) -> list[Finding]:
        findings: list[Finding] = []
        for event in events:
            if event.ip is None or event.status not in self._statuses:
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
            title=f"Rate-limit abuse from {ip}",
            description=(
                f"{len(window)} rate-limited (429) responses to {ip} within "
                f"{self._counter.window_seconds}s (threshold {self._threshold})."
            ),
            ip=ip,
            first_seen=window[0].timestamp,
            last_seen=window[-1].timestamp,
            count=len(window),
            evidence=tuple(make_evidence(e) for e in window),
        )
