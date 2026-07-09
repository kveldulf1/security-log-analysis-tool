"""Performance: backpressure under saturation.

Submitting well past capacity must reject the excess *promptly* with ``QueueFull``
rather than block or grow an unbounded backlog; every accepted job must still run to
completion once the pressure clears, and the queue must drain to a fully-terminal
state. This is the "bounded queue = explicit backpressure" contract from §3.5.
"""

from __future__ import annotations

import threading
import time

import pytest

from security_log_analysis_tool.models import JobStatus
from security_log_analysis_tool.pipeline.engine import AnalysisResult
from security_log_analysis_tool.pipeline.queue import JobQueue, QueueFull

pytestmark = pytest.mark.perf

_MAX_PENDING = 8
_WORKERS = 4


class _GatedWorker:
    """Every worker blocks until released, so the queue reliably saturates."""

    def __init__(self) -> None:
        self._release = threading.Event()

    def release(self) -> None:
        self._release.set()

    def run(self, job, cancel):  # noqa: ARG002 - protocol signature
        self._release.wait(10.0)
        return AnalysisResult(events=(), failures=(), findings=())


@pytest.mark.timeout(60)
def test_saturation_rejects_excess_promptly_and_drains():
    worker = _GatedWorker()
    queue = JobQueue(worker, max_pending=_MAX_PENDING, workers=_WORKERS)

    accepted: list[str] = []
    rejections = 0
    attempts = 2 * _MAX_PENDING + _WORKERS + 4  # comfortably beyond total capacity

    for i in range(attempts):
        start = time.monotonic()
        try:
            job = queue.submit([f"{i}.log"], submitted_by="perf")
        except QueueFull:
            elapsed = time.monotonic() - start
            assert elapsed < 0.1, f"QueueFull took {elapsed:.3f}s — backpressure must be prompt"
            rejections += 1
        else:
            accepted.append(job.job_id)

    # The queue pushed back: some submissions were rejected, and no more than the
    # queue+worker capacity was ever accepted at once.
    assert rejections >= 1
    assert len(accepted) <= _MAX_PENDING + _WORKERS

    # Release the workers; every accepted job completes and the queue fully drains.
    worker.release()
    assert queue.shutdown(timeout=15) is True
    for jid in accepted:
        assert queue.get(jid).status is JobStatus.DONE
    non_terminal = [
        j for j in queue.list_jobs() if j.status in {JobStatus.QUEUED, JobStatus.RUNNING}
    ]
    assert non_terminal == []
