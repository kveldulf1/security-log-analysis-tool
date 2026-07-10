"""End-to-end export tests: the installed console script writes real files.

Each format is produced by a genuine subprocess run over the committed sample
logs, then validated as an artifact a downstream consumer would load: JSON must
parse with populated findings, CSV must have a header plus data rows, SARIF must
be 2.1.0 with repo-relative URIs (the GitHub code-scanning contract).
"""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

import pytest
from fixtures.console_script import find_console_script

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(60)]

_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_ACCESS = _ROOT / "sample_logs" / "access.log"
_SAMPLE_AUTH = _ROOT / "sample_logs" / "auth.log"
_RULES = _ROOT / "config" / "rules.yaml"


@pytest.fixture(scope="module")
def cli() -> str:
    return find_console_script()


def _export(cli: str, fmt: str, output: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            cli,
            "analyze",
            str(_SAMPLE_ACCESS),
            str(_SAMPLE_AUTH),
            "--rules",
            str(_RULES),
            "--export",
            fmt,
            "--output",
            str(output),
            "--no-alerts",
            *extra,
        ],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        timeout=45,
        check=False,
    )


def test_json_export_parses_with_findings(cli: str, tmp_path: Path) -> None:
    out = tmp_path / "findings.json"
    proc = _export(cli, "json", out)
    assert proc.returncode == 1  # sample logs contain HIGH+ findings
    payload = json.loads(out.read_text(encoding="utf-8"))
    findings = payload["findings"] if isinstance(payload, dict) else payload
    assert len(findings) >= 1


def test_csv_export_has_header_and_rows(cli: str, tmp_path: Path) -> None:
    out = tmp_path / "findings.csv"
    proc = _export(cli, "csv", out)
    assert proc.returncode == 1
    with out.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert len(rows) >= 2  # header + at least one finding
    assert any("severity" in cell.lower() for cell in rows[0])


def test_sarif_export_is_2_1_0_with_repo_relative_uris(cli: str, tmp_path: Path) -> None:
    out = tmp_path / "findings.sarif"
    proc = _export(cli, "sarif", out)
    assert proc.returncode == 1
    sarif = json.loads(out.read_text(encoding="utf-8"))
    assert sarif["version"] == "2.1.0"
    results = sarif["runs"][0]["results"]
    assert len(results) >= 1
    uris = [
        location["physicalLocation"]["artifactLocation"]["uri"]
        for result in results
        for location in result.get("locations", [])
    ]
    assert uris, "SARIF results carry no locations"
    for uri in uris:
        # Path.is_absolute() alone is platform-dependent (a POSIX-style
        # "/var/log/x" is NOT absolute to WindowsPath), so check the leading
        # slash and drive-colon explicitly to keep this assertion meaningful
        # on every platform.
        assert not uri.startswith("/")
        assert not Path(uri).is_absolute()
        assert ":" not in uri  # no Windows drive letters in a repo-relative URI


def test_min_severity_filter_shrinks_export(cli: str, tmp_path: Path) -> None:
    full_out = tmp_path / "full.json"
    filtered_out = tmp_path / "critical.json"
    _export(cli, "json", full_out)
    _export(cli, "json", filtered_out, "--min-severity", "critical")

    def _count(path: Path) -> int:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return len(payload["findings"] if isinstance(payload, dict) else payload)

    assert 0 < _count(filtered_out) < _count(full_out)
