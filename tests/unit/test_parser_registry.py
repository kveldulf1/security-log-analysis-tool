"""Tests for the parser registry and format sniffer."""

from __future__ import annotations

import pytest

from security_log_analysis_tool.models import LogSource
from security_log_analysis_tool.parsers import (
    UnknownFormatError,
    available_formats,
    get_parser,
    parser_for,
    sniff_parser,
)

_APACHE = ['10.0.0.50 - - [03/Jul/2025:10:15:32 +0000] "GET / HTTP/1.1" 200 1']
_SYSLOG = ["Jul  3 10:15:32 web-01 sshd[1]: Failed password for root from 1.2.3.4 port 1 ssh2"]


@pytest.mark.parametrize(
    ("name", "expected_source"),
    [
        ("apache", LogSource.WEB),
        ("web", LogSource.WEB),
        ("ACCESS", LogSource.WEB),
        ("syslog", LogSource.AUTH),
        ("auth", LogSource.AUTH),
    ],
)
def test_get_parser_aliases(name: str, expected_source: LogSource) -> None:
    assert get_parser(name).source is expected_source


def test_get_parser_unknown_raises() -> None:
    with pytest.raises(UnknownFormatError, match="unknown format"):
        get_parser("mainframe")


def test_available_formats_lists_known() -> None:
    formats = available_formats()
    assert "apache" in formats and "syslog" in formats


def test_sniff_apache_vs_syslog() -> None:
    assert sniff_parser(_APACHE).source is LogSource.WEB
    assert sniff_parser(_SYSLOG).source is LogSource.AUTH
    assert sniff_parser(["random noise line"]) is None


def test_parser_for_auto() -> None:
    assert parser_for("auto", _APACHE).source is LogSource.WEB
    assert parser_for("auto", _SYSLOG).source is LogSource.AUTH


def test_parser_for_auto_unrecognized_raises() -> None:
    with pytest.raises(UnknownFormatError):
        parser_for("auto", ["garbage", "more garbage"])


def test_parser_for_explicit() -> None:
    assert parser_for("apache", _SYSLOG).source is LogSource.WEB  # explicit wins over content
