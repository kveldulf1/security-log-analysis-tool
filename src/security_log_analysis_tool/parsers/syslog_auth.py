"""Parser for syslog ``auth.log`` lines (sshd, sudo, PAM sessions).

Syslog timestamps carry no year, so the parser assumes the year of a reference
instant (the current UTC time by default, injectable for deterministic tests) and
flags ``extra['future_dated']`` when the resulting timestamp is ahead of it. The
parser only normalizes structure — semantic classification (failure vs success,
invalid-user enumeration, sudo intent) belongs to the detectors.

Timezone note: classic syslog also carries no offset, so the wall-clock time is
interpreted as UTC (per the model's UTC-internal contract). If a deployment's auth
host logs local time, configure it to emit UTC / RFC 5424 timestamps; a mixed-offset
fleet is out of scope for the homework and documented in the README scaling notes.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from ..models import LogEvent, LogSource, ParseFailure
from .base import SNIFF_THRESHOLD, Parser, clean_line, fraction_matching

# e.g. "Jul  3 10:15:32 web-01 sshd[1234]: Failed password for invalid user admin from 1.2.3.4 ..."
_LINE_RE = re.compile(
    r"^(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<prog>[^:\[\s]+)(?:\[(?P<pid>\d+)\])?:\s*(?P<msg>.*)$"
)

_IP_RE = re.compile(r"\bfrom\s+(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\b")
_USER_RES = (
    re.compile(r"\bfor\s+invalid user\s+(?P<user>\S+)"),
    re.compile(r"\bfor\s+user\s+(?P<user>\S+)"),
    re.compile(r"\bfor\s+(?P<user>\S+)\s+from\b"),
    re.compile(r"\binvalid user\s+(?P<user>\S+)"),
    re.compile(r"\buser\s+(?P<user>\S+)"),
    re.compile(r"^(?P<user>\S+)\s+:\s+TTY="),  # sudo: "alice : TTY=... COMMAND=..."
)

_TS_FORMAT = "%b %d %H:%M:%S %Y"

# A line dated more than this far ahead of the reference is flagged future_dated.
_FUTURE_TOLERANCE = timedelta(days=1)
# How many years back to search for a valid year (covers the Feb-29 leap-day gap).
_YEAR_SEARCH_DEPTH = 8


def _build_dt(mon: str, day: int, hms: str, year: int) -> datetime | None:
    """Construct a UTC datetime for the given components, or None if invalid.

    Returns None for impossible dates (e.g. Feb 29 in a non-leap year) so the
    caller can try another year instead of dropping the line.
    """

    try:
        naive = datetime.strptime(f"{mon} {day} {hms} {year}", _TS_FORMAT)
    except ValueError:
        return None
    return naive.replace(tzinfo=UTC)


def _infer_timestamp(mon: str, day: int, hms: str, reference: datetime) -> datetime | None:
    """Infer the year for a yearless syslog timestamp.

    Syslog carries no year. We assume the most plausible one: the reference year,
    unless the month sits well ahead of the reference month (a December line seen
    in January is last year's), in which case we roll back. Impossible dates in the
    chosen year (Feb 29) fall back to the nearest earlier valid year rather than
    being dropped — never lose a legitimate security event to a calendar quirk.
    """

    dt = _build_dt(mon, day, hms, reference.year)
    # A month far ahead of the reference month means the log wrapped a year boundary.
    if dt is not None and dt.month > reference.month + 1:
        rolled = _build_dt(mon, day, hms, reference.year - 1)
        if rolled is not None:
            return rolled
    if dt is not None:
        return dt
    # reference year was invalid (leap day): search backwards for a valid year.
    for delta in range(1, _YEAR_SEARCH_DEPTH):
        candidate = _build_dt(mon, day, hms, reference.year - delta)
        if candidate is not None:
            return candidate
    return None


class SyslogAuthParser:
    name = "syslog"
    source = LogSource.AUTH

    def __init__(self, reference: datetime | None = None) -> None:
        self._reference = reference

    def match_fraction(self, sample_lines: Sequence[str]) -> float:
        return fraction_matching(_LINE_RE, sample_lines)

    def sniff(self, sample_lines: Sequence[str]) -> bool:
        return self.match_fraction(sample_lines) >= SNIFF_THRESHOLD

    def parse_line(self, file: str, line_no: int, line: str) -> LogEvent | ParseFailure:
        candidate = clean_line(line)
        if not candidate:
            return ParseFailure(file, line_no, "empty line")

        match = _LINE_RE.match(candidate)
        if match is None:
            return ParseFailure(file, line_no, "does not match syslog auth format")

        reference = self._reference or datetime.now(UTC)
        timestamp = _infer_timestamp(match["mon"], int(match["day"]), match["time"], reference)
        if timestamp is None:
            return ParseFailure(file, line_no, "invalid syslog timestamp")

        message = match["msg"]
        extra: dict[str, object] = {
            "program": match["prog"],
            "pid": int(match["pid"]) if match["pid"] else None,
            "host": match["host"],
        }
        if timestamp > reference + _FUTURE_TOLERANCE:
            extra["future_dated"] = True

        return LogEvent(
            source=LogSource.AUTH,
            file=file,
            line_no=line_no,
            timestamp=timestamp,
            raw=candidate,
            ip=_extract_ip(message),
            user=_extract_user(message),
            message=message,
            extra=extra,
        )


def _extract_ip(message: str) -> str | None:
    match = _IP_RE.search(message)
    return match["ip"] if match else None


def _extract_user(message: str) -> str | None:
    for pattern in _USER_RES:
        match = pattern.search(message)
        if match:
            return match["user"]
    return None


# Module-level singleton used by the registry (uses the current year at parse time).
PARSER: Parser = SyslogAuthParser()
