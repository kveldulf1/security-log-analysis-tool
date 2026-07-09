"""Scanner-burst detector: an IP probing many distinct sensitive paths quickly."""

from __future__ import annotations

from collections.abc import Sequence

from ..config import RuleConfig
from ..models import Finding, LogEvent
from .base import SlidingWindowCounter, make_evidence, new_finding_id

_DEFAULT_STATUSES = (403, 404)
_DEFAULT_THRESHOLD = 6


class ScannerBurstRule:
    def __init__(self, config: RuleConfig) -> None:
        self.rule_id = config.id
        self.severity = config.severity
        self._threshold = int(config.params.get("threshold", _DEFAULT_THRESHOLD))
        self._statuses = frozenset(config.params.get("statuses", _DEFAULT_STATUSES))
        self._probe_paths = tuple(config.params.get("probe_paths", ()))
        self._counter = SlidingWindowCounter(config.window_seconds)
        self._flagged: set[str] = set()

    def _is_probe(self, event: LogEvent) -> bool:
        if event.status not in self._statuses:
            return False
        if not self._probe_paths:
            return True
        path = event.path or ""
        return any(path.startswith(p) for p in self._probe_paths)

    def evaluate(self, events: Sequence[LogEvent]) -> list[Finding]:
        findings: list[Finding] = []
        for event in events:
            if event.ip is None or not self._is_probe(event):
                continue
            window = self._counter.add(event.ip, event)
            distinct_paths = {e.path for e in window if e.path}
            if len(distinct_paths) >= self._threshold and event.ip not in self._flagged:
                self._flagged.add(event.ip)
                findings.append(self._build_finding(event.ip, window, len(distinct_paths)))
        return findings

    def _build_finding(self, ip: str, window: Sequence[LogEvent], distinct_count: int) -> Finding:
        return Finding(
            finding_id=new_finding_id(),
            rule_id=self.rule_id,
            severity=self.severity,
            title=f"Scanner burst from {ip}",
            description=(
                f"{ip} probed {distinct_count} distinct sensitive paths within "
                f"{self._counter.window_seconds}s (threshold {self._threshold})."
            ),
            ip=ip,
            first_seen=window[0].timestamp,
            last_seen=window[-1].timestamp,
            count=len(window),
            evidence=tuple(make_evidence(e) for e in window),
        )
