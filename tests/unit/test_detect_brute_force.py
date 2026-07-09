"""Unit tests for brute-force / brute-force-success detectors (good + bad)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fixtures import apache_line, make_rule_config, syslog_line

from security_log_analysis_tool.detection.brute_force import BruteForceRule, BruteForceSuccessRule
from security_log_analysis_tool.models import LogSource, Severity
from security_log_analysis_tool.parsers import get_parser
from security_log_analysis_tool.parsers.syslog_auth import SyslogAuthParser

_REF = datetime(2025, 7, 3, 12, 0, 0, tzinfo=UTC)


def _web_event(ip: str, i: int, *, status: int, path: str = "/login") -> object:
    apache = get_parser("apache")
    when = _REF + timedelta(seconds=i * 5)
    return apache.parse_line("f", i + 1, apache_line(ip=ip, path=path, status=status, when=when))


def _auth_event(ip: str, i: int, message: str) -> object:
    syslog = SyslogAuthParser(reference=_REF)
    when = _REF + timedelta(seconds=i * 5)
    return syslog.parse_line("f", i + 1, syslog_line(when=when, message=message))


def test_web_brute_force_flags_ip_at_threshold() -> None:
    config = make_rule_config(
        id="web-brute-force",
        type="brute-force",
        source=LogSource.WEB,
        threshold=5,
        statuses=[401],
        match_paths=["/login"],
    )
    rule = BruteForceRule(config)
    events = [_web_event("10.0.0.1", i, status=401) for i in range(5)]

    findings = rule.evaluate(events)

    assert len(findings) == 1
    assert findings[0].ip == "10.0.0.1"
    assert findings[0].count == 5
    assert findings[0].rule_id == "web-brute-force"
    assert len(findings[0].evidence) == 5


def test_web_brute_force_does_not_flag_below_threshold() -> None:
    config = make_rule_config(
        id="web-brute-force",
        type="brute-force",
        source=LogSource.WEB,
        threshold=5,
        statuses=[401],
        match_paths=["/login"],
    )
    rule = BruteForceRule(config)
    events = [_web_event("10.0.0.1", i, status=401) for i in range(4)]

    assert rule.evaluate(events) == []


def test_web_brute_force_ignores_non_matching_path() -> None:
    config = make_rule_config(
        id="web-brute-force",
        type="brute-force",
        source=LogSource.WEB,
        threshold=3,
        statuses=[401],
        match_paths=["/login"],
    )
    rule = BruteForceRule(config)
    events = [_web_event("10.0.0.2", i, status=401, path="/other") for i in range(5)]

    assert rule.evaluate(events) == []


def test_web_brute_force_ignores_out_of_window_failures() -> None:
    config = make_rule_config(
        id="web-brute-force",
        type="brute-force",
        source=LogSource.WEB,
        window_seconds=10,
        threshold=3,
        statuses=[401],
    )
    rule = BruteForceRule(config)
    # 30s apart with a 10s window: never more than 1 in-window at a time.
    apache = get_parser("apache")
    events = [
        apache.parse_line(
            "f",
            i + 1,
            apache_line(
                ip="10.0.0.6", path="/login", status=401, when=_REF + timedelta(seconds=i * 30)
            ),
        )
        for i in range(5)
    ]

    assert rule.evaluate(events) == []


def test_ssh_brute_force_flags_failed_password_any_user() -> None:
    config = make_rule_config(
        id="ssh-brute-force", type="brute-force", source=LogSource.AUTH, threshold=3
    )
    rule = BruteForceRule(config)
    events = [
        _auth_event("10.0.0.3", i, f"Failed password for root from 10.0.0.3 port {40000 + i} ssh2")
        for i in range(3)
    ]

    findings = rule.evaluate(events)

    assert len(findings) == 1
    assert findings[0].ip == "10.0.0.3"


def test_web_brute_force_success_escalates_to_critical() -> None:
    config = make_rule_config(
        id="web-brute-force-success",
        type="brute-force-success",
        source=LogSource.WEB,
        severity=Severity.CRITICAL,
        window_seconds=300,
        threshold=5,
        statuses=[401],
        success_statuses=[200],
    )
    rule = BruteForceSuccessRule(config)
    events = [_web_event("10.0.0.4", i, status=401) for i in range(5)]
    events.append(_web_event("10.0.0.4", 5, status=200))

    findings = rule.evaluate(events)

    assert len(findings) == 1
    assert findings[0].severity is Severity.CRITICAL
    assert findings[0].count == 6


def test_web_brute_force_success_not_triggered_without_prior_failures() -> None:
    config = make_rule_config(
        id="web-brute-force-success",
        type="brute-force-success",
        source=LogSource.WEB,
        window_seconds=300,
        threshold=5,
        statuses=[401],
        success_statuses=[200],
    )
    rule = BruteForceSuccessRule(config)
    events = [_web_event("10.0.0.5", 0, status=200)]

    assert rule.evaluate(events) == []


def test_ssh_brute_force_success_escalates() -> None:
    config = make_rule_config(
        id="ssh-brute-force-success",
        type="brute-force-success",
        source=LogSource.AUTH,
        severity=Severity.CRITICAL,
        window_seconds=300,
        threshold=3,
    )
    rule = BruteForceSuccessRule(config)
    events = [
        _auth_event("10.0.0.7", i, f"Failed password for root from 10.0.0.7 port {40000 + i} ssh2")
        for i in range(3)
    ]
    events.append(
        _auth_event("10.0.0.7", 3, "Accepted password for root from 10.0.0.7 port 41000 ssh2")
    )

    findings = rule.evaluate(events)

    assert len(findings) == 1
    assert findings[0].severity is Severity.CRITICAL
