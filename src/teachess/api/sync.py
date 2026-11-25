"""Automatic sync: import the player's new games and analyse them, periodically.

Runs as an ordinary background job (so the web can follow its progress) at startup and then
every `interval` seconds while `teachess serve` is running. Only one sync runs at a time.
"""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from teachess.api.jobs import JobFunction, JobManager

log = logging.getLogger(__name__)

STARTUP_DELAY_SECONDS = 5.0  # let the server finish starting before the first sync


class SyncBusyError(RuntimeError):
    pass


class SyncService:
    def __init__(
        self,
        jobs: JobManager,
        run: JobFunction | None,  # None: no platform user configured
        interval_seconds: float,  # 0: no automatic sync (manual only)
        clock: Callable[[], float] = time.time,
    ):
        self._jobs = jobs
        self._run = run
        self._interval = interval_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._job_id: str | None = None
        self._next_run: float | None = None

    @property
    def configured(self) -> bool:
        return self._run is not None

    def start(self) -> None:
        """Start the periodic sync thread (no-op if disabled or not configured)."""
        if not self.configured or self._interval <= 0 or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def trigger(self) -> dict[str, Any]:
        """Start a sync now. Raises SyncBusyError if one is already running."""
        if self._run is None:
            raise RuntimeError("Sincronización no configurada.")
        with self._lock:
            current = self._jobs.get(self._job_id) if self._job_id else None
            if current and current["status"] in ("queued", "running"):
                raise SyncBusyError("Ya hay una sincronización en marcha.")
            job = self._jobs.submit("sync", self._run)
            self._job_id = job["id"]
        return job

    def status(self) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(self._job_id) if self._job_id else None
            next_run = self._next_run
        return {
            "configured": self.configured,
            "interval_hours": round(self._interval / 3600, 2) if self._interval > 0 else None,
            "next_run_at": next_run,
            "job": job,
        }

    def _loop(self) -> None:
        delay = STARTUP_DELAY_SECONDS
        while True:
            with self._lock:
                self._next_run = self._clock() + delay
            if self._stop.wait(delay):
                return
            try:
                self.trigger()
            except SyncBusyError:
                pass  # a manual sync is already running: that counts
            except Exception:  # noqa: BLE001 - the scheduler must survive anything
                log.exception("Automatic sync could not start")
            delay = self._interval
