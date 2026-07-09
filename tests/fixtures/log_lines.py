"""Builders for well-formed and adversarial log lines used across the test suite."""

from __future__ import annotations

from datetime import datetime

_APACHE_TS = "%d/%b/%Y:%H:%M:%S %z"


def apache_line(
    *,
    ip: str = "10.0.0.50",
    user: str = "-",
    when: datetime | None = None,
    method: str = "GET",
    path: str = "/",
    status: int = 200,
    size: int | str = 1234,
    referer: str = "-",
    agent: str = "Mozilla/5.0",
) -> str:
    """Build one Apache combined-format access-log line."""

    when = when or datetime.fromisoformat("2025-07-03T10:15:32+00:00")
    stamp = when.strftime(_APACHE_TS)
    return (
        f'{ip} - {user} [{stamp}] "{method} {path} HTTP/1.1" {status} {size} "{referer}" "{agent}"'
    )


def syslog_line(
    *,
    when: datetime | None = None,
    host: str = "web-01",
    program: str = "sshd",
    pid: int = 1234,
    message: str = "Accepted password for alice from 10.0.0.50 port 40000 ssh2",
) -> str:
    """Build one syslog auth.log line (space-padded day, no year)."""

    when = when or datetime.fromisoformat("2025-07-03T10:15:32")
    stamp = f"{when.strftime('%b')} {when.day:>2} {when.strftime('%H:%M:%S')}"
    return f"{stamp} {host} {program}[{pid}]: {message}"


# Adversarial lines that must never crash a parser (see project-conventions memory).
ADVERSARIAL_LINES: tuple[str, ...] = (
    apache_line(path="/" + "A" * 1_000_000),  # oversized line
    apache_line(path="/a\x00b"),  # NUL bytes
    apache_line(path="/\x1b[31mred"),  # ANSI escape
    'malformed - - [not-a-timestamp] "GET / HTTP/1.1" 200 1',  # bad timestamp
    "totally unstructured line",  # no structure at all
    syslog_line(message="msg with \x00 nul and \x1b[0m ansi"),
)
