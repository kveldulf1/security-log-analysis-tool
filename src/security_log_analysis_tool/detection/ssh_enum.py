"""SSH invalid-user enumeration detector: many distinct invalid usernames from one IP."""

from __future__ import annotations

from collections.abc import Sequence

from ..config import RuleConfig
from ..models import Finding, LogEvent
from .base import SlidingWindowCounter, make_evidence, new_finding_id

_INVALID_USER_MARKER = "invalid user"
_DEFAULT_THRESHOLD = 4


class SshInvalidUserEnumRule:
    def __init__(self, config: RuleConfig) -> None:
        self.rule_id = config.id
        self.severity = config.severity
        self._threshold = int(config.params.get("threshold", _DEFAULT_THRESHOLD))
        self._counter = SlidingWindowCounter(config.window_seconds)
        self._flagged: set[str] = set()

    def _is_invalid_user_attempt(self, event: LogEvent) -> bool:
        return _INVALID_USER_MARKER in (event.message or "")

    def evaluate(self, events: Sequence[LogEvent]) -> list[Finding]:
        findings: list[Finding] = []
        for event in events:
            if event.ip is None or not self._is_invalid_user_attempt(event):
                continue
            window = self._counter.add(event.ip, event)
            distinct_users = {e.user for e in window if e.user}
            if len(distinct_users) >= self._threshold and event.ip not in self._flagged:
                self._flagged.add(event.ip)
                findings.append(self._build_finding(event.ip, window, distinct_users))
        return findings

    def _build_finding(
        self, ip: str, window: Sequence[LogEvent], distinct_users: set[str]
    ) -> Finding:
        return Finding(
            finding_id=new_finding_id(),
            rule_id=self.rule_id,
            severity=self.severity,
            title=f"SSH invalid-user enumeration from {ip}",
            description=(
                f"{ip} attempted {len(distinct_users)} distinct invalid usernames within "
                f"{self._counter.window_seconds}s (threshold {self._threshold})."
            ),
            ip=ip,
            users=tuple(sorted(distinct_users)),
            first_seen=window[0].timestamp,
            last_seen=window[-1].timestamp,
            count=len(window),
            evidence=tuple(make_evidence(e) for e in window),
        )
