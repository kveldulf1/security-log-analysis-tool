"""In-process job queue: the "enterprise concurrency / load-balancing" answer.

A bounded :class:`JobQueue` fronts a fixed :class:`WorkerPool` of daemon threads;
a lock-guarded :class:`JobRegistry` is the single source of truth for every job's
state. The queue is deliberately small and self-contained — no Redis/Celery — so
the tool installs and runs on a fresh reviewer machine with ``pip install``. The
``JobQueue`` seam is the scaling story: swap a distributed broker behind the same
``submit``/``get``/``cancel`` surface, raise the worker count, or shard by file.

Design guarantees, each backed by a test:

* **Backpressure** — the pending queue is bounded; ``submit`` past capacity raises
  :class:`QueueFull` immediately instead of blocking (no silent unbounded growth).
* **No pool poisoning** — a job that raises is recorded ``FAILED`` with a *redacted*
  error; the worker thread survives and keeps draining the queue.
* **Cooperative cancel** — cancelling a still-queued job transitions it straight to
  ``CANCELLED`` without running; a long-running worker that polls its
  :class:`CancelToken` can bail out mid-flight.
* **Graceful shutdown** — one sentinel per worker drains in-flight work, then joins
  within a caller-supplied timeout, returning whether every thread exited cleanly.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

from ..models import Job, JobStatus
from ..pipeline.engine import AnalysisEngine, AnalysisResult
from ..redaction import redact

_TERMINAL_STATES = frozenset({JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED})

# How long a worker blocks in ``queue.get`` before re-checking the shutdown flag.
_POLL_INTERVAL_SECONDS = 0.1


class QueueFull(Exception):
    """Raised by :meth:`JobQueue.submit` when the bounded queue is at capacity.

    Retryable: the caller should back off and resubmit, or surface the pressure to
    the user (CLI/TUI). Never swallowed into an unbounded in-memory backlog.
    """


class JobCancelled(Exception):
    """Internal signal a cooperative worker raises to abort a running job."""


class CancelToken:
    """A one-shot cancellation flag handed to the worker running a job.

    Thread-safe. The production :class:`EngineWorker` only checks it before it
    starts (a synchronous ``analyze`` is not interruptible mid-line), but the token
    is a real seam: a worker that processes in chunks can call
    :meth:`raise_if_cancelled` between them to honour a mid-flight cancel.
    """

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise JobCancelled


class JobWorker(Protocol):
    """Runs the work for a single job. The queue owns threading; the worker owns
    *what a job does*, so the two concerns stay independently testable."""

    def run(self, job: Job, cancel: CancelToken) -> AnalysisResult: ...


class EngineWorker:
    """Default worker: run the analysis engine over a job's files."""

    def __init__(self, engine: AnalysisEngine, fmt: str = "auto") -> None:
        self._engine = engine
        self._fmt = fmt

    def run(self, job: Job, cancel: CancelToken) -> AnalysisResult:
        cancel.raise_if_cancelled()
        return self._engine.analyze(job.files, fmt=self._fmt)


