"""Parser for Apache/nginx Common and Combined access-log formats."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime

from ..models import LogEvent, LogSource, ParseFailure
from .base import SNIFF_THRESHOLD, Parser, clean_line, fraction_matching

# 10.0.0.50 - alice [03/Jul/2025:10:15:32 +0000] "POST /login HTTP/1.1" 200 1234 "-" "UA"
# Anchored; every quantifier operates on a negated class or \S — no nested repeats.
_LINE_RE = re.compile(
    r"^(?P<ip>\S+)\s+\S+\s+(?P<user>\S+)\s+"
    r"\[(?P<ts>[^\]]+)\]\s+"
    r'"(?P<request>[^"]*)"\s+'
    r"(?P<status>\d{3})\s+(?P<size>\d+|-)"
    r'(?:\s+"(?P<referer>[^"]*)"\s+"(?P<agent>[^"]*)")?\s*$'
)

_TS_FORMAT = "%d/%b/%Y:%H:%M:%S %z"


class ApacheAccessParser:
    name = "apache"
    source = LogSource.WEB

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
            return ParseFailure(file, line_no, "does not match Apache access-log format")

        try:
            timestamp = datetime.strptime(match["ts"], _TS_FORMAT).astimezone(UTC)
        except ValueError:
            return ParseFailure(file, line_no, "invalid or missing Apache timestamp")

        method, path, protocol = _split_request(match["request"])
        return LogEvent(
            source=LogSource.WEB,
            file=file,
            line_no=line_no,
            timestamp=timestamp,
            raw=candidate,
            ip=_none_if_dash(match["ip"]),
            user=_none_if_dash(match["user"]),
            method=method,
            path=path,
            status=int(match["status"]),
            size=None if match["size"] == "-" else int(match["size"]),
            extra={
                "protocol": protocol,
                "referer": match["referer"],
                "user_agent": match["agent"],
            },
        )


def _split_request(request: str) -> tuple[str | None, str | None, str | None]:
    parts = request.split(" ")
    method = parts[0] if parts and parts[0] else None
    path = parts[1] if len(parts) > 1 else None
    protocol = parts[2] if len(parts) > 2 else None
    return method, path, protocol


def _none_if_dash(value: str) -> str | None:
    return None if value == "-" else value


# Module-level singleton used by the registry.
PARSER: Parser = ApacheAccessParser()
