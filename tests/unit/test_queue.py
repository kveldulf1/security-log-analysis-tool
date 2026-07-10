"""Unit tests for the in-process job queue: lifecycle, backpressure, cancel,
graceful shutdown, and the no-pool-poisoning guarantee.

Workers here are deterministic test doubles (canned results, controllable blocking)
so every state transition is observed without racing on wall-clock timing.
"""

from __future__ import annotations

import threading
import time

import pytest

from security_log_analysis_tool.models import JobStatus
from security_log_analysis_tool.pipeline.engine import AnalysisResult
from security_log_analysis_tool.pipeline.queue import (
    CancelToken,
    JobCancelled,
    JobQueue,
    QueueFull,
)

_EMPTY_RESULT = AnalysisResult(events=(), failures=(), findings=())


def _wait_for(queue: JobQueue, job_id: str, status: JobStatus, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = queue.get(job_id)
        if job is not None and job.status is status:
            return job
        time.sleep(0.005)
    raise AssertionError(f"job {job_id} did not reach {status}: {queue.get(job_id)}")


class _CannedWorker:
    """Returns a fixed result, recording how many jobs it ran."""

    def __init__(self, result: AnalysisResult = _EMPTY_RESULT) -> None:
        self._result = result
        self.runs = 0

    def run(self, job, cancel):  # noqa: ARG002 - protocol signature
        self.runs += 1
        return self._result


class _BlockingWorker:
    """Blocks in ``run`` until released, so a job can be pinned in RUNNING."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, job, cancel):  # noqa: ARG002
        self.started.set()
        self.release.wait(5.0)
        return _EMPTY_RESULT


class _PollingWorker:
    """Loops while polling its cancel token, honouring a mid-run cancel."""

    def __init__(self) -> None:
        self.started = threading.Event()

    def run(self, job, cancel):  # noqa: ARG002
        self.started.set()
        for _ in range(1000):
            cancel.raise_if_cancelled()
            time.sleep(0.005)
        return _EMPTY_RESULT


class _RaisingWorker:
    """Raises on the first job, succeeds afterwards — exercises pool survival."""

    def __init__(self, message: str) -> None:
        self._message = message
        self.runs = 0

    def run(self, job, cancel):  # noqa: ARG002
        self.runs += 1
        if self.runs == 1:
            raise RuntimeError(self._message)
        return _EMPTY_RESULT


# --- Cancel token -----------------------------------------------------------


def test_cancel_token_raises_only_after_cancel():
    token = CancelToken()
    assert not token.cancelled
    token.raise_if_cancelled()  # no-op
    token.cancel()
    assert token.cancelled
    with pytest.raises(JobCancelled):
        token.raise_if_cancelled()


# --- Happy-path lifecycle ---------------------------------------------------


def test_submit_runs_to_done_with_stats():
    findings_result = AnalysisResult(events=(1, 2, 3), failures=(4,), findings=(5, 6))  # type: ignore[arg-type]
    worker = _CannedWorker(findings_result)
    with JobQueue(worker, workers=2) as queue:
        job = queue.submit(["a.log"], submitted_by="tester")
        assert job.status is JobStatus.QUEUED
        done = _wait_for(queue, job.job_id, JobStatus.DONE)
    assert done.findings == (5, 6)
    assert done.stats["events"] == 3
    assert done.stats["failures"] == 1
    assert done.stats["findings"] == 2
    assert done.stats["duration_seconds"] >= 0.0
    assert done.started_at is not None and done.finished_at is not None


def test_list_jobs_and_get():
    worker = _CannedWorker()
    with JobQueue(worker, workers=1) as queue:
        first = queue.submit(["a.log"], submitted_by="u")
        second = queue.submit(["b.log"], submitted_by="u")
        _wait_for(queue, first.job_id, JobStatus.DONE)
        _wait_for(queue, second.job_id, JobStatus.DONE)
        ids = {j.job_id for j in queue.list_jobs()}
    assert ids == {first.job_id, second.job_id}
    assert queue.get("does-not-exist") is None


# --- Backpressure -----------------------------------------------------------


def test_backpressure_raises_queue_full():
    worker = _BlockingWorker()
    with JobQueue(worker, max_pending=2, workers=1) as queue:
        first = queue.submit(["1.log"], submitted_by="u")
        assert worker.started.wait(2.0)  # worker now busy, holding the first job
        queue.submit(["2.log"], submitted_by="u")  # fills slot 1
        queue.submit(["3.log"], submitted_by="u")  # fills slot 2 (queue now full)
        with pytest.raises(QueueFull):
            queue.submit(["4.log"], submitted_by="u")
        # The rejected job leaves no dangling registry entry.
        assert len(queue.list_jobs()) == 3
        worker.release.set()
        _wait_for(queue, first.job_id, JobStatus.DONE)


def test_queue_full_rejection_is_prompt():
    worker = _BlockingWorker()
    with JobQueue(worker, max_pending=1, workers=1) as queue:
        queue.submit(["1.log"], submitted_by="u")
        assert worker.started.wait(2.0)
        queue.submit(["2.log"], submitted_by="u")  # fills the single pending slot
        start = time.monotonic()
        with pytest.raises(QueueFull):
            queue.submit(["3.log"], submitted_by="u")
        assert (time.monotonic() - start) < 0.1  # non-blocking rejection
        worker.release.set()


# --- No pool poisoning ------------------------------------------------------


def test_failing_job_does_not_poison_pool():
    worker = _RaisingWorker("boom")
    with JobQueue(worker, workers=1) as queue:
        bad = queue.submit(["bad.log"], submitted_by="u")
        failed = _wait_for(queue, bad.job_id, JobStatus.FAILED)
        assert failed.error == "boom"
        # The same single worker thread keeps serving jobs.
        good = queue.submit(["good.log"], submitted_by="u")
        _wait_for(queue, good.job_id, JobStatus.DONE)


def test_failed_job_error_is_redacted():
    secret_line = "connection refused for token=ghp_" + "A" * 20
    worker = _RaisingWorker(secret_line)
    with JobQueue(worker, workers=1) as queue:
        job = queue.submit(["x.log"], submitted_by="u")
        failed = _wait_for(queue, job.job_id, JobStatus.FAILED)
    assert "ghp_" not in failed.error
    assert "[REDACTED]" in failed.error


# --- Cancellation -----------------------------------------------------------


def test_cancel_queued_job_never_runs():
    worker = _BlockingWorker()
    with JobQueue(worker, max_pending=8, workers=1) as queue:
        blocker = queue.submit(["block.log"], submitted_by="u")
        assert worker.started.wait(2.0)  # single worker is pinned on the blocker
        queued = queue.submit(["queued.log"], submitted_by="u")
        assert queue.cancel(queued.job_id) is True
        cancelled = queue.get(queued.job_id)
        assert cancelled.status is JobStatus.CANCELLED
        worker.release.set()
        _wait_for(queue, blocker.job_id, JobStatus.DONE)
        # Still CANCELLED after the worker drains — it was never executed.
        assert queue.get(queued.job_id).status is JobStatus.CANCELLED


def test_cancel_running_job_is_cooperative():
    worker = _PollingWorker()
    with JobQueue(worker, workers=1) as queue:
        job = queue.submit(["run.log"], submitted_by="u")
        assert worker.started.wait(2.0)
        assert queue.cancel(job.job_id) is True
        _wait_for(queue, job.job_id, JobStatus.CANCELLED)


def test_cancel_unknown_or_finished_returns_false():
    worker = _CannedWorker()
    with JobQueue(worker, workers=1) as queue:
        assert queue.cancel("nope") is False
        job = queue.submit(["a.log"], submitted_by="u")
        _wait_for(queue, job.job_id, JobStatus.DONE)
        assert queue.cancel(job.job_id) is False  # already terminal


# --- Shutdown ---------------------------------------------------------------


def test_shutdown_joins_all_workers_and_returns_true():
    baseline = threading.active_count()
    worker = _CannedWorker()
    queue = JobQueue(worker, workers=4)
    assert threading.active_count() == baseline + 4
    assert queue.shutdown(timeout=10) is True
    assert threading.active_count() == baseline


def test_shutdown_drains_pending_jobs():
    worker = _CannedWorker()
    queue = JobQueue(worker, workers=2)
    jobs = [queue.submit([f"{i}.log"], submitted_by="u") for i in range(10)]
    assert queue.shutdown(timeout=10) is True
    # Every accepted job ran before the workers exited.
    assert all(queue.get(j.job_id).status is JobStatus.DONE for j in jobs)
    assert worker.runs == 10


def test_shutdown_respects_timeout_when_worker_wedged():
    # A full queue + a worker that never returns must not make shutdown block past its
    # timeout (regression: sentinel puts on a full bounded queue used to hang forever).
    worker = _BlockingWorker()
    queue = JobQueue(worker, max_pending=1, workers=1)
    queue.submit(["a.log"], submitted_by="u")  # worker grabs it and blocks
    assert worker.started.wait(2.0)
    queue.submit(["b.log"], submitted_by="u")  # fills the single pending slot (now full)

    start = time.monotonic()
    result = queue.shutdown(timeout=1.0)
    elapsed = time.monotonic() - start

    assert result is False  # the wedged worker never exited
    assert elapsed < 3.0  # but shutdown returned promptly instead of hanging
    worker.release.set()  # let the thread finish so it does not leak


def test_shutdown_is_idempotent():
    queue = JobQueue(_CannedWorker(), workers=1)
    assert queue.shutdown(timeout=5) is True
    assert queue.shutdown(timeout=5) is True


def test_submit_after_shutdown_raises():
    queue = JobQueue(_CannedWorker(), workers=1)
    queue.shutdown(timeout=5)
    with pytest.raises(RuntimeError):
        queue.submit(["a.log"], submitted_by="u")


# --- Construction guards ----------------------------------------------------


@pytest.mark.parametrize("kwargs", [{"workers": 0}, {"max_pending": 0}])
def test_invalid_construction_rejected(kwargs):
    with pytest.raises(ValueError):
        JobQueue(_CannedWorker(), **kwargs)


# --- Completion hook (alert dispatch seam) ----------------------------------


def test_on_done_called_with_completed_job():
    seen = []
    queue = JobQueue(_CannedWorker(), workers=1, on_done=seen.append)
    try:
        job = queue.submit(["a.log"], submitted_by="u")
        _wait_for(queue, job.job_id, JobStatus.DONE)
        deadline = time.monotonic() + 2.0
        while not seen and time.monotonic() < deadline:
            time.sleep(0.005)
    finally:
        queue.shutdown(timeout=5)
    assert [j.job_id for j in seen] == [job.job_id]
    assert seen[0].status is JobStatus.DONE


def test_on_done_not_called_for_failed_job():
    seen = []
    queue = JobQueue(_RaisingWorker("boom"), workers=1, on_done=seen.append)
    try:
        job = queue.submit(["a.log"], submitted_by="u")
        _wait_for(queue, job.job_id, JobStatus.FAILED)
    finally:
        queue.shutdown(timeout=5)
    assert seen == []


def test_raising_on_done_never_poisons_the_pool():
    def explode(job):
        raise RuntimeError("callback bug")

    queue = JobQueue(_CannedWorker(), workers=1, on_done=explode)
    try:
        first = queue.submit(["a.log"], submitted_by="u")
        _wait_for(queue, first.job_id, JobStatus.DONE)
        second = queue.submit(["b.log"], submitted_by="u")
        done = _wait_for(queue, second.job_id, JobStatus.DONE)
    finally:
        queue.shutdown(timeout=5)
    assert done.status is JobStatus.DONE
