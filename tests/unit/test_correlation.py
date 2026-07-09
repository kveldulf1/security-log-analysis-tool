"""Unit tests for the cross-source multi-vector correlation engine (good + bad)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fixtures import make_rule_config

from security_log_analysis_tool.correlation.engine import correlate
from security_log_analysis_tool.models import Evidence, Finding, LogSource, Severity

_REF = datetime(2025, 7, 3, 12, 0, 0, tzinfo=UTC)


def _finding(
    rule_id: str, ip: str, *, offset_seconds: int = 0, severity: Severity = Severity.HIGH
) -> Finding:
    ts = _REF + timedelta(seconds=offset_seconds)
    return Finding(
        finding_id=f"finding-{rule_id}-{ip}-{offset_seconds}",
        rule_id=rule_id,
        severity=severity,
        title=f"{rule_id} on {ip}",
        description="synthetic",
        ip=ip,
        first_seen=ts,
        last_seen=ts,
        count=1,
        evidence=(Evidence(file="f", line_no=1, excerpt="x"),),
    )


def _correlation_config(**params: object):
    return make_rule_config(
        id="multi-vector-correlation",
        type="multi-vector-correlation",
        severity=Severity.CRITICAL,
        window_seconds=600,
        **params,
    )


def test_correlates_two_rules_across_two_sources() -> None:
    findings = [
        _finding("web-brute-force-success", "10.0.0.50", offset_seconds=0),
        _finding("ssh-brute-force-success", "10.0.0.50", offset_seconds=30),
    ]
    rule_sources = {
        "web-brute-force-success": LogSource.WEB,
        "ssh-brute-force-success": LogSource.AUTH,
    }
    config = _correlation_config(min_distinct_rules=2, require_distinct_sources=True)

    correlated = correlate(findings, [config], rule_sources)

    assert len(correlated) == 1
    assert correlated[0].ip == "10.0.0.50"
    assert correlated[0].severity is Severity.CRITICAL
    assert set(correlated[0].correlated_rule_ids) == {
        "web-brute-force-success",
        "ssh-brute-force-success",
    }


def test_does_not_correlate_same_source_rules_when_distinct_sources_required() -> None:
    findings = [
        _finding("path-traversal", "203.0.113.5", offset_seconds=0),
        _finding("scanner-burst", "203.0.113.5", offset_seconds=10),
    ]
    rule_sources = {"path-traversal": LogSource.WEB, "scanner-burst": LogSource.WEB}
    config = _correlation_config(min_distinct_rules=2, require_distinct_sources=True)

    assert correlate(findings, [config], rule_sources) == []


def test_does_not_correlate_findings_from_different_ips() -> None:
    findings = [
        _finding("web-brute-force-success", "10.0.0.50", offset_seconds=0),
        _finding("ssh-brute-force-success", "10.0.0.99", offset_seconds=0),
    ]
    rule_sources = {
        "web-brute-force-success": LogSource.WEB,
        "ssh-brute-force-success": LogSource.AUTH,
    }
    config = _correlation_config(min_distinct_rules=2, require_distinct_sources=True)

    assert correlate(findings, [config], rule_sources) == []


def test_does_not_correlate_findings_outside_window() -> None:
    findings = [
        _finding("web-brute-force-success", "10.0.0.50", offset_seconds=0),
        _finding("ssh-brute-force-success", "10.0.0.50", offset_seconds=700),
    ]
    rule_sources = {
        "web-brute-force-success": LogSource.WEB,
        "ssh-brute-force-success": LogSource.AUTH,
    }
    config = _correlation_config(min_distinct_rules=2, require_distinct_sources=True)

    assert correlate(findings, [config], rule_sources) == []


def test_requires_min_distinct_rules() -> None:
    findings = [
        _finding("web-brute-force-success", "10.0.0.50", offset_seconds=0),
        _finding("ssh-brute-force-success", "10.0.0.50", offset_seconds=10),
    ]
    rule_sources = {
        "web-brute-force-success": LogSource.WEB,
        "ssh-brute-force-success": LogSource.AUTH,
    }
    config = _correlation_config(min_distinct_rules=3, require_distinct_sources=True)

    assert correlate(findings, [config], rule_sources) == []


def test_ignores_findings_without_ip() -> None:
    ipless = Finding(
        finding_id="f1",
        rule_id="sudo-sensitive-command",
        severity=Severity.HIGH,
        title="sudo",
        description="synthetic",
        first_seen=_REF,
        last_seen=_REF,
        count=1,
    )
    findings = [ipless, _finding("ssh-brute-force-success", "10.0.0.50", offset_seconds=0)]
    rule_sources = {
        "sudo-sensitive-command": LogSource.AUTH,
        "ssh-brute-force-success": LogSource.AUTH,
    }
    config = _correlation_config(min_distinct_rules=2, require_distinct_sources=False)

    assert correlate(findings, [config], rule_sources) == []
