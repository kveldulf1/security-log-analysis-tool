"""Unit tests for the CSV exporter (good + redaction negative)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from pathlib import Path

from security_log_analysis_tool.export.csv_export import to_csv, write_csv
from security_log_analysis_tool.models import Evidence, Finding, Severity

_REF = datetime(2025, 7, 3, 12, 0, 0, tzinfo=UTC)


def _finding(**overrides: object) -> Finding:
    defaults = dict(
        finding_id="abc123",
        rule_id="ssh-invalid-user-enum",
        severity=Severity.MEDIUM,
        title="SSH invalid-user enumeration from 203.0.113.5",
        description="6 distinct invalid usernames",
        ip="203.0.113.5",
        users=("admin", "test"),
        first_seen=_REF,
        last_seen=_REF,
        count=6,
        evidence=(Evidence(file="auth.log", line_no=62, excerpt="clean line"),),
    )
    defaults.update(overrides)
    return Finding(**defaults)


def test_to_csv_has_header_and_row() -> None:
    text = to_csv([_finding()])

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["rule_id"] == "ssh-invalid-user-enum"
    assert rows[0]["ip"] == "203.0.113.5"
    assert rows[0]["users"] == "admin;test"
    assert rows[0]["evidence"] == "auth.log:62"


def test_to_csv_redacts_secret_in_description() -> None:
    finding = _finding(description="leaked token=sk-ant-abcdef1234567890")

    text = to_csv([finding])

    assert "sk-ant-abcdef1234567890" not in text
    assert "[REDACTED]" in text


def test_to_csv_redacts_secret_shaped_username() -> None:
    """usernames come straight from attacker-controlled log content (e.g. SSH
    invalid-user enumeration) and must be redacted like any other output path."""

    finding = _finding(users=("AKIAABCDEFGHIJKLMNOP",))

    text = to_csv([finding])

    assert "AKIAABCDEFGHIJKLMNOP" not in text
    assert "[REDACTED]" in text


def test_write_csv_writes_file(tmp_path: Path) -> None:
    out = tmp_path / "findings.csv"

    write_csv([_finding()], str(out))

    rows = list(csv.DictReader(out.open(encoding="utf-8", newline="")))
    assert len(rows) == 1
