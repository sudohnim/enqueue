"""A real database per test, in a temporary directory.

The engine's own migration path is what builds it, so the tests exercise the thing
that actually runs rather than a hand-rolled schema that could drift from it.
"""

from __future__ import annotations

import pytest

from enqueue import config, db


@pytest.fixture(autouse=True)
def _fast_argon2(monkeypatch):
    """Tests use the INTERACTIVE Argon2id preset so the key-derivation tests run
    in milliseconds instead of ~1s each. The production preset stays MODERATE
    (DEC-D5); correctness is identical, only the brute-force resistance differs,
    and tests do not need that."""
    import nacl.pwhash

    from enqueue import crypto

    monkeypatch.setattr(crypto, "OPSLIMIT", nacl.pwhash.argon2id.OPSLIMIT_INTERACTIVE)
    monkeypatch.setattr(crypto, "MEMLIMIT", nacl.pwhash.argon2id.MEMLIMIT_INTERACTIVE)


@pytest.fixture(autouse=True)
def _test_host(monkeypatch):
    """TestClient sends Host: testserver; the engine only answers loopback names
    (api/guard.py). tests/test_guard.py checks the production set on its own."""
    monkeypatch.setattr(config, "ALLOWED_HOSTS", config.ALLOWED_HOSTS | {"testserver"})


@pytest.fixture(autouse=True)
def _no_query_lift(monkeypatch):
    """Query lifting calls the search model; no test reaches a network by accident.
    tests/test_query_lift.py exercises the real function directly."""
    from enqueue.retrieve import lift

    monkeypatch.setattr(lift, "lift", lambda query: [])


@pytest.fixture(autouse=True)
def _no_judge_worker(monkeypatch):
    """The related judge is a process-wide thread that calls the ingest model for
    whatever is pending in whichever database `config.DB_PATH` names at that moment.
    Started by one test's app, it would judge the next test's rows behind its back.
    tests/test_related.py drives `judge_next` directly."""
    from enqueue.ingest import related

    monkeypatch.setattr(related, "start_judge", lambda: None)


@pytest.fixture(autouse=True)
def _drain_ingest(monkeypatch):
    """Let this test's real ingest work finish inside this test.

    The ingest worker is one process-wide thread. A test that submits to it for real
    (no `quiet_queue`) used to leave items queued when it ended, and the worker then
    ran them against the NEXT test's database - `config.DB_PATH` points wherever the
    running test put it, and tests reuse ids like "a" and "b". That wrote rows into a
    stranger's database mid-assertion (test_related's purge check failed about one run
    in five). Requesting `monkeypatch` makes this teardown run before the paths are
    restored, so the drain happens against the test's own database.
    """
    yield
    from enqueue.ingest import queue as ingest_queue

    ingest_queue._ingest.wait_idle(10)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "enqueue.db")
    monkeypatch.setattr(config, "BLOB_DIR", tmp_path / "blobs")
    # QR.1: keyring_file stores the raw DEK via keyring.dek_store/_dek_get, which
    # on macOS writes to the real Keychain. Tests must never touch that: redirect
    # the DEK to a file inside the test's temp dir, exactly the non-macOS fallback.
    dek_file = tmp_path / "sync-dek.bin"

    from enqueue import keyring

    def _fake_store(dek: bytes) -> None:
        dek_file.write_bytes(dek)

    def _fake_get() -> bytes | None:
        try:
            return dek_file.read_bytes()
        except OSError:
            return None

    def _fake_clear() -> bool:
        dek_file.unlink(missing_ok=True)
        return True

    monkeypatch.setattr(keyring, "dek_store", _fake_store)
    monkeypatch.setattr(keyring, "_dek_get", _fake_get)
    monkeypatch.setattr(keyring, "dek_clear", _fake_clear)
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
    monkeypatch.setattr(ingest_queue, "submit_background", done.append)
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
