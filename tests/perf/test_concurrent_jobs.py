"""Performance: 20 concurrent analysis jobs finish without hanging.

Homework-scale by design (§3.5 / §6). Production scaling — sustained load, larger
files, more workers, a distributed broker — lives behind the ``JobQueue`` seam and
is documented in the README, not benchmarked here. The point of this test is the
"no hang" contract: many jobs in, all DONE well before a soft deadline, the pool
shuts down cleanly, and pytest-timeout hard-kills a genuine deadlock.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fixtures import apache_line  # type: ignore[import-not-found]

from security_log_analysis_tool.config import load_rules
from security_log_analysis_tool.models import JobStatus
from security_log_analysis_tool.pipeline.engine import AnalysisEngine
from security_log_analysis_tool.pipeline.queue import EngineWorker, JobQueue

_ROOT = Path(__file__).resolve().parents[2]
_RULES_PATH = _ROOT / "config" / "rules.yaml"
_JOBS = 20
_LINES_PER_FILE = 300
_SOFT_DEADLINE_SECONDS = 60.0

pytestmark = pytest.mark.perf


def _write_job_log(path: Path, job_index: int) -> None:
    """A per-job log whose IP offset makes exactly one brute-force finding expected."""

    attacker = f"10.10.{job_index}.5"
    benign = f"192.168.{job_index}.9"
    base = datetime(2025, 7, 3, 10, 0, 0, tzinfo=UTC)
    lines = [
        apache_line(ip=attacker, status=401, path="/login", when=base + timedelta(seconds=i))
        for i in range(8)  # > brute-force threshold (5)
    ]
    lines += [
        apache_line(
            ip=benign, status=200, path="/index.html", when=base + timedelta(seconds=20 + i)
        )
        for i in range(_LINES_PER_FILE - 8)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _wait_all(queue: JobQueue, job_ids: list[str], statuses, timeout: float) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all((queue.get(jid) or None) and queue.get(jid).status in statuses for jid in job_ids):
            return True
        time.sleep(0.02)
    return False


@pytest.mark.timeout(90)
def test_twenty_concurrent_jobs_all_finish(tmp_path: Path):
    files = []
    for i in range(_JOBS):
        log = tmp_path / f"job_{i}.log"
        _write_job_log(log, i)
        files.append(str(log))

    baseline_threads = threading.active_count()
    engine = AnalysisEngine(load_rules(_RULES_PATH))
    queue = JobQueue(EngineWorker(engine), max_pending=32, workers=4)

    job_ids = [queue.submit([f], submitted_by="perf").job_id for f in files]

    assert _wait_all(queue, job_ids, {JobStatus.DONE}, _SOFT_DEADLINE_SECONDS), (
        "not all jobs reached DONE before the soft deadline"
    )

    # Every job produced its expected brute-force finding.
    for jid in job_ids:
        job = queue.get(jid)
        assert job.status is JobStatus.DONE
        assert any(f.rule_id == "web-brute-force" for f in job.findings)

    assert queue.shutdown(timeout=10) is True
    assert threading.active_count() == baseline_threads


@pytest.mark.timeout(90)
def test_poison_job_does_not_stop_the_others(tmp_path: Path):
    good = tmp_path / "good.log"
    _write_job_log(good, 0)
    missing = str(tmp_path / "does_not_exist.log")

    engine = AnalysisEngine(load_rules(_RULES_PATH))
    with JobQueue(EngineWorker(engine), max_pending=8, workers=2) as queue:
        bad_id = queue.submit([missing], submitted_by="perf").job_id
        good_ids = [queue.submit([str(good)], submitted_by="perf").job_id for _ in range(5)]

        assert _wait_all(queue, [bad_id], {JobStatus.FAILED}, 30.0)
        failed = queue.get(bad_id)
        assert failed.error and "not found" in failed.error.lower()

        assert _wait_all(queue, good_ids, {JobStatus.DONE}, 30.0)
        for jid in good_ids:
            assert queue.get(jid).status is JobStatus.DONE
