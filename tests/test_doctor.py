"""enq doctor / GET /doctor: index health after the cutover.

The report has to say whether the search index matches the chunks table,
which embedding version built it, and whether that matches the running
model. `healthy` is the single bit a person or script reads first.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from enqueue import config, db, notes
from enqueue.api import app
from enqueue.index import bootstrap
from enqueue.index.store import get_store
from enqueue.ingest import chunk as chunk_mod


@pytest.fixture
def doctor_store(store, monkeypatch):
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    yield store
    get_store.cache_clear()


def _seed_and_build() -> str:
    note = notes.create("Hydroponics feeds the city from a rooftop.")
    aid = note["artifact"]["id"]
    conn = db.get_conn()
    try:
        chunk_mod.chunk_artifact(conn, aid)
        conn.commit()
    finally:
        conn.close()
    assert bootstrap.ensure_index() is True
    return aid


def _doctor(client: TestClient) -> dict:
    resp = client.get("/doctor")
    assert resp.status_code == 200
    return resp.json()


def test_doctor_reports_a_synced_current_index(doctor_store, quiet_queue):
    _seed_and_build()
    with TestClient(app) as client:
        report = _doctor(client)
    assert report["chunk_count"] >= 1
    assert report["index_counts"]["chunks"] == report["chunk_count"]
    assert report["embed_version"] == config.EMBED_VERSION
    assert report["embed_version_current"] is True
    assert report["index_state"] == "ready"
    assert report["index_in_sync"] is True
    assert report["healthy"] is True


def test_doctor_detects_index_drift(doctor_store, quiet_queue):
    """A chunk row with no matching index point is out of sync, not healthy."""
    _seed_and_build()
    # A second note, chunked but not indexed: the table gains a row the index
    # never saw. This is the shape of "the index is behind the database".
    note2 = notes.create("The commons is what we share, and sharing keeps it common.")
    aid2 = note2["artifact"]["id"]
    conn = db.get_conn()
    try:
        chunk_mod.chunk_artifact(conn, aid2)
        conn.commit()
    finally:
        conn.close()

    with TestClient(app) as client:
        report = _doctor(client)
    assert report["chunk_count"] > report["index_counts"]["chunks"]
    assert report["index_in_sync"] is False
    assert report["healthy"] is False


def test_doctor_detects_a_stale_embedding_version(doctor_store, quiet_queue):
    """A recorded version that no longer matches the running model is flagged."""
    _seed_and_build()
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO index_meta (key, value) VALUES ('embed_version', 'old-model')"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
        conn.commit()
    finally:
        conn.close()

    with TestClient(app) as client:
        report = _doctor(client)
    assert report["embed_version"] == "old-model"
    assert report["embed_version_current"] is False
    # The index is still in sync row-for-row; it is just out of date.
    assert report["index_in_sync"] is True
    assert report["healthy"] is False
