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
