"""SARIF 2.1.0 export, for GitHub code-scanning upload.

Locations use repo-relative URIs (e.g. ``sample_logs/access.log``) so GitHub
annotates findings directly on the committed sample log lines.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .. import __version__
from ..models import Evidence, Finding, Severity
from ..redaction import redact

_SCHEMA_URI = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
)
_TOOL_NAME = "security-log-analysis-tool"
_TOOL_URI = "https://github.com/security-log-analysis-tool"

_LEVEL_BY_SEVERITY = {
    Severity.LOW: "note",
    Severity.MEDIUM: "warning",
    Severity.HIGH: "error",
    Severity.CRITICAL: "error",
}


def _artifact_uri(file: str) -> str:
    normalized = file.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    path = Path(normalized)
    if path.is_absolute():
        try:
            relative = os.path.relpath(path, Path.cwd())
        except ValueError:
            # Different drive on Windows -- no relative path exists; keep the
            # normalized absolute path rather than raising.
            return normalized
        return relative.replace("\\", "/")
    return normalized


def _location(evidence: Evidence) -> dict[str, Any]:
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": _artifact_uri(evidence.file)},
            "region": {"startLine": max(evidence.line_no, 1)},
        }
    }


def _rule_definitions(findings: Sequence[Finding]) -> list[dict[str, Any]]:
    seen: dict[str, Severity] = {}
    for finding in findings:
        seen.setdefault(finding.rule_id, finding.severity)
    return [
        {
            "id": rule_id,
            "name": rule_id,
            "shortDescription": {"text": rule_id.replace("-", " ").title()},
            "defaultConfiguration": {"level": _LEVEL_BY_SEVERITY.get(severity, "warning")},
        }
        for rule_id, severity in sorted(seen.items())
    ]


def _result(finding: Finding) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ruleId": finding.rule_id,
        "level": _LEVEL_BY_SEVERITY.get(finding.severity, "warning"),
        "message": {"text": redact(finding.description)},
    }
    if finding.evidence:
        result["locations"] = [_location(e) for e in finding.evidence]
    return result


def to_sarif(findings: Sequence[Finding]) -> dict[str, Any]:
    """Build the SARIF 2.1.0 document (as a plain dict) for ``findings``."""

    return {
        "$schema": _SCHEMA_URI,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": _TOOL_NAME,
                        "informationUri": _TOOL_URI,
                        "version": __version__,
                        "rules": _rule_definitions(findings),
                    }
                },
                "results": [_result(f) for f in findings],
            }
        ],
    }


def write_sarif(findings: Sequence[Finding], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(to_sarif(findings), fh, indent=2, ensure_ascii=False)
