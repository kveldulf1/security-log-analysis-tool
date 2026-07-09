"""Table-driven tests for the Apache access-log parser."""

from __future__ import annotations

from datetime import timedelta

import pytest

from security_log_analysis_tool.models import LogEvent, LogSource, ParseFailure
from security_log_analysis_tool.parsers.apache_access import ApacheAccessParser

PARSER = ApacheAccessParser()


def _parse(line: str) -> LogEvent | ParseFailure:
    return PARSER.parse_line("access.log", 1, line)


def test_parses_combined_line() -> None:
    line = (
        "10.0.0.50 - alice [03/Jul/2025:10:15:32 +0000] "
        '"POST /login HTTP/1.1" 200 1234 "-" "Mozilla/5.0"'
    )
    ev = _parse(line)
    assert isinstance(ev, LogEvent)
    assert ev.source is LogSource.WEB
    assert ev.ip == "10.0.0.50"
    assert ev.user == "alice"
    assert ev.method == "POST"
    assert ev.path == "/login"
    assert ev.status == 200
    assert ev.size == 1234
    assert ev.extra["protocol"] == "HTTP/1.1"
    assert ev.extra["user_agent"] == "Mozilla/5.0"
    # timezone-aware, normalized to UTC
    assert ev.timestamp.tzinfo is not None
    assert ev.timestamp.utcoffset() == timedelta(0)
    assert ev.timestamp.hour == 10


def test_parses_common_line_without_referer_agent() -> None:
    line = '203.0.113.5 - - [03/Jul/2025:11:00:00 +0000] "GET /admin HTTP/1.1" 403 512'
    ev = _parse(line)
    assert isinstance(ev, LogEvent)
    assert ev.user is None  # "-" becomes None
    assert ev.status == 403
    assert ev.extra["user_agent"] is None


def test_timestamp_normalized_to_utc() -> None:
    line = '1.2.3.4 - - [03/Jul/2025:12:00:00 +0200] "GET / HTTP/1.1" 200 1'
    ev = _parse(line)
    assert isinstance(ev, LogEvent)
    assert ev.timestamp.utcoffset() == timedelta(0)
    assert ev.timestamp.hour == 10  # 12:00 +0200 -> 10:00 UTC


def test_dash_size_becomes_none() -> None:
    line = '1.2.3.4 - - [03/Jul/2025:12:00:00 +0000] "GET / HTTP/1.1" 304 -'
    ev = _parse(line)
    assert isinstance(ev, LogEvent)
    assert ev.size is None


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not a log line at all",
        '10.0.0.50 - - [03/Jul/2025:10:15:32 +0000] "POST /login',  # truncated
        '10.0.0.50 - - [03/Jul/2025:10:15:32] "GET / HTTP/1.1" 200 1',  # missing TZ
        '10.0.0.50 - - [notadate] "GET / HTTP/1.1" 200 1',  # bad timestamp
    ],
)
def test_malformed_lines_become_parse_failure(bad: str) -> None:
    result = _parse(bad)
    assert isinstance(result, ParseFailure)
    assert result.line_no == 1


def test_million_char_line_is_bounded_not_hang() -> None:
    line = (
        '10.0.0.50 - - [03/Jul/2025:10:15:32 +0000] "GET /' + "a" * 1_000_000 + ' HTTP/1.1" 200 1'
    )
    result = _parse(line)  # truncation caps regex work; either outcome is fine
    assert isinstance(result, (LogEvent, ParseFailure))


def test_nul_bytes_do_not_crash() -> None:
    line = '10.0.0.50 - - [03/Jul/2025:10:15:32 +0000] "GET /a\x00b HTTP/1.1" 200 1'
    result = _parse(line)
    assert isinstance(result, (LogEvent, ParseFailure))


def test_ansi_escape_in_path_is_inert() -> None:
    line = '10.0.0.50 - - [03/Jul/2025:10:15:32 +0000] "GET /\x1b[31mred HTTP/1.1" 200 1'
    ev = _parse(line)
    assert isinstance(ev, LogEvent)
    assert "\x1b[31m" in ev.path  # stored literally, never interpreted


def test_sniff_recognizes_apache() -> None:
    lines = [
        '10.0.0.50 - - [03/Jul/2025:10:15:32 +0000] "GET / HTTP/1.1" 200 1',
        '10.0.0.51 - - [03/Jul/2025:10:15:33 +0000] "GET /a HTTP/1.1" 404 2',
    ]
    assert PARSER.sniff(lines) is True
    assert PARSER.sniff(["Jul  3 10:15:32 host sshd[1]: Failed password"]) is False
