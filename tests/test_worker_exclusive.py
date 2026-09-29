"""Exclusive jobs run on the worker thread between items, ahead of the queue."""

from __future__ import annotations

import threading

import pytest

from enqueue.worker import Worker


def test_a_job_on_an_idle_worker_runs_and_returns_its_result():
    w = Worker("t", lambda item: None)
    assert w.run_exclusive(lambda: 42, timeout=5) == 42
    assert w.wait_idle(5)


def test_a_job_runs_on_the_worker_thread_and_its_error_reaches_the_caller():
    w = Worker("t", lambda item: None)
    names = []

    def boom():
        names.append(threading.current_thread().name)
        raise RuntimeError("database is locked")

    with pytest.raises(RuntimeError, match="locked"):
        w.run_exclusive(boom, timeout=5)
    assert names == ["enqueue-t"]


def test_a_job_jumps_ahead_of_queued_items():
    order: list[str] = []
    started = threading.Event()
    release = threading.Event()

    def handle(item):
        if item == "first":
            started.set()
            release.wait(5)
        order.append(item)

    w = Worker("t", handle)
    w.submit("first")
    started.wait(5)
    for item in ("a", "b", "c"):
        w.submit(item)
    w.run_exclusive(lambda: order.append("job"), wait=False)
    release.set()
    assert w.wait_idle(5)

    assert order == ["first", "job", "a", "b", "c"]


def test_the_index_endpoint_rebuilds_on_the_ingest_worker(store, monkeypatch):
    from fastapi.testclient import TestClient

    from enqueue.api.app import create_app
    from enqueue.index import bootstrap

    seen = []
    monkeypatch.setattr(
        bootstrap, "rebuild_now", lambda: seen.append(threading.current_thread().name) or {}
    )

    assert TestClient(create_app()).post("/index").status_code == 200
    assert seen == ["enqueue-ingest"]
