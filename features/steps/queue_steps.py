"""Step implementations for queue.feature.

Positive scenarios run the real analysis engine over the committed sample logs (the
same fixtures the unit and CLI checks use). The cancel/backpressure scenarios need a
saturated pool, so they use a gated worker that blocks until released — the only way
to observe backpressure deterministically without racing the clock.
"""

from __future__ import annotations

import threading
import time

from behave import given, then, when

from security_log_analysis_tool.config import load_rules
from security_log_analysis_tool.models import JobStatus
from security_log_analysis_tool.pipeline.engine import AnalysisEngine, AnalysisResult
from security_log_analysis_tool.pipeline.queue import EngineWorker, JobQueue, QueueFull

_MAX_PENDING = 4
_WORKERS = 2


class _GatedWorker:
    def __init__(self) -> None:
        self._release = threading.Event()
        self._started = threading.Semaphore(0)

    def release(self) -> None:
        self._release.set()

    def wait_until_started(self, count: int, timeout: float = 5.0) -> bool:
        return all(self._started.acquire(timeout=timeout) for _ in range(count))

    def run(self, job, cancel):  # noqa: ARG002 - protocol signature
        self._started.release()
        self._release.wait(10.0)
        return AnalysisResult(events=(), failures=(), findings=())


def _sample_files(context) -> list[str]:
    return [str(context.sample_logs / "access.log"), str(context.sample_logs / "auth.log")]


def _wait_all(queue: JobQueue, job_ids, statuses, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all((queue.get(jid) and queue.get(jid).status in statuses) for jid in job_ids):
            return True
        time.sleep(0.02)
    return False


@given("a running job queue with {workers:d} workers")
def step_running_queue(context, workers: int) -> None:
    engine = AnalysisEngine(load_rules(context.rules_path))
    context.queue = JobQueue(EngineWorker(engine), max_pending=64, workers=workers)
    context.job_ids = []
    context.bad_job_id = None


def _pin_all_workers(context) -> None:
    context.gated = _GatedWorker()
    context.queue = JobQueue(context.gated, max_pending=_MAX_PENDING, workers=_WORKERS)
    context.job_ids = []
    # Every worker grabs a job and blocks, so no worker can drain the pending queue.
    for i in range(_WORKERS):
        context.queue.submit([f"worker-{i}.log"], submitted_by="behave")
    assert context.gated.wait_until_started(_WORKERS), "workers did not all start"


@given("a job queue with all workers busy")
def step_workers_busy(context) -> None:
    _pin_all_workers(context)  # pending queue left empty: there is room to queue a job


@given("a saturated job queue")
def step_saturated_queue(context) -> None:
    _pin_all_workers(context)
    # Fill every pending slot too: the queue is now genuinely full.
    for i in range(_MAX_PENDING):
        context.queue.submit([f"pending-{i}.log"], submitted_by="behave")


@when("I submit {n:d} concurrent analysis jobs")
def step_submit_n(context, n: int) -> None:
    for _ in range(n):
        context.job_ids.append(context.queue.submit(_sample_files(context), "behave").job_id)


@when("I submit a job for a file that does not exist")
def step_submit_missing(context) -> None:
    context.bad_job_id = context.queue.submit(["/no/such/file.log"], "behave").job_id


@when("I submit one more job and cancel it")
def step_submit_and_cancel(context) -> None:
    job = context.queue.submit(["extra.log"], "behave")
    context.cancelled_id = job.job_id
    assert context.queue.cancel(job.job_id) is True


@then("all jobs finish successfully")
def step_all_finish(context) -> None:
    assert _wait_all(context.queue, context.job_ids, {JobStatus.DONE}, 60.0)


@then("all good jobs finish successfully")
def step_good_jobs_finish(context) -> None:
    assert _wait_all(context.queue, context.job_ids, {JobStatus.DONE}, 60.0)


@then("the bad job is marked failed")
def step_bad_failed(context) -> None:
    assert _wait_all(context.queue, [context.bad_job_id], {JobStatus.FAILED}, 30.0)


@then("that job is cancelled without running")
def step_job_cancelled(context) -> None:
    job = context.queue.get(context.cancelled_id)
    assert job.status is JobStatus.CANCELLED
    context.gated.release()


@then("further submissions are rejected as queue-full")
def step_rejected(context) -> None:
    start = time.monotonic()
    try:
        context.queue.submit(["overflow.log"], "behave")
    except QueueFull:
        assert (time.monotonic() - start) < 0.1
    else:
        raise AssertionError("expected QueueFull on a saturated queue")
    context.gated.release()


@then("the queue shuts down without hanging")
def step_shutdown(context) -> None:
    assert context.queue.shutdown(timeout=15) is True
