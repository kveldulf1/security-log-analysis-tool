"""Smoke test: the package imports and its CLI entry point runs."""

from security_log_analysis_tool import __version__
from security_log_analysis_tool.cli import main


def test_version_present():
    assert __version__


def test_cli_runs_and_reports_ready(capsys):
    exit_code = main([])
    assert exit_code == 0
    assert "ready" in capsys.readouterr().out
