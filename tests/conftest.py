"""A real database per test, in a temporary directory.

The engine's own migration path is what builds it, so the tests exercise the thing
that actually runs rather than a hand-rolled schema that could drift from it.
"""

from __future__ import annotations

import pytest

from enqueue import config, db


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "enqueue.db")
    monkeypatch.setattr(config, "BLOB_DIR", tmp_path / "blobs")
    db.reset_migration_state()
    db.migrate()
    yield tmp_path
    db.reset_migration_state()


@pytest.fixture
def quiet_queue(monkeypatch):
    """Run ingest inline instead of on the worker thread.

    The queue is deliberately fire-and-forget, which makes a test that writes a note
    and immediately asserts on its chunks racy. Tests want the same work, done before
    the call returns.
    """
    from enqueue.ingest import queue as ingest_queue

    done = []
    monkeypatch.setattr(ingest_queue, "submit", done.append)
    return done


@pytest.fixture
def async_turns(monkeypatch):
    """Record answer-worker submissions and resolve them synchronously on demand.

    Phase H split: submitting returns immediately with a pending turn, and the
    worker completes it later. These tests exercise both halves - the immediate
    pending turn from `send`/`ask`, then the worker's compute core run
    synchronously when the test calls `resolve()` - without any thread timing.
    """
    from enqueue import chats_worker

    class Recorder:
        def __init__(self):
            self.jobs = []

        def submit(self, job):
            self.jobs.append(job)

        def resolve(self):
            for job in self.jobs:
                chats_worker.compute(job)

    recorder = Recorder()
    monkeypatch.setattr(chats_worker, "submit", recorder.submit)
    return recorder
