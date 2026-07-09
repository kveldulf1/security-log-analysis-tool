"""Web application attack detectors: path traversal and SQL-injection probes.

Both check the raw path and a single URL-decode pass, so double-encoded traversal
(``%252e``) and percent-encoded variants (``%2e%2e%2f``) are caught alongside the
literal ``../``. Findings are aggregated per IP so a scanning burst produces one
finding with multiple evidence lines, not one finding per hit.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import unquote

from ..config import RuleConfig
from ..models import Finding, LogEvent
from .base import group_by_ip, make_evidence, new_finding_id


class _PatternMatchRule:
    """Shared per-IP aggregation for a list of configured regex patterns."""

    _title = "Suspicious request pattern"
    _description = "matched a configured pattern"

    def __init__(self, config: RuleConfig) -> None:
        self.rule_id = config.id
        self.severity = config.severity
        patterns = config.params.get("patterns", [])
        self._patterns: tuple[re.Pattern[str], ...] = tuple(re.compile(p) for p in patterns)

    def _matches(self, event: LogEvent) -> bool:
        path = event.path or ""
        candidates = (path, unquote(path))
        return any(
            pattern.search(candidate) for pattern in self._patterns for candidate in candidates
        )

    def evaluate(self, events: Sequence[LogEvent]) -> list[Finding]:
        findings: list[Finding] = []
        for ip, ip_events in group_by_ip(events).items():
            hits = [e for e in ip_events if self._matches(e)]
            if hits:
                findings.append(self._build_finding(ip, hits))
        return findings

    def _build_finding(self, ip: str, hits: Sequence[LogEvent]) -> Finding:
        return Finding(
            finding_id=new_finding_id(),
            rule_id=self.rule_id,
            severity=self.severity,
            title=f"{self._title} from {ip}",
            description=f"{len(hits)} request(s) from {ip} {self._description}.",
            ip=ip,
            first_seen=hits[0].timestamp,
            last_seen=hits[-1].timestamp,
            count=len(hits),
            evidence=tuple(make_evidence(e) for e in hits),
        )


class PathTraversalRule(_PatternMatchRule):
    _title = "Path traversal attempt"
    _description = "attempted directory traversal"


class SqliProbeRule(_PatternMatchRule):
    _title = "SQL injection probe"
    _description = "matched a SQL-injection pattern"
