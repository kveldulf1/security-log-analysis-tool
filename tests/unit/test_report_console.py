"""Unit tests for the Rich console reporter (good + redaction negative)."""

from __future__ import annotations

import io
from datetime import UTC, datetime

from rich.console import Console

from security_log_analysis_tool.models import Evidence, Finding, Severity
from security_log_analysis_tool.report.console import render_report

_REF = datetime(2025, 7, 3, 12, 0, 0, tzinfo=UTC)


def _finding(**overrides: object) -> Finding:
    defaults = dict(
        finding_id="abc123",
        rule_id="sudo-sensitive-command",
        severity=Severity.HIGH,
        title="Sensitive sudo command by alice",
        description="alice ran 1 sudo command(s) touching a sensitive path.",
        first_seen=_REF,
        last_seen=_REF,
        count=1,
        evidence=(Evidence(file="auth.log", line_no=68, excerpt="clean"),),
    )
    defaults.update(overrides)
    return Finding(**defaults)


def _render(findings: list[Finding]) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=200, no_color=True)
    render_report(console, findings, event_count=10, failure_count=0)
    return buffer.getvalue()


def test_render_report_includes_rule_and_ip() -> None:
    output = _render([_finding(ip="10.0.0.50")])

    assert "sudo-sensitive-command" in output
    assert "10.0.0.50" in output
    assert "1 finding(s) across 10 event(s)" in output


def test_render_report_redacts_secret_shaped_title() -> None:
    """A title built from attacker/log-controlled content (here a username that
    happens to look like an AWS key) must never reach the console unredacted."""

    finding = _finding(title="Sensitive sudo command by AKIAABCDEFGHIJKLMNOP")

    output = _render([finding])

    assert "AKIAABCDEFGHIJKLMNOP" not in output
    assert "[REDACTED]" in output


def test_render_report_redacts_correlated_callout_title() -> None:
    finding = _finding(
        rule_id="multi-vector-correlation",
        title="Multi-vector attack correlated on 10.0.0.50 token=sk-ant-abcdef1234567890",
        correlated_rule_ids=("web-brute-force-success", "ssh-brute-force-success"),
        ip="10.0.0.50",
    )

    output = _render([finding])

    assert "sk-ant-abcdef1234567890" not in output
    assert "Correlated multi-vector attacks" in output


def test_render_report_shows_no_correlated_section_without_correlated_findings() -> None:
    output = _render([_finding()])

    assert "Correlated multi-vector attacks" not in output
