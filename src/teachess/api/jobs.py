"""Background jobs (import, analysis) with progress the web polls."""

import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

log = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "done", "error"]
MAX_KEPT_JOBS = 100


class JobError(Exception):
    """Expected failure: the message is shown to the user as is."""


@dataclass
class Job:
    id: str
    kind: str
    status: JobStatus = "queued"
    current: int = 0
    total: int = 0
    message: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


class Progress:
    """Handed to job functions to report how far they are."""

    def __init__(self, job: Job, lock: threading.Lock):
        self._job = job
        self._lock = lock

    def __call__(self, current: int, total: int, message: str = "") -> None:
        with self._lock:
            self._job.current = current
            self._job.total = total
            self._job.message = message


JobFunction = Callable[[Progress], dict[str, Any]]


class JobManager:
    def __init__(self, executor: Executor | None = None):
        self._executor = executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix="job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, fn: JobFunction) -> dict[str, Any]:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            self._forget_old_jobs()
        self._executor.submit(self._run, job, fn)
        return self.get(job.id) or job.snapshot()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.snapshot() if job else None

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, job: Job, fn: JobFunction) -> None:
        with self._lock:
            job.status = "running"
        try:
            result = fn(Progress(job, self._lock))
        except JobError as exc:
            self._finish(job, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - a job must never die silently
            log.exception("Job %s failed", job.id)
            self._finish(job, error=f"Error inesperado: {exc}")
        else:
            self._finish(job, result=result)

    def _finish(
        self, job: Job, *, result: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        with self._lock:
            job.status = "error" if error is not None else "done"
            job.result = result
            job.error = error

    def _forget_old_jobs(self) -> None:
        """Keep memory bounded: drop the oldest finished jobs. Call with the lock held."""
        finished = [j for j in self._jobs.values() if j.status in ("done", "error")]
        excess = len(self._jobs) - MAX_KEPT_JOBS
        for job in sorted(finished, key=lambda j: j.created_at)[: max(0, excess)]:
            del self._jobs[job.id]
