"""The main colours of a picture, worked out on this Mac."""

from __future__ import annotations

from . import blobstore, db

_TYPES = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif", "image/webp": "webp"}


def palette(data: bytes, mime: str, top: int = 5) -> list[tuple[int, int, int, float]]:
    """Up to `top` colours as (r, g, b, share of the picture), largest share first."""
    import fitz
    import numpy as np

    ext = _TYPES.get(mime)
    if ext is None:
        return []
    doc = fitz.open(stream=data, filetype=ext)
    try:
        page = doc[0]
        scale = 64 / max(page.rect.width, page.rect.height, 1)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        px = np.frombuffer(pix.samples, dtype=np.uint8).reshape(-1, pix.n)[:, :3]
    finally:
        doc.close()
    bins = (px >> 5).astype(np.int32)
    keys = bins[:, 0] * 64 + bins[:, 1] * 8 + bins[:, 2]
    counts = np.bincount(keys, minlength=512)
    out = []
    for key in np.argsort(counts)[::-1][:top]:
        if counts[key] == 0:
            break
        mean = px[keys == key].mean(axis=0)
        share = round(float(counts[key]) / len(keys), 4)
        out.append((int(mean[0]), int(mean[1]), int(mean[2]), share))
    return out


def make(artifact_id: str) -> int:
    """Work out and keep one live image's colours. Returns how many were kept."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT kind, mime, content_hash, vaulted_at FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or row["kind"] != "image" or row["vaulted_at"]:
        return 0
    if not row["content_hash"] or not blobstore.exists(row["content_hash"]):
        return 0
    try:
        found = palette(blobstore.read(row["content_hash"]), row["mime"] or "")
    except Exception:  # noqa: BLE001 - a picture that cannot be read has no colours
        return 0
    with db.transaction() as conn:
        conn.execute("DELETE FROM artifact_colours WHERE artifact_id = ?", (artifact_id,))
        conn.executemany(
            "INSERT OR REPLACE INTO artifact_colours (artifact_id, r, g, b, share)"
            " VALUES (?, ?, ?, ?, ?)",
            [(artifact_id, r, g, b, share) for r, g, b, share in found],
        )
    return len(found)


def drop(artifact_id: str) -> None:
    with db.transaction() as conn:
        conn.execute("DELETE FROM artifact_colours WHERE artifact_id = ?", (artifact_id,))
