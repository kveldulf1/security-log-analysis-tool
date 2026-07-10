"""Tests for the ``analyze`` command's exit-code contract.

Regression coverage for a bug found via `/code-review`: the exit code must be
derived from the same severity-filtered finding set as the console report and
any export, not the unfiltered set — otherwise `--min-severity` can hide every
finding from the report/export while the process still exits 1.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fixtures import RecordingDispatcher, apache_line

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

    exit_code = cli.main(["analyze", str(log), "--no-alerts"])

    assert exit_code == 1


def test_min_severity_above_actual_findings_hides_report_and_exits_0(
    tmp_path: Path, capsys
) -> None:
    log = _brute_force_log(tmp_path)

    exit_code = cli.main(["analyze", str(log), "--min-severity", "critical", "--no-alerts"])

    out = capsys.readouterr().out
    assert "0 finding(s)" in out
    assert exit_code == 0


@pytest.fixture
def recorded_alerts(monkeypatch) -> RecordingDispatcher:
    from security_log_analysis_tool.commands import analyze as analyze_cmd

    recorder = RecordingDispatcher()
    monkeypatch.setattr(analyze_cmd, "build_dispatcher", lambda *_a, **_kw: recorder)
    return recorder


def test_analyze_dispatches_alerts_by_default(
    tmp_path: Path, recorded_alerts: RecordingDispatcher
) -> None:
    log = _brute_force_log(tmp_path)

    cli.main(["analyze", str(log)])

    assert len(recorded_alerts.calls) == 1
    job_id, finding_count = recorded_alerts.calls[0]
    assert job_id.startswith("cli-")
    assert finding_count >= 1


def test_analyze_alerts_ignore_display_min_severity_filter(
    tmp_path: Path, recorded_alerts: RecordingDispatcher
) -> None:
    log = _brute_force_log(tmp_path)

    # The display filter hides everything, but the alert path still sees the
    # full finding set (the config's own alert threshold governs alerting).
    cli.main(["analyze", str(log), "--min-severity", "critical"])

    assert len(recorded_alerts.calls) == 1
    assert recorded_alerts.calls[0][1] >= 1


def test_no_alerts_flag_suppresses_dispatch(
    tmp_path: Path, recorded_alerts: RecordingDispatcher
) -> None:
    log = _brute_force_log(tmp_path)

    cli.main(["analyze", str(log), "--no-alerts"])

    assert recorded_alerts.calls == []


def test_real_dispatch_path_runs_unmocked_with_no_sinks(tmp_path: Path) -> None:
    """No --no-alerts and no monkeypatching: the genuine build_dispatcher +
    dispatch path executes in-process. The rules copy declares zero sinks, so
    the run has no side effects — any crash in the alert wiring fails here."""

    rules_src = Path("config/rules.yaml").read_text(encoding="utf-8")
    assert "sinks: [toast, email]" in rules_src  # guard against config drift
    rules = tmp_path / "rules.yaml"
    rules.write_text(rules_src.replace("sinks: [toast, email]", "sinks: []"), encoding="utf-8")
    log = _brute_force_log(tmp_path)

    exit_code = cli.main(["analyze", str(log), "--rules", str(rules)])

    assert exit_code == 1
