"""The main colours of a picture, worked out on this Mac."""

from __future__ import annotations

import uuid

import fitz

from enqueue import blobstore, colours, db


def _png(bands: list[tuple[float, float, tuple[float, float, float]]]) -> bytes:
    doc = fitz.open(width=100, height=100)
    page = doc.new_page(width=100, height=100)
    for x0, x1, rgb in bands:
        page.draw_rect(fitz.Rect(x0, 0, x1, 100), color=None, fill=rgb)
    data = page.get_pixmap().tobytes("png")
    doc.close()
    return data


def _seed(store, data: bytes, kind: str = "image", mime: str = "image/png") -> str:
    artifact_id = str(uuid.uuid4())
    digest = blobstore.write(data)
    now = "2024-01-01T00:00:00+00:00"
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, content_hash, mime, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (artifact_id, kind, "A capture", digest, mime, "ok", now, now),
        )
    return artifact_id


def rows(artifact_id: str) -> list[tuple]:
    conn = db.get_conn()
    try:
        return [
            (r["r"], r["g"], r["b"], r["share"])
            for r in conn.execute(
                "SELECT r, g, b, share FROM artifact_colours WHERE artifact_id = ? ORDER BY share DESC",
                (artifact_id,),
            )
        ]
    finally:
        conn.close()


def test_an_all_red_picture_has_one_colour_with_all_the_share(store):
    red = _png([(0, 100, (1, 0, 0))])
    artifact_id = _seed(store, red)
    assert colours.make(artifact_id) == 1
    found = rows(artifact_id)
    assert len(found) == 1
    r, g, b, share = found[0]
    assert r > 240 and g < 15 and b < 15
    assert share == 1.0


def test_a_half_red_half_blue_picture_has_two_colours(store):
    both = _png([(0, 50, (1, 0, 0)), (50, 100, (0, 0, 1))])
    artifact_id = _seed(store, both)
    assert colours.make(artifact_id) == 2
    found = rows(artifact_id)
    assert len(found) == 2
    assert abs(found[0][3] - 0.5) < 0.05
    assert abs(found[1][3] - 0.5) < 0.05
    reds = [c for c in found if c[0] > 200 and c[1] < 15 and c[2] < 15]
    blues = [c for c in found if c[2] > 200 and c[0] < 15 and c[1] < 15]
    assert len(reds) == 1 and len(blues) == 1


def test_a_pdf_artifact_gives_no_colours(store):
    assert colours.palette(_png([(0, 100, (1, 0, 0))]), "application/pdf") == []
    artifact_id = _seed(store, _png([(0, 100, (1, 0, 0))]), kind="pdf", mime="application/pdf")
    assert colours.make(artifact_id) == 0
    assert rows(artifact_id) == []


def test_drop_removes_the_colours(store):
    artifact_id = _seed(store, _png([(0, 100, (1, 0, 0))]))
    colours.make(artifact_id)
    assert rows(artifact_id)
    colours.drop(artifact_id)
    assert rows(artifact_id) == []
