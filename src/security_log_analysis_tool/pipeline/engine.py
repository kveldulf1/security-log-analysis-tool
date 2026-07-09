"""The analysis engine: files -> events -> rule detectors -> correlation -> findings.

Every line is parsed independently and a bad line becomes a counted, WARN-logged
``ParseFailure`` rather than aborting the run — one malformed line must never take
down an otherwise-good analysis (fail closed, never crash on untrusted input).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..config import AppConfig, ConfigError
from ..correlation.engine import correlate
from ..detection import build_rule
from ..models import Finding, LogEvent, LogSource, ParseFailure
from ..parsers import Parser, UnknownFormatError, parser_for
from ..parsers.syslog_auth import SyslogAuthParser

logger = logging.getLogger(__name__)

_SNIFF_SAMPLE_LINES = 20
_CORRELATION_RULE_TYPE = "multi-vector-correlation"


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    events: tuple[LogEvent, ...]
    failures: tuple[ParseFailure, ...]
    findings: tuple[Finding, ...]


class AnalysisEngine:
    """Runs the full parse -> detect -> correlate pipeline over a set of files."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def analyze(self, files: Sequence[str], fmt: str = "auto") -> AnalysisResult:
        events: list[LogEvent] = []
        failures: list[ParseFailure] = []
        pending_auth: list[tuple[str, list[str]]] = []

        for file in files:
            lines = self._read_lines(file)
            parser = self._resolve_parser(file, fmt, lines)
            if parser.source is LogSource.AUTH:
                # Syslog timestamps carry no year. Defer parsing until every
                # absolute-year (web) file has been read, so the reference instant
                # used to resolve them (see _infer_reference) reflects the rest of
                # this run instead of the moment the tool happens to execute.
                pending_auth.append((file, lines))
                continue
            file_events, file_failures = self._parse_lines(parser, file, lines)
            events.extend(file_events)
            failures.extend(file_failures)

        if pending_auth:
            reference = self._infer_reference(events)
            auth_parser = SyslogAuthParser(reference=reference)
            for file, lines in pending_auth:
                file_events, file_failures = self._parse_lines(auth_parser, file, lines)
                events.extend(file_events)
                failures.extend(file_failures)

        events.sort(key=lambda e: e.timestamp)
        for failure in failures:
            logger.warning(
                "parse failure in %s:%d: %s", failure.file, failure.line_no, failure.reason
            )

        detector_configs = [
            rc for rc in self._config.enabled_rules() if rc.type != _CORRELATION_RULE_TYPE
        ]
        correlation_configs = [
            rc for rc in self._config.enabled_rules() if rc.type == _CORRELATION_RULE_TYPE
        ]
        rule_sources = {rc.id: rc.source for rc in detector_configs}

        findings: list[Finding] = []
        for rule_config in detector_configs:
            rule_events = (
                events
                if rule_config.source is None
                else [e for e in events if e.source == rule_config.source]
            )
            rule = build_rule(rule_config)
            findings.extend(rule.evaluate(rule_events))

        findings.extend(correlate(findings, correlation_configs, rule_sources))

        return AnalysisResult(
            events=tuple(events), failures=tuple(failures), findings=tuple(findings)
        )

    @staticmethod
    def _infer_reference(events: Sequence[LogEvent]) -> datetime:
        """Pick the instant used to resolve yearless syslog timestamps.

        Uses the latest already-parsed absolute-year (web) event timestamp when
        one exists, so a fixed historical dataset analyzed alongside a web log
        stays internally consistent regardless of today's wall-clock date;
        otherwise falls back to the current UTC time — the live-analysis case,
        matching the parser's own documented default.
        """

        if events:
            return max(e.timestamp for e in events)
        return datetime.now(UTC)

    def _read_lines(self, file: str) -> list[str]:
        path = Path(file)
        try:
            return path.read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError as exc:
            raise ConfigError(f"log file not found: {file}") from exc
        except OSError as exc:
            raise ConfigError(f"cannot read log file {file}: {exc}") from exc

    def _resolve_parser(self, file: str, fmt: str, lines: list[str]) -> Parser:
        try:
            return parser_for(fmt, lines[:_SNIFF_SAMPLE_LINES])
        except UnknownFormatError as exc:
            raise ConfigError(f"{file}: {exc}") from exc

    @staticmethod
    def _parse_lines(
        parser: Parser, file: str, lines: list[str]
    ) -> tuple[list[LogEvent], list[ParseFailure]]:
        events: list[LogEvent] = []
        failures: list[ParseFailure] = []
        for line_no, line in enumerate(lines, start=1):
            result = parser.parse_line(file, line_no, line)
            (failures if isinstance(result, ParseFailure) else events).append(result)
        return events, failures
