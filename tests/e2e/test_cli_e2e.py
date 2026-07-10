"""End-to-end CLI tests: drive the *installed console script* as a subprocess.

These prove the packaging contract a reviewer relies on — `pip install -e .`
puts `security-log-analysis-tool` on PATH, and the documented exit codes hold:
0 = clean, 1 = HIGH-or-above findings, 2 = configuration/usage error.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fixtures.console_script import find_console_script

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(60)]

_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_ACCESS = _ROOT / "sample_logs" / "access.log"
_SAMPLE_AUTH = _ROOT / "sample_logs" / "auth.log"
_CLEAN_ACCESS = _ROOT / "sample_logs" / "clean_access.log"
_RULES = _ROOT / "config" / "rules.yaml"


@pytest.fixture(scope="module")
def cli() -> str:
    return find_console_script()


def _run(cli: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [cli, *args],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        timeout=45,
        check=False,
    )


def test_version_exits_0(cli: str) -> None:
    proc = _run(cli, "--version")
    assert proc.returncode == 0
    assert "security-log-analysis-tool" in proc.stdout


def test_help_lists_every_subcommand(cli: str) -> None:
    proc = _run(cli, "--help")
    assert proc.returncode == 0
    for subcommand in ("analyze", "watch", "tui", "users"):
        assert subcommand in proc.stdout


def test_analyze_sample_logs_exits_1_with_both_showcase_correlations(cli: str) -> None:
    proc = _run(
        cli,
        "analyze",
        str(_SAMPLE_ACCESS),
        str(_SAMPLE_AUTH),
        "--rules",
        str(_RULES),
        "--no-alerts",
    )
    assert proc.returncode == 1
    assert "CRITICAL" in proc.stdout
    assert "10.0.0.50" in proc.stdout
    assert "203.0.113.5" in proc.stdout


def test_analyze_clean_log_exits_0(cli: str) -> None:
    proc = _run(cli, "analyze", str(_CLEAN_ACCESS), "--rules", str(_RULES), "--no-alerts")
    assert proc.returncode == 0


def test_bad_rules_file_exits_2_without_traceback(cli: str, tmp_path: Path) -> None:
    bad_rules = tmp_path / "rules.yaml"
    bad_rules.write_text("rules: [unclosed", encoding="utf-8")
    proc = _run(cli, "analyze", str(_CLEAN_ACCESS), "--rules", str(bad_rules), "--no-alerts")
    assert proc.returncode == 2
    combined = proc.stdout + proc.stderr
    assert "Traceback" not in combined
    assert "rules" in combined.lower()


def test_nonexistent_log_file_exits_2(cli: str, tmp_path: Path) -> None:
    proc = _run(
        cli,
        "analyze",
        str(tmp_path / "missing.log"),
        "--rules",
        str(_RULES),
        "--no-alerts",
    )
    assert proc.returncode == 2
    assert "Traceback" not in proc.stdout + proc.stderr


def test_export_without_output_exits_2(cli: str) -> None:
    proc = _run(
        cli,
        "analyze",
        str(_CLEAN_ACCESS),
        "--rules",
        str(_RULES),
        "--export",
        "json",
        "--no-alerts",
    )
    assert proc.returncode == 2
    assert "--output" in proc.stdout + proc.stderr


def test_unknown_subcommand_exits_2(cli: str) -> None:
    proc = _run(cli, "obliterate")
    assert proc.returncode == 2


def test_real_alert_path_runs_with_no_sinks_configured(cli: str, tmp_path: Path) -> None:
    """Exercise the UN-mocked dispatch path end-to-end (no --no-alerts).

    The rules copy declares zero sinks, so the real build_dispatcher +
    dispatch code runs to completion without any side effect — a crash
    anywhere in the alert wiring fails this test where every mocked or
    --no-alerts run would stay green.
    """

    rules = tmp_path / "rules.yaml"
    original = _RULES.read_text(encoding="utf-8")
    rules.write_text(original.replace("sinks: [toast, email]", "sinks: []"), encoding="utf-8")
    assert "sinks: []" in rules.read_text(encoding="utf-8")  # guard against drift

    proc = _run(cli, "analyze", str(_SAMPLE_ACCESS), str(_SAMPLE_AUTH), "--rules", str(rules))

    assert proc.returncode == 1
    assert "Traceback" not in proc.stdout + proc.stderr
