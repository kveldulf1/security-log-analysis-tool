"""Parser protocol and shared helpers.

A parser maps a single raw line to exactly one of ``LogEvent`` or ``ParseFailure``
with no I/O and no exceptions — a malformed line is data, never a crash. Every line
is truncated to :data:`MAX_LINE_LENGTH` before any regex runs, which bounds parse
time per line and neutralises oversized-input / ReDoS amplification.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ..models import LogEvent, LogSource, ParseFailure

# Lines longer than this are truncated before matching. 8 KiB comfortably fits any
# legitimate access/syslog line while capping worst-case regex work per line.
MAX_LINE_LENGTH = 8192

# Fraction of non-blank sample lines a parser must recognise to claim a format.
SNIFF_THRESHOLD = 0.6


def clean_line(line: str) -> str:
    """Strip the trailing newline and truncate to the ReDoS-safe maximum length."""

    return line.rstrip("\r\n")[:MAX_LINE_LENGTH]


def fraction_matching(pattern: re.Pattern[str], sample_lines: Sequence[str]) -> float:
    """Return the fraction of non-blank sample lines whose start matches ``pattern``."""

    considered = [ln for ln in sample_lines if ln.strip()]
    if not considered:
        return 0.0
    hits = sum(1 for ln in considered if pattern.match(clean_line(ln)))
    return hits / len(considered)


@runtime_checkable
class Parser(Protocol):
    """Structural type for a log-line parser."""

    name: str
    source: LogSource

    def match_fraction(self, sample_lines: Sequence[str]) -> float:
        """Return how strongly this parser recognises the sample (0.0-1.0)."""

    def sniff(self, sample_lines: Sequence[str]) -> bool:
        """Return True if this parser recognises the given sample lines."""

    def parse_line(self, file: str, line_no: int, line: str) -> LogEvent | ParseFailure:
        """Normalize one raw line. Never raises."""
