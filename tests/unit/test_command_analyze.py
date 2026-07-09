"""Tests for the ``analyze`` command's exit-code contract.

Regression coverage for a bug found via `/code-review`: the exit code must be
derived from the same severity-filtered finding set as the console report and
any export, not the unfiltered set — otherwise `--min-severity` can hide every
finding from the report/export while the process still exits 1.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fixtures import apache_line

from security_log_analysis_tool import cli


def _brute_force_log(tmp_path: Path) -> Path:
    start = datetime.fromisoformat("2025-07-03T10:00:00+00:00")
    lines = [
        apache_line(ip="10.0.0.9", path="/login", status=401, when=start + timedelta(seconds=i))
        for i in range(5)
    ]
    log = tmp_path / "access.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log


def test_high_finding_without_export_exits_1(tmp_path: Path) -> None:
    log = _brute_force_log(tmp_path)

    exit_code = cli.main(["analyze", str(log)])

    assert exit_code == 1


def test_min_severity_above_actual_findings_hides_report_and_exits_0(
    tmp_path: Path, capsys
) -> None:
    log = _brute_force_log(tmp_path)

    exit_code = cli.main(["analyze", str(log), "--min-severity", "critical"])

    out = capsys.readouterr().out
    assert "0 finding(s)" in out
    assert exit_code == 0
