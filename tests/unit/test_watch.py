"""Unit tests for watch mode: the byte-offset tailer, the incremental analyzer,
and the polling session — all driven synchronously (no background threads)."""

from __future__ import annotations

import threading
from dataclasses import replace as dc_replace
from datetime import datetime, timedelta
from pathlib import Path

from fixtures import apache_line, syslog_line  # type: ignore[import-not-found]

from security_log_analysis_tool.config import load_rules
from security_log_analysis_tool.models import Finding, LogEvent
from security_log_analysis_tool.parsers import get_parser
from security_log_analysis_tool.parsers.syslog_auth import SyslogAuthParser
from security_log_analysis_tool.pipeline.watch import (
    _MAX_SNIFF_BUFFER,
    FileTailer,
    IncrementalAnalyzer,
    WatchSession,
)

_ROOT = Path(__file__).resolve().parents[2]
_RULES_PATH = _ROOT / "config" / "rules.yaml"
_START = datetime.fromisoformat("2025-07-03T10:00:00+00:00")


def _append(path: Path, *lines: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")


def _web_failures(ip: str, count: int, *, path: str = "/login") -> list[LogEvent]:
    parser = get_parser("apache")
    events: list[LogEvent] = []
    for i in range(count):
        line = apache_line(ip=ip, status=401, path=path, when=_START + timedelta(seconds=i))
        event = parser.parse_line("access.log", i + 1, line)
        assert isinstance(event, LogEvent)
        events.append(event)
    return events


# --- FileTailer -------------------------------------------------------------


def test_tailer_missing_file_yields_nothing(tmp_path: Path):
    tailer = FileTailer(tmp_path / "absent.log")
    assert tailer.poll() == []


def test_tailer_returns_only_newly_appended_lines(tmp_path: Path):
    log = tmp_path / "a.log"
    log.write_text("line1\nline2\n", encoding="utf-8")
    tailer = FileTailer(log)
    assert tailer.poll() == ["line1", "line2"]
    assert tailer.poll() == []  # nothing new
    _append(log, "line3")
    assert tailer.poll() == ["line3"]


def test_tailer_buffers_partial_trailing_line(tmp_path: Path):
    log = tmp_path / "b.log"
    log.write_text("complete\npartial", encoding="utf-8")  # no trailing newline
    tailer = FileTailer(log)
    assert tailer.poll() == ["complete"]  # partial withheld
    with log.open("a", encoding="utf-8") as handle:
        handle.write("-now-done\n")
    assert tailer.poll() == ["partial-now-done"]


def test_tailer_handles_crlf(tmp_path: Path):
    log = tmp_path / "crlf.log"
    log.write_bytes(b"one\r\ntwo\r\n")
    tailer = FileTailer(log)
    assert tailer.poll() == ["one", "two"]


def test_tailer_detects_rotation_by_truncation(tmp_path: Path):
    log = tmp_path / "rot.log"
    log.write_text("old-a\nold-b\n", encoding="utf-8")
    tailer = FileTailer(log)
    assert tailer.poll() == ["old-a", "old-b"]
    # Rotation: file replaced with a shorter one -> read from the top again.
    log.write_text("fresh\n", encoding="utf-8")
    assert tailer.poll() == ["fresh"]


# --- IncrementalAnalyzer ----------------------------------------------------


def test_incremental_analyzer_fires_once_at_threshold():
    analyzer = IncrementalAnalyzer(load_rules(_RULES_PATH))
    events = _web_failures("198.51.100.9", 5)

    # First four failures: below threshold, nothing fires.
    assert analyzer.feed(events[:4]) == []
    # Fifth failure crosses the threshold in the same window.
    fired = analyzer.feed(events[4:])
    brute = [f for f in fired if f.rule_id == "web-brute-force"]
    assert len(brute) == 1
    # Further failures from the same IP do not re-fire.
    more = _web_failures("198.51.100.9", 3)
    assert [f for f in analyzer.feed(more) if f.rule_id == "web-brute-force"] == []


def test_incremental_analyzer_empty_batch_is_noop():
    analyzer = IncrementalAnalyzer(load_rules(_RULES_PATH))
    assert analyzer.feed([]) == []


def test_incremental_analyzer_without_correlation_does_not_retain_findings():
    # With no correlation rule configured, findings must not accumulate (memory leak
    # regression) — nothing ever re-examines them.
    config = load_rules(_RULES_PATH)
    no_corr = dc_replace(
        config, rules=tuple(r for r in config.rules if r.type != "multi-vector-correlation")
    )
    analyzer = IncrementalAnalyzer(no_corr)
    for i in range(20):
        fired = analyzer.feed(_web_failures(f"10.0.{i}.1", 5))
        assert any(f.rule_id == "web-brute-force" for f in fired)
    assert analyzer._recent_findings == []


def test_incremental_analyzer_correlates_across_sources():
    analyzer = IncrementalAnalyzer(load_rules(_RULES_PATH))
    ip = "10.0.0.50"

    web_findings = analyzer.feed(_web_failures(ip, 5))
    assert any(f.rule_id == "web-brute-force" for f in web_findings)

    # Bind the syslog reference to the web log's year so both sources land in the
    # same correlation window (a synthetic-fixture concern; live tails are all "now").
    auth_parser = SyslogAuthParser(reference=_START)
    auth_events: list[LogEvent] = []
    for i in range(5):
        line = syslog_line(
            when=_START + timedelta(seconds=10 + i),
            message=f"Failed password for root from {ip} port 22 ssh2",
        )
        event = auth_parser.parse_line("auth.log", i + 1, line)
        assert isinstance(event, LogEvent)
        auth_events.append(event)

    fired = analyzer.feed(auth_events)
    correlated = [f for f in fired if f.correlated_rule_ids]
    assert len(correlated) == 1
    assert correlated[0].ip == ip
    # Feeding the same evidence again does not duplicate the correlation.
    assert not [f for f in analyzer.feed(_web_failures(ip, 1)) if f.correlated_rule_ids]


# --- WatchSession -----------------------------------------------------------


def test_watch_session_detects_appended_lines(tmp_path: Path):
    log = tmp_path / "access.log"
    log.write_text("", encoding="utf-8")
    seen: list[Finding] = []
    session = WatchSession(
        [str(log)],
        load_rules(_RULES_PATH),
        fmt="apache",
        on_findings=seen.extend,
    )

    lines = [
        apache_line(ip="203.0.113.7", status=401, path="/login", when=_START + timedelta(seconds=i))
        for i in range(5)
    ]
    _append(log, *lines)

    findings = session.poll_once()
    assert any(f.rule_id == "web-brute-force" for f in findings)
    assert seen == findings
    assert session.event_count == 5
    assert session.finding_count >= 1


def test_watch_session_bounds_pending_for_unrecognized_file(tmp_path: Path):
    # An auto-format file that never resolves must not grow the pending buffer without
    # bound (resource-exhaustion regression on untrusted input).
    log = tmp_path / "garbage.log"
    log.write_text("", encoding="utf-8")
    session = WatchSession([str(log)], load_rules(_RULES_PATH), fmt="auto")
    for _ in range(5):
        _append(log, *["!!! not any recognized log format !!!"] * 100)
        assert session.poll_once() == []  # never resolves a parser
    assert len(session._pending[str(log)]) <= _MAX_SNIFF_BUFFER


def test_watch_session_run_stops_immediately_when_flagged(tmp_path: Path):
    log = tmp_path / "idle.log"
    log.write_text("", encoding="utf-8")
    session = WatchSession([str(log)], load_rules(_RULES_PATH), fmt="apache")
    stop = threading.Event()
    stop.set()  # already asked to stop
    session.run(stop)  # returns without polling
    assert session.event_count == 0


def test_watch_session_run_honours_max_polls(tmp_path: Path):
    log = tmp_path / "x.log"
    log.write_text("", encoding="utf-8")
    session = WatchSession([str(log)], load_rules(_RULES_PATH), fmt="apache", poll_interval=0.0)
    stop = threading.Event()
    session.run(stop, max_polls=3)
    assert session.event_count == 0  # nothing was appended, but it polled and exited cleanly
