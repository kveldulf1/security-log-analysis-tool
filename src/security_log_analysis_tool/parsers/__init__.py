"""Parser registry and format sniffer.

Public API for the rest of the app: pick a parser by explicit name, or let
``parser_for`` auto-detect from a sample of lines.
"""

from __future__ import annotations

from collections.abc import Sequence

from .apache_access import PARSER as _APACHE
from .apache_access import ApacheAccessParser
from .base import MAX_LINE_LENGTH, SNIFF_THRESHOLD, Parser, clean_line
from .syslog_auth import PARSER as _SYSLOG
from .syslog_auth import SyslogAuthParser

# Name (and friendly aliases) -> parser singleton.
_REGISTRY: dict[str, Parser] = {
    "apache": _APACHE,
    "web": _APACHE,
    "access": _APACHE,
    "syslog": _SYSLOG,
    "auth": _SYSLOG,
}

# Order matters only for tie-breaks; sniff scores decide in practice.
_SNIFF_ORDER: tuple[Parser, ...] = (_APACHE, _SYSLOG)


class UnknownFormatError(Exception):
    """Raised when no registered parser recognises the sample."""


def available_formats() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def get_parser(name: str) -> Parser:
    """Return the parser registered under ``name`` (case-insensitive)."""

    try:
        return _REGISTRY[name.strip().lower()]
    except KeyError as exc:
        valid = ", ".join(available_formats())
        raise UnknownFormatError(f"unknown format {name!r}; valid: {valid}") from exc


def sniff_parser(sample_lines: Sequence[str]) -> Parser | None:
    """Return the best-matching parser for the sample, or None if none recognise it.

    Each parser scores the sample once via ``match_fraction``; the highest score at
    or above :data:`SNIFF_THRESHOLD` wins (registration order breaks ties).
    """

    best: Parser | None = None
    best_score = 0.0
    for parser in _SNIFF_ORDER:
        score = parser.match_fraction(sample_lines)
        if score >= SNIFF_THRESHOLD and score > best_score:
            best, best_score = parser, score
    return best


def parser_for(fmt: str, sample_lines: Sequence[str]) -> Parser:
    """Resolve a parser for ``fmt`` ('auto' sniffs; otherwise an explicit name)."""

    if fmt.strip().lower() == "auto":
        parser = sniff_parser(sample_lines)
        if parser is None:
            raise UnknownFormatError("could not auto-detect log format from sample")
        return parser
    return get_parser(fmt)


__all__ = [
    "MAX_LINE_LENGTH",
    "ApacheAccessParser",
    "Parser",
    "SyslogAuthParser",
    "UnknownFormatError",
    "available_formats",
    "clean_line",
    "get_parser",
    "parser_for",
    "sniff_parser",
]
