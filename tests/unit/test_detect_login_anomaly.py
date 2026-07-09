"""Unit tests for the rapid-success-after-failures detector (good + bad)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fixtures import make_rule_config, syslog_line

from security_log_analysis_tool.detection.login_anomaly import RapidSuccessAfterFailuresRule
from security_log_analysis_tool.models import LogSource
from security_log_analysis_tool.parsers.syslog_auth import SyslogAuthParser

_REF = datetime(2025, 7, 3, 12, 0, 0, tzinfo=UTC)


def _event(message: str, i: int) -> object:
    syslog = SyslogAuthParser(reference=_REF)
    when = _REF + timedelta(seconds=i * 5)
    return syslog.parse_line("f", i + 1, syslog_line(when=when, message=message))


def test_flags_success_shortly_after_failure_streak() -> None:
    rule = RapidSuccessAfterFailuresRule(
        make_rule_config(
            id="rapid-success-after-failures",
            type="rapid-success-after-failures",
            source=LogSource.AUTH,
            min_failures=3,
            max_gap_seconds=30,
        )
    )
    events = [
        _event("Failed password for root from 10.0.0.50 port 50000 ssh2", 0),
        _event("Failed password for invalid user admin from 10.0.0.50 port 50001 ssh2", 1),
        _event("Failed password for root from 10.0.0.50 port 50002 ssh2", 2),
        _event("Accepted password for alice from 10.0.0.50 port 50003 ssh2", 3),
    ]

    findings = rule.evaluate(events)

    assert len(findings) == 1
    assert findings[0].ip == "10.0.0.50"
    assert findings[0].count == 4


def test_does_not_flag_below_min_failures() -> None:
    rule = RapidSuccessAfterFailuresRule(
        make_rule_config(
            id="rapid-success-after-failures",
            type="rapid-success-after-failures",
            source=LogSource.AUTH,
            min_failures=3,
            max_gap_seconds=30,
        )
    )
    events = [
        _event("Failed password for root from 10.0.0.50 port 50000 ssh2", 0),
        _event("Accepted password for alice from 10.0.0.50 port 50001 ssh2", 1),
    ]

    assert rule.evaluate(events) == []


def test_does_not_flag_success_outside_max_gap() -> None:
    rule = RapidSuccessAfterFailuresRule(
        make_rule_config(
            id="rapid-success-after-failures",
            type="rapid-success-after-failures",
            source=LogSource.AUTH,
            min_failures=3,
            max_gap_seconds=5,
        )
    )
    events = [
        _event("Failed password for root from 10.0.0.50 port 50000 ssh2", 0),
        _event("Failed password for root from 10.0.0.50 port 50001 ssh2", 1),
        _event("Failed password for root from 10.0.0.50 port 50002 ssh2", 2),
        # 100s later — well outside a 5s gap tolerance.
        _event("Accepted password for alice from 10.0.0.50 port 50003 ssh2", 22),
    ]

    assert rule.evaluate(events) == []


def test_success_resets_streak_for_next_evaluation() -> None:
    rule = RapidSuccessAfterFailuresRule(
        make_rule_config(
            id="rapid-success-after-failures",
            type="rapid-success-after-failures",
            source=LogSource.AUTH,
            min_failures=3,
            max_gap_seconds=30,
        )
    )
    events = [
        _event("Failed password for root from 10.0.0.50 port 50000 ssh2", 0),
        _event("Failed password for root from 10.0.0.50 port 50001 ssh2", 1),
        _event("Failed password for root from 10.0.0.50 port 50002 ssh2", 2),
        _event("Accepted password for alice from 10.0.0.50 port 50003 ssh2", 3),
        # A lone success after the streak reset must not double-count.
        _event("Accepted password for alice from 10.0.0.50 port 50004 ssh2", 4),
    ]

    assert len(rule.evaluate(events)) == 1