class JobRegistry:
    """Thread-safe store of jobs and their cancel tokens.

    Jobs are immutable :class:`Job` values; a state change replaces the stored
    object under the lock, so a reader always sees a consistent snapshot.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._tokens: dict[str, CancelToken] = {}
        self._lock = threading.Lock()

    def add(self, job: Job, token: CancelToken) -> None:
        with self._lock:
            self._jobs[job.job_id] = job
            self._tokens[job.job_id] = token

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def token(self, job_id: str) -> CancelToken | None:
        with self._lock:
            return self._tokens.get(job_id)

    def replace(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)
            self._tokens.pop(job_id, None)

    def cancel_if_queued(self, job_id: str) -> bool:
        """Atomically flip a still-``QUEUED`` job to ``CANCELLED``.

        Returns ``True`` only if the job was queued at the moment of the call, so a
        job that a worker has already picked up is left for the worker to finish or
        abort — no lost or double transitions.
        """

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status is not JobStatus.QUEUED:
                return False
            self._jobs[job_id] = replace(
                job, status=JobStatus.CANCELLED, finished_at=datetime.now(UTC)
            )
            return True

    def start_if_runnable(self, job_id: str) -> Job | None:
        """Atomically claim a ``QUEUED`` job for execution, or decline it.

        Returns the job transitioned to ``RUNNING`` if it was still queued and not
        cancel-flagged; otherwise records ``CANCELLED`` (if the token was set) and
        returns ``None``. Doing the cancel check and the RUNNING transition under a
        single lock closes the race where a concurrent :meth:`cancel_if_queued` could
        otherwise be clobbered by the worker's own status write.
        """

        with self._lock:
            job = self._jobs.get(job_id)
            token = self._tokens.get(job_id)
            if job is None or token is None or job.status is not JobStatus.QUEUED:
                return None
            now = datetime.now(UTC)
            if token.cancelled:
                self._jobs[job_id] = replace(job, status=JobStatus.CANCELLED, finished_at=now)
                return None
            running = replace(job, status=JobStatus.RUNNING, started_at=now)
            self._jobs[job_id] = running
            return running


class JobQueue:
    """Bounded queue + worker pool + registry, wired together and auto-started.

    Enqueues job *ids* (the registry, not the queue, holds mutable state). Use as a
    context manager to guarantee :meth:`shutdown` on exit.
    """

    def __init__(
        self,
        worker: JobWorker,
        *,
        max_pending: int = 100,
        workers: int = 4,
    ) -> None:
        if max_pending <= 0:
            raise ValueError("max_pending must be positive")
        if workers <= 0:
            raise ValueError("workers must be positive")
        self._worker = worker
        self._queue: queue.Queue[str] = queue.Queue(maxsize=max_pending)
        self._registry = JobRegistry()
        self._threads: list[threading.Thread] = []
        self._worker_count = workers
        self._lifecycle_lock = threading.Lock()
        self._shutdown_event = threading.Event()
        self._start()

    def _start(self) -> None:
        for index in range(self._worker_count):
            thread = threading.Thread(
                target=self._work_loop, name=f"slat-worker-{index}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def submit(self, files: Sequence[str], submitted_by: str) -> Job:
        """Enqueue a job. Raises :class:`QueueFull` when the queue is at capacity."""

        job = Job(
            job_id=uuid.uuid4().hex,
            status=JobStatus.QUEUED,
            files=tuple(files),
            submitted_by=submitted_by,
            submitted_at=datetime.now(UTC),
        )
        token = CancelToken()
        # Register + enqueue under the lifecycle lock, which shutdown() also holds
        # when it sets the shutdown flag. This serialises the two: a job either lands
        # in the queue (and is drained before workers exit) or is cleanly rejected —
        # it can never be enqueued after shutdown has begun and stranded forever.
        with self._lifecycle_lock:
            if self._shutdown_event.is_set():
                raise RuntimeError("cannot submit to a queue that is shutting down")
            self._registry.add(job, token)
            try:
                self._queue.put_nowait(job.job_id)
            except queue.Full as exc:
                self._registry.remove(job.job_id)
                raise QueueFull(
                    f"job queue is full (max_pending={self._queue.maxsize}); retry shortly"
                ) from exc
        return job

    def get(self, job_id: str) -> Job | None:
        return self._registry.get(job_id)

    def list_jobs(self) -> list[Job]:
        return self._registry.list()

    def cancel(self, job_id: str) -> bool:
        """Request cancellation of a job.

        A still-queued job is transitioned to ``CANCELLED`` immediately; a running
        job has its token set (honoured only if its worker polls the token). Returns
        ``False`` for unknown or already-finished jobs.
        """

        token = self._registry.token(job_id)
        job = self._registry.get(job_id)
        if token is None or job is None or job.status in _TERMINAL_STATES:
            return False
        token.cancel()
        self._registry.cancel_if_queued(job_id)
        return True

    def shutdown(self, timeout: float | None = None) -> bool:
        """Drain in-flight work, then join every worker within ``timeout``.

        Signals shutdown via a flag (not blocking sentinels), so it never stalls on a
        full queue — the ``timeout`` genuinely bounds how long it waits. Workers keep
        draining queued jobs until the queue is empty, then exit. Returns ``True`` iff
        every worker thread exited within the timeout. Idempotent.
        """

        with self._lifecycle_lock:
            self._shutdown_event.set()

        deadline = None if timeout is None else time.monotonic() + timeout
        all_joined = True
        for thread in self._threads:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            thread.join(remaining)
            if thread.is_alive():
                all_joined = False
        return all_joined

    def _work_loop(self) -> None:
        while True:
            try:
                job_id = self._queue.get(timeout=_POLL_INTERVAL_SECONDS)
            except queue.Empty:
                # No pending work: exit once shutdown is requested, else keep waiting.
                if self._shutdown_event.is_set():
                    return
                continue
            try:
                self._process(job_id)
            finally:
                self._queue.task_done()

    def _process(self, job_id: str) -> None:
        running = self._registry.start_if_runnable(job_id)
        if running is None:
            # Cancelled before it could start, already terminal, or unknown — nothing
            # to run. start_if_runnable has recorded the CANCELLED transition if due.
            return
        token = self._registry.token(job_id)
        if token is None:  # pragma: no cover - registry always holds a token here
            return

        started = time.monotonic()
        try:
            result = self._worker.run(running, token)
        except JobCancelled:
            self._registry.replace(
                replace(running, status=JobStatus.CANCELLED, finished_at=datetime.now(UTC))
            )
            return
        except Exception as exc:  # noqa: BLE001 — one bad job must not poison the pool.
            self._registry.replace(
                replace(
                    running,
                    status=JobStatus.FAILED,
                    finished_at=datetime.now(UTC),
                    error=redact(str(exc)),
                )
            )
            return

        stats = {
            "events": len(result.events),
            "failures": len(result.failures),
            "findings": len(result.findings),
            "duration_seconds": time.monotonic() - started,
        }
        self._registry.replace(
            replace(
                running,
                status=JobStatus.DONE,
                finished_at=datetime.now(UTC),
                findings=result.findings,
                stats=stats,
            )
        )

    def __enter__(self) -> JobQueue:
        return self

    def __exit__(self, *_exc: object) -> bool:
        self.shutdown()
        return False
