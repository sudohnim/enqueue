"""Small pictures of image artifacts, kept sealed like every original (blobstore)."""

from __future__ import annotations

import logging

from . import blobstore, db

log = logging.getLogger(__name__)
WIDTH = 520
_TYPES = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif", "image/webp": "webp"}


def render(data: bytes, mime: str, width: int = WIDTH) -> bytes | None:
    """A JPEG at most `width` pixels wide, or None for a type that cannot be drawn."""
    import fitz

    ext = _TYPES.get(mime)
    if ext is None:
        return None
    doc = fitz.open(stream=data, filetype=ext)
    try:
        page = doc[0]
        scale = min(1.0, width / max(page.rect.width, 1))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pix.tobytes("jpeg")
    finally:
        doc.close()


def make(artifact_id: str) -> bool:
    """Make and keep the small picture of one live image. True when one is kept."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT kind, mime, content_hash, vaulted_at, deleted_at FROM artifacts"
            " WHERE id = ?",
            (artifact_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or row["kind"] != "image" or row["vaulted_at"] or row["deleted_at"]:
        return False
    if not row["content_hash"] or not blobstore.exists(row["content_hash"]):
        return False
    try:
        small = render(blobstore.read(row["content_hash"]), row["mime"] or "")
    except Exception:  # noqa: BLE001 - a picture that cannot be drawn has no thumb
        log.info("no small picture for %s", artifact_id)
        return False
    if small is None:
        return False
    digest = blobstore.write(small)
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO thumbs (artifact_id, content_hash, width)" " VALUES (?, ?, ?)",
            (artifact_id, digest, WIDTH),
        )
    return True


def get(artifact_id: str) -> bytes | None:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT t.content_hash FROM thumbs t JOIN artifacts a ON a.id = t.artifact_id"
            " WHERE t.artifact_id = ? AND a.vaulted_at IS NULL AND a.deleted_at IS NULL",
            (artifact_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or not blobstore.exists(row["content_hash"]):
        return None
    return blobstore.read(row["content_hash"])


def drop(artifact_id: str) -> None:
    """Remove the small picture (the item went into the vault)."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT content_hash FROM thumbs WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        conn.execute("DELETE FROM thumbs WHERE artifact_id = ?", (artifact_id,))
    if row is not None:
        blobstore.remove(row["content_hash"])
