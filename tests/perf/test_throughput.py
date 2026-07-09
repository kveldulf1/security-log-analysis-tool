"""Performance: streaming throughput and bounded memory over a 100k-line log.

Proves the detection pipeline *streams* rather than materialising the whole file:
lines are parsed and fed to the long-lived incremental detectors in fixed batches,
so the traced-memory peak stays flat as the line count grows. Floors are calibrated
locally with a generous CI margin — this is a "no pathological blowup" guard, not a
micro-benchmark.
"""

from __future__ import annotations

import time
import tracemalloc
from pathlib import Path

import pytest

from security_log_analysis_tool.config import load_rules
from security_log_analysis_tool.models import LogEvent
from security_log_analysis_tool.parsers import get_parser
from security_log_analysis_tool.pipeline.watch import IncrementalAnalyzer

pytestmark = pytest.mark.perf

_ROOT = Path(__file__).resolve().parents[2]
_RULES_PATH = _ROOT / "config" / "rules.yaml"

_TOTAL_LINES = 100_000
_BATCH = 500
_LINES_PER_SECOND_FLOOR = 3_000  # generous CI margin (local is far higher)
_PEAK_MEMORY_CAP_MB = 150


def _write_synthetic_log(path: Path, count: int) -> None:
    """Write ``count`` well-formed Apache lines, IP and timestamp spread so the
    sliding-window detectors continuously prune (bounded memory)."""

    ts_base = 10 * 3600  # seconds into 03/Jul/2025
    with path.open("w", encoding="utf-8") as handle:
        for i in range(count):
            octet = i % 250 + 1
            secs = ts_base + i
            hh, mm, ss = secs // 3600 % 24, secs // 60 % 60, secs % 60
            handle.write(
                f"10.20.30.{octet} - - [03/Jul/2025:{hh:02d}:{mm:02d}:{ss:02d} +0000] "
                f'"GET /page/{i % 1000} HTTP/1.1" 200 1234 "-" "agent"\n'
            )


def _stream_analyze(path: Path) -> tuple[float, int]:
    """Stream-parse ``path`` through the incremental analyzer; return (peak_bytes, events)."""

    parser = get_parser("apache")
    analyzer = IncrementalAnalyzer(load_rules(_RULES_PATH))
    batch: list[LogEvent] = []
    events = 0

    tracemalloc.start()
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            result = parser.parse_line(str(path), line_no, line.rstrip("\n"))
            if isinstance(result, LogEvent):
                batch.append(result)
            if len(batch) >= _BATCH:
                analyzer.feed(batch)
                events += len(batch)
                batch.clear()
        if batch:
            analyzer.feed(batch)
            events += len(batch)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak, events


@pytest.mark.timeout(120)
def test_streaming_throughput_meets_floor_with_bounded_memory(tmp_path: Path):
    log = tmp_path / "big.log"
    _write_synthetic_log(log, _TOTAL_LINES)

    start = time.monotonic()
    peak, events = _stream_analyze(log)
    elapsed = time.monotonic() - start

    assert events == _TOTAL_LINES
    lines_per_second = events / elapsed
    assert lines_per_second >= _LINES_PER_SECOND_FLOOR, (
        f"throughput {lines_per_second:.0f} lines/s below floor {_LINES_PER_SECOND_FLOOR}"
    )
    peak_mb = peak / (1024 * 1024)
    assert peak_mb < _PEAK_MEMORY_CAP_MB, f"peak memory {peak_mb:.1f} MB exceeded cap"


@pytest.mark.timeout(120)
def test_memory_peak_is_sublinear_in_line_count(tmp_path: Path):
    small = tmp_path / "small.log"
    large = tmp_path / "large.log"
    _write_synthetic_log(small, 20_000)
    _write_synthetic_log(large, 100_000)

    peak_small, _ = _stream_analyze(small)
    peak_large, _ = _stream_analyze(large)

    # 5x the lines must NOT mean ~5x the peak — streaming keeps it near-flat.
    assert peak_large < peak_small * 2.5, (
        f"peak grew {peak_large / peak_small:.1f}x for 5x lines — not streaming"
    )
