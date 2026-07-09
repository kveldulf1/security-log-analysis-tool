"""Step implementations for export.feature."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
from behave import given, then, when

from security_log_analysis_tool.export.csv_export import write_csv
from security_log_analysis_tool.export.json_export import write_json
from security_log_analysis_tool.export.sarif_export import write_sarif
from security_log_analysis_tool.models import Evidence, Finding, Severity

_EXPORTERS = {"json": write_json, "csv": write_csv, "sarif": write_sarif}
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "schemas"
    / "sarif-schema-2.1.0.json"
)


@given('a finding containing the secret "{secret}"')
def step_finding_with_secret(context, secret: str) -> None:
    ts = datetime(2025, 7, 3, 12, 0, 0, tzinfo=UTC)
    context.extra_findings = [
        Finding(
            finding_id="secret-finding",
            rule_id="sudo-sensitive-command",
            severity=Severity.HIGH,
            title="test finding",
            description=f"leaked credential token={secret}",
            first_seen=ts,
            last_seen=ts,
            count=1,
            evidence=(Evidence(file="auth.log", line_no=1, excerpt=f"password={secret}"),),
        )
    ]


@when('the findings are exported as "{fmt}" to a temporary file')
def step_export_to_temp_file(context, fmt: str) -> None:
    findings = tuple(context.result.findings) + tuple(getattr(context, "extra_findings", ()))
    fd, path = tempfile.mkstemp(suffix=f".{fmt}")
    os.close(fd)
    _EXPORTERS[fmt](findings, path)
    context.exported_findings = findings
    context.export_path = Path(path)


@then("the exported file contains the same number of findings")
def step_json_count_matches(context) -> None:
    data = json.loads(context.export_path.read_text(encoding="utf-8"))
    assert len(data) == len(context.exported_findings)


@then("the exported CSV has one row per finding")
def step_csv_row_count(context) -> None:
    with context.export_path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == len(context.exported_findings)


@then("the exported SARIF file is schema-valid")
def step_sarif_is_schema_valid(context) -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    document = json.loads(context.export_path.read_text(encoding="utf-8"))
    jsonschema.validate(document, schema)


@then('the exported file does not contain "{secret}"')
def step_file_does_not_contain(context, secret: str) -> None:
    text = context.export_path.read_text(encoding="utf-8")
    assert secret not in text
