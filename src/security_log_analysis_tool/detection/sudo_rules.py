"""Sudo sensitive-command detector: privileged commands touching sensitive paths.

Sudo log lines carry no source IP, so findings key on the invoking user instead.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ..config import RuleConfig
from ..models import Finding, LogEvent
from .base import make_evidence, new_finding_id

_SUDO_PROGRAM = "sudo"


class SudoSensitiveCommandRule:
    def __init__(self, config: RuleConfig) -> None:
        self.rule_id = config.id
        self.severity = config.severity
        patterns = config.params.get("sensitive_patterns", [])
        self._patterns: tuple[re.Pattern[str], ...] = tuple(re.compile(p) for p in patterns)

    def _is_sensitive(self, event: LogEvent) -> bool:
        if event.extra.get("program") != _SUDO_PROGRAM:
            return False
        message = event.message or ""
        return any(pattern.search(message) for pattern in self._patterns)

    def evaluate(self, events: Sequence[LogEvent]) -> list[Finding]:
        by_user: dict[str, list[LogEvent]] = {}
        for event in events:
            if self._is_sensitive(event):
                by_user.setdefault(event.user or "unknown", []).append(event)
        return [self._build_finding(user, hits) for user, hits in by_user.items()]

    def _build_finding(self, user: str, hits: Sequence[LogEvent]) -> Finding:
        return Finding(
            finding_id=new_finding_id(),
            rule_id=self.rule_id,
            severity=self.severity,
            title=f"Sensitive sudo command by {user}",
            description=f"{user} ran {len(hits)} sudo command(s) touching a sensitive path.",
            users=(user,),
            first_seen=hits[0].timestamp,
            last_seen=hits[-1].timestamp,
            count=len(hits),
            evidence=tuple(make_evidence(e) for e in hits),
        )
