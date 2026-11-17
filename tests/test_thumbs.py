"""Small pictures of image artifacts: made once, kept sealed, dropped with the vault."""

from __future__ import annotations

import hashlib
import uuid

import fitz

from enqueue import blobstore, db, thumbs


def _png(width=1200, height=600) -> bytes:
    doc = fitz.open(width=width, height=height)
    doc.new_page(width=width, height=height)
    return doc[0].get_pixmap().tobytes("png")


def _seed(store, kind="image", mime="image/png", with_blob=True):
    artifact_id = str(uuid.uuid4())
    if with_blob:
        digest = blobstore.write(_png())
    else:
        digest = hashlib.sha256(artifact_id.encode()).hexdigest()
    now = "2024-01-01T00:00:00+00:00"
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, content_hash, mime, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (artifact_id, kind, "A capture", digest, mime, "ok", now, now),
        )
    return artifact_id


def test_render_makes_a_520_pixel_jpeg():
    jpeg = thumbs.render(_png(), "image/png")
    assert jpeg is not None
    assert fitz.Pixmap(jpeg).width == 520


def test_render_refuses_a_type_it_cannot_draw():
    assert thumbs.render(_png(), "application/pdf") is None


def test_make_and_get_an_image(store):
    artifact_id = _seed(store)
    assert thumbs.make(artifact_id) is True
    data = thumbs.get(artifact_id)
    assert data is not None
    assert fitz.Pixmap(data).width == 520


def test_make_for_a_note_returns_false(store):
    assert thumbs.make(_seed(store, kind="note", mime=None)) is False


def test_get_is_none_without_a_blob(store):
    artifact_id = _seed(store, with_blob=False)
    assert thumbs.make(artifact_id) is False
    assert thumbs.get(artifact_id) is None


def test_drop_removes_the_thumb(store):
    artifact_id = _seed(store)
    assert thumbs.make(artifact_id) is True
    thumbs.drop(artifact_id)
    assert thumbs.get(artifact_id) is None
