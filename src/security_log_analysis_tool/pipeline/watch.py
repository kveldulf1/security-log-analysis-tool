"""Watch mode: follow growing log files and detect incrementally.

Two collaborators, each independently testable:

* :class:`FileTailer` — a byte-offset tail-follow over one file. It reads only what
  was appended since the last poll and is rotation-aware: a file that shrank (or
  whose inode changed, where the OS reports one) is re-read from the top. Partial
  trailing lines are buffered until their newline arrives, so a half-written line is
  never parsed.
* :class:`IncrementalAnalyzer` — the same stateful detectors the batch engine builds,
  kept alive and fed batch-by-batch. Because every detector prunes via its
  ``SlidingWindowCounter`` and correlation runs over a window-bounded finding buffer,
  memory stays flat under sustained ingestion — the pipeline follows a stream, it
  does not accumulate it.

:class:`WatchSession` ties them together and stops cleanly the instant a caller sets
its stop event (or on ``Ctrl+C``): no thread is left running, no line half-processed.

Documented limitations (inherent to any poll-based tail-follow — for exact,
order-independent results run ``analyze`` over the complete files):

* **Append-only, roughly-chronological ingestion is assumed.** Each poll feeds only
  the newly-appended lines, and the stateful sliding-window detectors require
  per-key non-decreasing timestamps (see ``detection/base.py``). A file that is
  written out of order, or a burst of *older*-timestamped lines that arrives in a
  *later* poll than newer lines from another file, can be under-counted. This is the
  standard ``tail -f`` contract (fail2ban and friends assume the same).
* **Copy-truncate rotation can be missed under a poll race.** Rotation is detected by
  a shrinking file (``size < offset``) or a changed inode; on a platform that reports
  ``st_ino == 0``, a copy-truncate whose replacement file is refilled past the old
  read offset *between two polls* is not seen, and that window's first bytes are
  skipped. Shortening the poll interval narrows the race; the plan (§8) accepts basic
  tail with this documented limitation.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path

from ..config import AppConfig, RuleConfig
from ..correlation.engine import correlate
from ..detection import build_rule
from ..detection.base import Rule
from ..models import Finding, LogEvent, LogSource, ParseFailure
from ..parsers import Parser, get_parser, sniff_parser

_CORRELATION_RULE_TYPE = "multi-vector-correlation"
_DEFAULT_CORRELATION_WINDOW = 600
_READ_CHUNK_LIMIT = 8 * 1024 * 1024  # cap one poll's read so a huge append can't spike memory
# While a file's format is still unresolved in auto mode, retain at most this many
# recent lines as the sniff sample: an unrecognisable (or attacker-controlled garbage)
# file must not grow the pending buffer without bound, and re-sniffing a capped sample
# each poll keeps the work O(1) instead of O(n^2) in lines seen.
_MAX_SNIFF_BUFFER = 100


class FileTailer:
    """Follows one file, yielding only newly-appended complete lines per poll."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._offset = 0
        self._inode: int | None = None
        self._buffer = b""

    def poll(self) -> list[str]:
        """Return complete lines appended since the previous poll.

        A missing file yields ``[]`` (it may appear later). Rotation resets the read
        position to the top so the new file's contents are picked up from line one.
        """

        try:
            stat = self._path.stat()
        except (FileNotFoundError, NotADirectoryError):
            return []
        except OSError:
            return []

        self._handle_rotation(stat.st_ino, stat.st_size)

        try:
            with self._path.open("rb") as handle:
                handle.seek(self._offset)
                chunk = handle.read(_READ_CHUNK_LIMIT)
                self._offset = handle.tell()
        except OSError:
            return []

        data = self._buffer + chunk
        parts = data.split(b"\n")
        self._buffer = parts.pop()  # trailing partial line (or b"" if data ended on a newline)
        return [part.rstrip(b"\r").decode("utf-8", errors="replace") for part in parts]

    def _handle_rotation(self, inode: int, size: int) -> None:
        rotated_inode = self._inode is not None and inode != 0 and inode != self._inode
        truncated = size < self._offset
        if rotated_inode or truncated:
            self._offset = 0
            self._buffer = b""
        self._inode = inode


