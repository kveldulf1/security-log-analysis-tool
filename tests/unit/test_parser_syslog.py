"""Table-driven tests for the syslog auth.log parser."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from security_log_analysis_tool.models import LogEvent, LogSource, ParseFailure
from security_log_analysis_tool.parsers.syslog_auth import SyslogAuthParser

# Fixed reference so year-inference is deterministic.
REF = datetime(2025, 7, 3, 12, 0, 0, tzinfo=UTC)
PARSER = SyslogAuthParser(reference=REF)


def _parse(line: str) -> LogEvent | ParseFailure:
    return PARSER.parse_line("auth.log", 1, line)


def test_parses_failed_invalid_user() -> None:
    line = (
        "Jul  3 10:15:32 web-01 sshd[1234]: "
        "Failed password for invalid user admin from 203.0.113.5 port 54321 ssh2"
    )
    ev = _parse(line)
    assert isinstance(ev, LogEvent)
    assert ev.source is LogSource.AUTH
    assert ev.ip == "203.0.113.5"
    assert ev.user == "admin"
    assert ev.extra["program"] == "sshd"
    assert ev.extra["pid"] == 1234
    assert ev.timestamp.tzinfo is not None
    assert ev.timestamp.utcoffset() == timedelta(0)
    assert ev.timestamp.year == 2025


def test_parses_accepted_password() -> None:
    line = (
        "Jul  3 10:16:00 web-01 sshd[1250]: "
        "Accepted password for alice from 10.0.0.50 port 40000 ssh2"
    )
    ev = _parse(line)
    assert isinstance(ev, LogEvent)
    assert ev.user == "alice"
    assert ev.ip == "10.0.0.50"


def test_parses_failed_root() -> None:
    line = (
        "Jul  3 10:15:40 web-01 sshd[1240]: Failed password for root from 10.0.0.50 port 40001 ssh2"
    )
    ev = _parse(line)
    assert isinstance(ev, LogEvent)
    assert ev.user == "root"


def test_parses_sudo_command() -> None:
    line = (
        "Jul  3 10:20:00 web-01 sudo:   alice : TTY=pts/0 ; PWD=/home/alice ; "
        "USER=root ; COMMAND=/usr/bin/cat /etc/shadow"
    )
    ev = _parse(line)
    assert isinstance(ev, LogEvent)
    assert ev.extra["program"] == "sudo"
    assert ev.user == "alice"
    assert "COMMAND=/usr/bin/cat /etc/shadow" in ev.message


def test_double_digit_day_padding() -> None:
    line = "Jul 13 09:00:00 web-01 sshd[10]: Accepted password for bob from 1.2.3.4 port 22 ssh2"
    ev = _parse(line)
    assert isinstance(ev, LogEvent)
    assert ev.timestamp.day == 13


def test_future_dated_flag_set() -> None:
    # A line a few days ahead of the reference (clock skew) is flagged, not corrected.
    ref = datetime(2025, 7, 3, 10, 0, 0, tzinfo=UTC)
    parser = SyslogAuthParser(reference=ref)
    ev = parser.parse_line(
        "auth.log",
        1,
        "Jul  5 10:00:00 web-01 sshd[1]: Accepted password for x from 1.2.3.4 port 1 ssh2",
    )
    assert isinstance(ev, LogEvent)
    assert ev.timestamp.year == 2025
    assert ev.extra.get("future_dated") is True


def test_cross_year_rollback() -> None:
    # A December line seen in early January belongs to the PREVIOUS year, not future.
    ref = datetime(2025, 1, 1, tzinfo=UTC)
    parser = SyslogAuthParser(reference=ref)
    ev = parser.parse_line(
        "auth.log",
        1,
        "Dec 31 23:59:59 web-01 sshd[1]: Accepted password for x from 1.2.3.4 port 1 ssh2",
    )
    assert isinstance(ev, LogEvent)
    assert ev.timestamp.year == 2024
    assert "future_dated" not in ev.extra


def test_leap_day_preserved_in_non_leap_reference_year() -> None:
    # Feb 29 must never be dropped just because the reference year isn't a leap year.
    ref = datetime(2025, 6, 1, tzinfo=UTC)  # 2025 is not a leap year
    parser = SyslogAuthParser(reference=ref)
    ev = parser.parse_line(
        "auth.log",
        1,
        "Feb 29 12:00:00 web-01 sshd[1]: Failed password for root from 1.2.3.4 port 1 ssh2",
    )
    assert isinstance(ev, LogEvent)
    assert ev.timestamp.year == 2024  # nearest earlier leap year
    assert ev.timestamp.month == 2 and ev.timestamp.day == 29


def test_not_future_when_in_range() -> None:
    ev = _parse("Jul  3 10:15:32 web-01 sshd[1]: Accepted password for x from 1.2.3.4 port 1 ssh2")
    assert isinstance(ev, LogEvent)
    assert "future_dated" not in ev.extra


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "totally unrelated text",
        "Jul  3 25:99:99 web-01 sshd[1]: bad time",  # invalid time -> failure
    ],
)
def test_malformed_lines_become_parse_failure(bad: str) -> None:
    assert isinstance(_parse(bad), ParseFailure)


def test_million_char_line_is_bounded() -> None:
    line = "Jul  3 10:15:32 web-01 sshd[1]: " + "A" * 1_000_000
    result = _parse(line)
    assert isinstance(result, (LogEvent, ParseFailure))


def test_nul_and_ansi_inert() -> None:
    line = "Jul  3 10:15:32 web-01 sshd[1]: message with \x00 and \x1b[31m escape"
    ev = _parse(line)
    assert isinstance(ev, LogEvent)
    assert "\x1b[31m" in ev.message


def test_sniff_recognizes_syslog() -> None:
    lines = [
        "Jul  3 10:15:32 web-01 sshd[1]: Failed password for root from 1.2.3.4 port 1 ssh2",
        "Jul  3 10:15:33 web-01 sshd[2]: Accepted password for bob from 1.2.3.5 port 2 ssh2",
    ]
    assert PARSER.sniff(lines) is True
    assert (
        PARSER.sniff(['1.2.3.4 - - [03/Jul/2025:10:15:32 +0000] "GET / HTTP/1.1" 200 1']) is False
    )
