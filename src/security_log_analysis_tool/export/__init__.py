"""Findings exporters: JSON, CSV, SARIF.

``finding_to_dict`` is the single serialization choke point every exporter builds
from, so every output path applies the same redaction pass — belt and braces on
top of the redaction already applied when evidence was captured.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..models import Finding
from ..redaction import redact


def finding_to_dict(finding: Finding) -> dict[str, Any]:
    return {
        "finding_id": finding.finding_id,
        "rule_id": finding.rule_id,
        "severity": finding.severity.name,
        "title": redact(finding.title),
        "description": redact(finding.description),
        "ip": finding.ip,
        "users": [redact(u) for u in finding.users],
        "first_seen": finding.first_seen.isoformat(),
        "last_seen": finding.last_seen.isoformat(),
        "count": finding.count,
        "correlated_rule_ids": list(finding.correlated_rule_ids),
        "evidence": [
            {"file": e.file, "line_no": e.line_no, "excerpt": redact(e.excerpt)}
            for e in finding.evidence
        ],
    }


def findings_to_dicts(findings: Sequence[Finding]) -> list[dict[str, Any]]:
    return [finding_to_dict(f) for f in findings]