class IncrementalAnalyzer:
    """Feeds growing batches of events into long-lived detectors and correlation.

    Detectors are stateful across :meth:`feed` calls by design (their sliding-window
    counters and ``_flagged`` sets persist), so a finding fires exactly once as its
    triggering line arrives — no reprocessing of the whole history each poll.
    """

    def __init__(self, config: AppConfig) -> None:
        detector_configs = [
            rc for rc in config.enabled_rules() if rc.type != _CORRELATION_RULE_TYPE
        ]
        self._rules: list[tuple[LogSource | None, Rule]] = [
            (rc.source, build_rule(rc)) for rc in detector_configs
        ]
        self._correlation_configs: list[RuleConfig] = [
            rc for rc in config.enabled_rules() if rc.type == _CORRELATION_RULE_TYPE
        ]
        self._rule_sources: dict[str, LogSource | None] = {
            rc.id: rc.source for rc in detector_configs
        }
        self._correlation_window = max(
            (rc.window_seconds for rc in self._correlation_configs),
            default=_DEFAULT_CORRELATION_WINDOW,
        )
        self._recent_findings: list[Finding] = []
        self._seen_correlations: set[tuple[str | None, tuple[str, ...]]] = set()

    def feed(self, events: Sequence[LogEvent]) -> list[Finding]:
        """Run the new events through every detector; return findings first seen now."""

        if not events:
            return []
        ordered = sorted(events, key=lambda e: e.timestamp)
        new_findings: list[Finding] = []
        for source, rule in self._rules:
            rule_events = ordered if source is None else [e for e in ordered if e.source == source]
            if rule_events:
                new_findings.extend(rule.evaluate(rule_events))
        return new_findings + self._correlate(new_findings)

    def _correlate(self, new_findings: Sequence[Finding]) -> list[Finding]:
        # With no correlation rule configured, findings are never re-examined — so
        # retaining them would be a pure memory leak under sustained ingestion.
        if not self._correlation_configs or not new_findings:
            return []

        self._recent_findings.extend(new_findings)
        newest = max(f.last_seen for f in self._recent_findings)
        cutoff = newest - timedelta(seconds=self._correlation_window)
        self._recent_findings = [f for f in self._recent_findings if f.last_seen >= cutoff]

        fresh: list[Finding] = []
        for correlated in correlate(
            self._recent_findings, self._correlation_configs, self._rule_sources
        ):
            key = (correlated.ip, correlated.correlated_rule_ids)
            if key not in self._seen_correlations:
                self._seen_correlations.add(key)
                fresh.append(correlated)
        return fresh


class WatchSession:
    """Polls a set of files, parsing and detecting only what is newly appended."""

    def __init__(
        self,
        files: Sequence[str],
        config: AppConfig,
        *,
        fmt: str = "auto",
        poll_interval: float = 0.5,
        on_findings: Callable[[list[Finding]], None] | None = None,
    ) -> None:
        self._files = list(files)
        self._analyzer = IncrementalAnalyzer(config)
        self._fmt = fmt
        self._poll_interval = poll_interval
        self._on_findings = on_findings
        self._tailers = {f: FileTailer(f) for f in self._files}
        self._parsers: dict[str, Parser] = {}
        self._pending: dict[str, list[tuple[int, str]]] = {f: [] for f in self._files}
        self._line_no: dict[str, int] = {f: 0 for f in self._files}
        self.event_count = 0
        self.failure_count = 0
        self.finding_count = 0

    def poll_once(self) -> list[Finding]:
        """Read appended lines across all files, parse, detect, return new findings."""

        batch: list[LogEvent] = []
        for file in self._files:
            batch.extend(self._read_file_events(file))
        findings = self._analyzer.feed(batch)
        self.event_count += len(batch)
        self.finding_count += len(findings)
        if findings and self._on_findings is not None:
            self._on_findings(findings)
        return findings

    def run(self, stop_event: threading.Event, *, max_polls: int | None = None) -> None:
        """Poll until ``stop_event`` is set, ``max_polls`` reached, or interrupted."""

        polls = 0
        try:
            while not stop_event.is_set():
                self.poll_once()
                polls += 1
                if max_polls is not None and polls >= max_polls:
                    return
                stop_event.wait(self._poll_interval)
        except KeyboardInterrupt:
            return

    def _read_file_events(self, file: str) -> list[LogEvent]:
        new_lines = self._tailers[file].poll()
        pending = self._pending[file]
        for line in new_lines:
            self._line_no[file] += 1
            pending.append((self._line_no[file], line))
        if not pending:
            return []

        parser = self._parsers.get(file)
        if parser is None:
            parser = self._resolve_parser([line for _, line in pending])
            if parser is None:
                # Not enough signal to sniff a format yet; keep only the most recent
                # lines as the sample so the buffer (and the per-poll sniff cost) stay
                # bounded for a file that never resolves.
                if len(pending) > _MAX_SNIFF_BUFFER:
                    del pending[:-_MAX_SNIFF_BUFFER]
                return []
            self._parsers[file] = parser

        events: list[LogEvent] = []
        for line_no, line in pending:
            result = parser.parse_line(file, line_no, line)
            if isinstance(result, ParseFailure):
                self.failure_count += 1
            else:
                events.append(result)
        pending.clear()
        return events

    def _resolve_parser(self, sample: Sequence[str]) -> Parser | None:
        if self._fmt.strip().lower() != "auto":
            return get_parser(self._fmt)
        return sniff_parser(sample)
