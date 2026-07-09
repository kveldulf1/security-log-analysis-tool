"""Unit tests for the rate-limit-abuse detector (good + bad)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fixtures import apache_line, make_rule_config

from security_log_analysis_tool.detection.rate_limit import RateLimitAbuseRule
from security_log_analysis_tool.models import LogSource
from security_log_analysis_tool.parsers import get_parser

_REF = datetime(2025, 7, 3, 12, 0, 0, tzinfo=UTC)


def _event(ip: str, status: int, i: int) -> object:
    apache = get_parser("apache")
    when = _REF + timedelta(seconds=i * 3)
    return apache.parse_line(
        "f", i + 1, apache_line(ip=ip, path="/api/data", status=status, when=when)
    )


def test_rate_limit_flags_at_threshold() -> None:
    rule = RateLimitAbuseRule(
        make_rule_config(
            id="rate-limit-abuse",
            type="rate-limit-abuse",
            source=LogSource.WEB,
            threshold=5,
            statuses=[429],
        )
    )
    events = [_event("45.33.32.1", 429, i) for i in range(5)]

    findings = rule.evaluate(events)

    assert len(findings) == 1
    assert findings[0].ip == "45.33.32.1"
    assert findings[0].count == 5


def test_rate_limit_does_not_flag_below_threshold() -> None:
    rule = RateLimitAbuseRule(
        make_rule_config(
            id="rate-limit-abuse",
            type="rate-limit-abuse",
            source=LogSource.WEB,
            threshold=5,
            statuses=[429],
        )
    )
    events = [_event("45.33.32.1", 429, i) for i in range(4)]

    assert rule.evaluate(events) == []


def test_rate_limit_ignores_non_429_status() -> None:
    rule = RateLimitAbuseRule(
        make_rule_config(
            id="rate-limit-abuse",
            type="rate-limit-abuse",
            source=LogSource.WEB,
            threshold=3,
            statuses=[429],
        )
    )
    events = [_event("192.0.2.1", 200, i) for i in range(5)]

    assert rule.evaluate(events) == []
