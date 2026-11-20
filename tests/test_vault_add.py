"""Files added straight to the vault: sealed as saved, and never read by a model."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from enqueue import blobstore, config, db, events, vault, vaultops
from enqueue.ingest import facets
from enqueue.sync import snapshot


@pytest.fixture(autouse=True)
def _vault(store, monkeypatch):
    monkeypatch.setattr(vaultops, "push_artifact", lambda *_a, **_k: None)
    import enqueue.ingest.queue as iq

    submitted: list[str] = []
    monkeypatch.setattr(iq, "submit", submitted.append)
    monkeypatch.setattr(iq, "submit_background", submitted.append)
    vault.lock()
    vault.setup("123456")
    yield submitted
    vault.lock()


@pytest.fixture
def model_calls(monkeypatch):
    calls: list[str] = []
    import enqueue.providers.base as base

    def refuse(*_a, **_k):
        calls.append("model")
        raise RuntimeError("no model may read this")

    monkeypatch.setattr(base, "get_provider", refuse)
    monkeypatch.setattr(base, "get_vision_provider", refuse)
    return calls


def _png() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 40, 40)).save(out, "PNG")
    return out.getvalue()


def _row(aid):
    conn = db.get_conn()
    try:
        return conn.execute("SELECT * FROM artifacts WHERE id = ?", (aid,)).fetchone()
    finally:
        conn.close()


def _ids():
    conn = db.get_conn()
    try:
        return [r["id"] for r in conn.execute("SELECT id FROM artifacts ORDER BY kind")]
    finally:
        conn.close()


def test_files_are_sealed_as_saved_and_nothing_reads_them(_vault):
    out = vaultops.add_files(
        [
            ("codes.md", b"# Backup codes\n\nzebra-copper-7731", "text/markdown"),
            ("scan.pdf", b"%PDF-1.4 recovery words: harbour violet", "application/pdf"),
        ]
    )
    assert out == {"added": 2, "skipped": []}
    assert _vault == []
    disk = config.DB_PATH.read_bytes()
    assert b"zebra-copper-7731" not in disk and b"Backup codes" not in disk
    conn = db.get_conn()
    try:
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
        assert all(facets.summary_off(conn, aid) for aid in _ids())
    finally:
        conn.close()
    assert events.recent(50) == [] or all(
        "codes" not in str(e) and "scan" not in str(e) for e in events.recent(50)
    )
    note, pdf = (vaultops.get(aid)["artifact"] for aid in _ids())
    assert note["kind"] == "note" and "zebra-copper-7731" in note["body"]
    assert note["title"] == "Backup codes"
    raw, mime, _ = vaultops.blob_bytes(pdf["id"])
    assert raw.startswith(b"%PDF") and mime == "application/pdf"
    assert b"harbour violet" not in blobstore.read(_row(pdf["id"])["content_hash"])


def test_taken_out_it_is_searchable_but_no_model_reads_it(_vault, model_calls):
    from enqueue.ingest import queue as iq

    vaultops.add_files(
        [
            ("pin.txt", b"The safe code is 4417 and the locker is 22.", "text/plain"),
            ("photo.png", _png(), "image/png"),
        ]
    )
    for aid in _ids():
        vaultops.unvault_artifact(aid)
        iq.process(aid)
    assert model_calls == []
    conn = db.get_conn()
    try:
        assert all(facets.summary_off(conn, aid) for aid in _ids())
        assert conn.execute("SELECT COUNT(*) FROM facets").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] > 0
    finally:
        conn.close()


def test_the_same_file_twice_is_skipped(_vault):
    vaultops.add_files([("a.pdf", b"%PDF same bytes", None)])
    out = vaultops.add_files([("b.pdf", b"%PDF same bytes", None), ("empty.md", b"", None)])
    assert out["added"] == 0
    assert [s["why"] for s in out["skipped"]] == ["already in the vault", "empty"]


def test_the_route_needs_an_open_vault():
    from enqueue.api.app import create_app

    client = TestClient(create_app())
    files = [("files", ("n.md", b"# Hidden\n\ntext", "text/markdown"))]
    assert client.post("/vault/add", files=files).json()["added"] == 1
    vault.lock()
    assert client.post("/vault/add", files=files).status_code == 409


def test_the_switch_rides_the_snapshot(_vault):
    vaultops.add_files([("n.md", b"# Hidden\n\ntext", None)])
    (aid,) = _ids()
    conn = db.get_conn()
    try:
        snap = snapshot.read_artifact_snapshot(conn, aid)
        assert snap["summary_off"] is True
        conn.execute("DELETE FROM facet_skips")
        conn.commit()
        snapshot._apply_summary_off(conn, aid, snap)
        assert facets.summary_off(conn, aid)
        snapshot._apply_summary_off(conn, aid, {**snap, "summary_off": False})
        assert not facets.summary_off(conn, aid)
        snapshot._apply_summary_off(
            conn, aid, {k: v for k, v in snap.items() if k != "summary_off"}
        )
        assert not facets.summary_off(conn, aid)
    finally:
        conn.close()


def test_an_image_switched_off_is_never_described(store, model_calls):
    from enqueue import capture
    from enqueue.ingest import queue as iq

    made = capture.upload(_png(), "red.png", "image/png")
    facets.set_summary(made["id"], False)
    iq.process(made["id"])
    assert model_calls == []
