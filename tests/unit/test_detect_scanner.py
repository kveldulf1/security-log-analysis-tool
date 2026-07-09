"""Unit tests for the scanner-burst detector (good + bad)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fixtures import apache_line, make_rule_config

from security_log_analysis_tool.detection.scanner import ScannerBurstRule
from security_log_analysis_tool.models import LogSource
from security_log_analysis_tool.parsers import get_parser

_REF = datetime(2025, 7, 3, 12, 0, 0, tzinfo=UTC)
_PROBE_PATHS = ["/.env", "/.git/config", "/admin", "/phpmyadmin", "/wp-admin", "/config.php"]


def _event(ip: str, path: str, status: int, i: int) -> object:
    apache = get_parser("apache")
    when = _REF + timedelta(seconds=i * 4)
    return apache.parse_line("f", i + 1, apache_line(ip=ip, path=path, status=status, when=when))


def test_scanner_burst_flags_distinct_probe_paths_at_threshold() -> None:
    rule = ScannerBurstRule(
        make_rule_config(
            id="scanner-burst",
            type="scanner-burst",
            source=LogSource.WEB,
            threshold=6,
            statuses=[403, 404],
            probe_paths=_PROBE_PATHS,
        )
    )
    events = [_event("203.0.113.5", path, 404, i) for i, path in enumerate(_PROBE_PATHS)]

    findings = rule.evaluate(events)

    assert len(findings) == 1
    assert findings[0].ip == "203.0.113.5"


def test_scanner_burst_does_not_flag_below_threshold() -> None:
    rule = ScannerBurstRule(
        make_rule_config(
            id="scanner-burst",
            type="scanner-burst",
            source=LogSource.WEB,
            threshold=6,
            statuses=[403, 404],
            probe_paths=_PROBE_PATHS,
        )
    )
    events = [_event("203.0.113.5", path, 404, i) for i, path in enumerate(_PROBE_PATHS[:5])]

    assert rule.evaluate(events) == []


def test_scanner_burst_ignores_non_probe_paths() -> None:
    rule = ScannerBurstRule(
        make_rule_config(
            id="scanner-burst",
            type="scanner-burst",
            source=LogSource.WEB,
            threshold=3,
            statuses=[403, 404],
            probe_paths=_PROBE_PATHS,
        )
    )
    events = [_event("192.0.2.1", f"/blog/{i}", 404, i) for i in range(6)]

    assert rule.evaluate(events) == []


def test_scanner_burst_ignores_successful_status() -> None:
    rule = ScannerBurstRule(
        make_rule_config(
            id="scanner-burst",
            type="scanner-burst",
            source=LogSource.WEB,
            threshold=3,
            statuses=[403, 404],
            probe_paths=_PROBE_PATHS,
        )
    )
    events = [_event("203.0.113.5", path, 200, i) for i, path in enumerate(_PROBE_PATHS)]

    assert rule.evaluate(events) == []
