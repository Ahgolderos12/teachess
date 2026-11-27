"""SyncService scheduling, with a job manager that runs jobs inline."""

import threading
from typing import Any

import pytest

from teachess.api import sync as sync_module
from teachess.api.jobs import JobManager, Progress
from teachess.api.sync import SyncBusyError, SyncService
from tests.test_api import InlineExecutor


def test_periodic_sync_runs_at_startup_and_then_every_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sync_module, "STARTUP_DELAY_SECONDS", 0.01)
    runs = threading.Semaphore(0)

    def run(progress: Progress) -> dict[str, Any]:
        runs.release()
        return {"new": 0}

    service = SyncService(JobManager(InlineExecutor()), run, interval_seconds=0.02)  # type: ignore[arg-type]
    service.start()
    try:
        assert runs.acquire(timeout=2) and runs.acquire(timeout=2)  # startup + one interval
        status = service.status()
        assert status["job"]["status"] == "done" and status["next_run_at"] is not None
    finally:
        service.stop()


def test_manual_sync_is_refused_while_one_is_running() -> None:
    release = threading.Event()

    def slow(progress: Progress) -> dict[str, Any]:
        release.wait(2)
        return {}

    service = SyncService(JobManager(), slow, interval_seconds=0)
    service.trigger()
    with pytest.raises(SyncBusyError):
        service.trigger()
    release.set()


def test_disabled_sync_never_starts_a_thread() -> None:
    service = SyncService(JobManager(), None, interval_seconds=3600)
    service.start()
    assert service.status()["configured"] is False
    with pytest.raises(RuntimeError):
        service.trigger()
