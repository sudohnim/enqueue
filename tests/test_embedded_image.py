"""An image pasted inside a note is an embedded artifact: it carries the bytes and
syncs like any capture, but `embedded_at` keeps it off the wall, out of search, and
out of ingest. The note references it as `![](/artifacts/{id}/blob)`.
"""

from __future__ import annotations

from enqueue import capture, db

PNG = b"\x89PNG\r\n\x1a\n" + b"embedded-image-bytes" + b"\x00" * 32


def _artifact(aid):
    conn = db.get_conn()
    try:
        return conn.execute(
            "SELECT embedded_at, kind, content_hash FROM artifacts WHERE id = ?", (aid,)
        ).fetchone()
    finally:
        conn.close()


def test_embedded_upload_sets_the_flag_and_stores_the_blob(store, quiet_queue):
    out = capture.upload(PNG, "pasted.png", mime="image/png", embedded=True)
    row = _artifact(out["id"])
    assert row["embedded_at"] is not None
    assert row["kind"] == "image"
    # The bytes are on disk under the content hash, so the blob route can serve them.
    assert capture.blob_path(out["id"]) is not None


def test_embedded_image_is_absent_from_the_wall(store, quiet_queue):
    from fastapi.testclient import TestClient
    from enqueue.api import app
    from enqueue import notes

    client = TestClient(app)
    kept = notes.create(body="# A note")["artifact"]["id"]
    embedded = capture.upload(PNG, "pasted.png", mime="image/png", embedded=True)["id"]

    ids = [i["id"] for i in client.get("/artifacts").json()["items"]]
    assert kept in ids
    assert embedded not in ids


def test_a_plain_upload_still_shows_and_has_no_flag(store, quiet_queue):
    from fastapi.testclient import TestClient
    from enqueue.api import app

    client = TestClient(app)
    plain = capture.upload(PNG, "photo.png", mime="image/png")["id"]
    assert _artifact(plain)["embedded_at"] is None
    ids = [i["id"] for i in client.get("/artifacts").json()["items"]]
    assert plain in ids
