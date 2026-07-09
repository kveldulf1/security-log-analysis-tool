"""Integrity tests for the committed sample_logs — guards the data session 2 detects on.

Also exercises the shared fixture builders so a format drift is caught here first.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fixtures import ADVERSARIAL_LINES, apache_line, syslog_line

from security_log_analysis_tool.models import LogEvent, ParseFailure
from security_log_analysis_tool.parsers import get_parser
from security_log_analysis_tool.parsers.syslog_auth import SyslogAuthParser

_ROOT = Path(__file__).resolve().parents[2]
_REF = datetime(2025, 7, 3, 23, 0, 0, tzinfo=UTC)


def _parse_all(path: Path, parser) -> tuple[list[LogEvent], list[ParseFailure]]:
    events: list[LogEvent] = []
    failures: list[ParseFailure] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        result = parser.parse_line(str(path), i, line)
        (failures if isinstance(result, ParseFailure) else events).append(result)
    return events, failures


def test_sample_logs_have_exactly_one_malformed_line() -> None:
    access_events, access_fail = _parse_all(_ROOT / "sample_logs/access.log", get_parser("apache"))
    auth_events, auth_fail = _parse_all(
        _ROOT / "sample_logs/auth.log", SyslogAuthParser(reference=_REF)
    )
    # Exactly one malformed line total (session 2 asserts parse-failure count == 1).
    assert len(access_fail) + len(auth_fail) == 1
    assert access_events and auth_events


def test_showcase_scenarios_present() -> None:
    access_events, _ = _parse_all(_ROOT / "sample_logs/access.log", get_parser("apache"))
    auth_events, _ = _parse_all(_ROOT / "sample_logs/auth.log", SyslogAuthParser(reference=_REF))

    # Showcase A: 10.0.0.50 web /login brute force then a 200 success.
    web_5050 = [e for e in access_events if e.ip == "10.0.0.50"]
    assert sum(1 for e in web_5050 if e.status == 401) >= 5
    assert any(e.status == 200 for e in web_5050)

    # Showcase B: 10.0.0.50 ssh Failed... then Accepted (same IP across sources).
    ssh_5050 = [e for e in auth_events if e.ip == "10.0.0.50"]
    assert any("Failed password" in (e.message or "") for e in ssh_5050)
    assert any("Accepted password" in (e.message or "") for e in ssh_5050)

    # Second correlation: 203.0.113.5 invalid-user enumeration (>=4 distinct users).
    enum_users = {e.user for e in auth_events if e.ip == "203.0.113.5" and e.user is not None}
    assert len(enum_users) >= 4

    # Negative lookalike present: O'Brien search (must not be a SQLi later).
    assert any("O%27Brien" in (e.path or "") for e in access_events)

    # sudo sensitive vs benign both present.
    sudo_msgs = [e.message or "" for e in auth_events if e.extra.get("program") == "sudo"]
    assert any("/etc/shadow" in m for m in sudo_msgs)
    assert any("systemctl restart nginx" in m for m in sudo_msgs)


def test_fixture_builders_roundtrip() -> None:
    apache = get_parser("apache")
    ev = apache.parse_line("f", 1, apache_line(ip="1.2.3.4", status=403, path="/x"))
    assert isinstance(ev, LogEvent) and ev.ip == "1.2.3.4" and ev.status == 403

    syslog = SyslogAuthParser(reference=_REF)
    sv = syslog.parse_line(
        "f", 1, syslog_line(message="Failed password for root from 9.9.9.9 port 22 ssh2")
    )
    assert isinstance(sv, LogEvent) and sv.ip == "9.9.9.9"


def test_adversarial_lines_never_crash_parsers() -> None:
    apache = get_parser("apache")
    syslog = SyslogAuthParser(reference=_REF)
    for line in ADVERSARIAL_LINES:
        for parser in (apache, syslog):
            result = parser.parse_line("f", 1, line)
            assert isinstance(result, (LogEvent, ParseFailure))
