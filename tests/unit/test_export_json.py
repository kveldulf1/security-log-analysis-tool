"""Unit tests for the JSON exporter (good + redaction negative)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from security_log_analysis_tool.export.json_export import to_json, write_json
from security_log_analysis_tool.models import Evidence, Finding, Severity

_REF = datetime(2025, 7, 3, 12, 0, 0, tzinfo=UTC)


def _finding(**overrides: object) -> Finding:
    defaults = dict(
        finding_id="abc123",
        rule_id="web-brute-force",
        severity=Severity.HIGH,
        title="Brute-force attempt from 10.0.0.1",
        description="5 failures from 10.0.0.1",
        ip="10.0.0.1",
        users=(),
        first_seen=_REF,
        last_seen=_REF,
        count=5,
        evidence=(Evidence(file="access.log", line_no=42, excerpt="clean line"),),
    )
    defaults.update(overrides)
    return Finding(**defaults)


@pytest.mark.smoke
def test_to_json_round_trips_fields() -> None:
    findings = [_finding()]

    payload = json.loads(to_json(findings))

    assert len(payload) == 1
    row = payload[0]
    assert row["rule_id"] == "web-brute-force"
    assert row["severity"] == "HIGH"
    assert row["ip"] == "10.0.0.1"
    assert row["count"] == 5
    assert row["evidence"][0]["line_no"] == 42


def test_to_json_redacts_secret_in_evidence_excerpt() -> None:
    finding = _finding(
        evidence=(Evidence(file="access.log", line_no=1, excerpt="password=Password123!"),)
    )

    payload = to_json([finding])

    assert "Password123!" not in payload
    assert "[REDACTED]" in payload


def test_to_json_redacts_secret_shaped_username() -> None:
    """usernames come straight from attacker-controlled log content (e.g. SSH
    invalid-user enumeration) and must be redacted like any other output path."""

    finding = _finding(users=("AKIAABCDEFGHIJKLMNOP",))

    payload = to_json([finding])

    assert "AKIAABCDEFGHIJKLMNOP" not in payload
    assert "[REDACTED]" in payload


def test_write_json_writes_file(tmp_path: Path) -> None:
    out = tmp_path / "findings.json"

    write_json([_finding()], str(out))

    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) == 1
