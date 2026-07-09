"""Performance: sustained watch-mode ingestion stays flat.

Appending batch after batch to a live-watched file must not make processing lag
creep up or memory grow without bound — the incremental analyzer prunes via its
sliding windows and never buffers the whole stream. Timing/memory floors are loose
on purpose (CI variance); the invariant under test is "no unbounded growth", not a
precise number.
"""

from __future__ import annotations

import statistics
import tracemalloc
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from security_log_analysis_tool.config import load_rules
from security_log_analysis_tool.pipeline.watch import WatchSession

pytestmark = pytest.mark.perf

_ROOT = Path(__file__).resolve().parents[2]
_RULES_PATH = _ROOT / "config" / "rules.yaml"

_ROUNDS = 40
_LINES_PER_ROUND = 250


def _batch(round_index: int) -> list[str]:
    base = datetime(2025, 7, 3, 10, 0, 0, tzinfo=UTC) + timedelta(
        seconds=round_index * _LINES_PER_ROUND
    )
    lines = []
    for i in range(_LINES_PER_ROUND):
        when = base + timedelta(seconds=i)
        stamp = when.strftime("%d/%b/%Y:%H:%M:%S %z")
        octet = i % 250 + 1
        lines.append(f'172.16.0.{octet} - - [{stamp}] "GET /page/{i} HTTP/1.1" 200 900 "-" "a"')
    return lines


@pytest.mark.timeout(90)
def test_sustained_ingestion_no_lag_or_memory_growth(tmp_path: Path):
    log = tmp_path / "live.log"
    log.write_text("", encoding="utf-8")
    session = WatchSession([str(log)], load_rules(_RULES_PATH), fmt="apache")

    durations: list[float] = []
    memory_samples: list[int] = []

    tracemalloc.start()
    import time

    for round_index in range(_ROUNDS):
        with log.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(_batch(round_index)) + "\n")
        start = time.monotonic()
        session.poll_once()
        durations.append(time.monotonic() - start)
        current, _ = tracemalloc.get_traced_memory()
        memory_samples.append(current)
    tracemalloc.stop()

    assert session.event_count == _ROUNDS * _LINES_PER_ROUND

    # Lag does not creep up: the last fifth of polls is not dramatically slower than
    # the first fifth (median smooths per-poll noise).
    fifth = _ROUNDS // 5
    early_lag = statistics.median(durations[:fifth])
    late_lag = statistics.median(durations[-fifth:])
    assert late_lag <= early_lag * 3.0 + 0.01, (
        f"processing lag grew from {early_lag:.4f}s to {late_lag:.4f}s"
    )

    # Memory stays bounded: retained state does not scale with total lines ingested.
    early_mem = statistics.median(memory_samples[:fifth])
    late_mem = statistics.median(memory_samples[-fifth:])
    assert late_mem <= early_mem * 2.0, (
        f"retained memory grew from {early_mem} to {late_mem} bytes over ingestion"
    )
