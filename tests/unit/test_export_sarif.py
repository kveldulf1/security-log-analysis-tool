"""Unit tests for the SARIF 2.1.0 exporter: schema validity, mapping, redaction."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

from security_log_analysis_tool.export.sarif_export import to_sarif, write_sarif
from security_log_analysis_tool.models import Evidence, Finding, Severity

_REF = datetime(2025, 7, 3, 12, 0, 0, tzinfo=UTC)
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "schemas" / "sarif-schema-2.1.0.json"
)


@pytest.fixture(scope="module")
def sarif_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _finding(**overrides: object) -> Finding:
    defaults = dict(
        finding_id="abc123",
        rule_id="path-traversal",
        severity=Severity.HIGH,
        title="Path traversal attempt from 203.0.113.5",
        description="2 request(s) attempted directory traversal",
        ip="203.0.113.5",
        users=(),
        first_seen=_REF,
        last_seen=_REF,
        count=2,
        evidence=(
            Evidence(file="sample_logs/access.log", line_no=97, excerpt="clean"),
            Evidence(file="sample_logs/access.log", line_no=98, excerpt="clean"),
        ),
    )
    defaults.update(overrides)
    return Finding(**defaults)


def test_sarif_document_validates_against_schema(sarif_schema: dict) -> None:
    document = to_sarif([_finding()])

    jsonschema.validate(document, sarif_schema)


def test_sarif_uses_repo_relative_uri() -> None:
    document = to_sarif([_finding()])

    locations = document["runs"][0]["results"][0]["locations"]
    assert locations[0]["physicalLocation"]["artifactLocation"]["uri"] == "sample_logs/access.log"
    assert locations[0]["physicalLocation"]["region"]["startLine"] == 97


def test_sarif_maps_critical_to_error_level(sarif_schema: dict) -> None:
    document = to_sarif([_finding(severity=Severity.CRITICAL)])

    assert document["runs"][0]["results"][0]["level"] == "error"
    jsonschema.validate(document, sarif_schema)


def test_sarif_result_with_no_evidence_omits_locations(sarif_schema: dict) -> None:
    document = to_sarif([_finding(evidence=())])

    assert "locations" not in document["runs"][0]["results"][0]
    jsonschema.validate(document, sarif_schema)


def test_sarif_redacts_secret_in_message(sarif_schema: dict) -> None:
    finding = _finding(description="leaked password=Password123!")

    document = to_sarif([finding])

    serialized = json.dumps(document)
    assert "Password123!" not in serialized
    assert "[REDACTED]" in serialized
    jsonschema.validate(document, sarif_schema)


def test_write_sarif_writes_valid_file(tmp_path: Path, sarif_schema: dict) -> None:
    out = tmp_path / "findings.sarif"

    write_sarif([_finding()], str(out))

    document = json.loads(out.read_text(encoding="utf-8"))
    jsonschema.validate(document, sarif_schema)
