"""Passages that say something close: "More like this" (`similar_items`) and the
notes beside a passage being written (`near_text`). No model call, nothing stored.
"""

from __future__ import annotations

import json

from .. import db

PASSAGE_MIN = 0.78  # passage-to-passage cosine; ~a quarter of eval-corpus passages link


def similar_items(artifact_id: str, limit: int = 12) -> list[dict]:
    """Live items closest to an artifact, by the sum of its passages' nearest chunks."""
    from ..index.store import get_store

    store = get_store()
    conn = db.get_conn()
    try:
        chunks = conn.execute(
            "SELECT id FROM chunks WHERE artifact_id = ? ORDER BY ordinal LIMIT 12",
            (artifact_id,),
        ).fetchall()
        totals: dict[str, float] = {}
        best: dict[str, tuple[float, str]] = {}
        for c in chunks:
            per: dict[str, list[float]] = {}
            for hit in store.similar_chunks(c["id"], limit=12):
                other = hit["artifact_id"]
                if other == artifact_id:
                    continue
                per.setdefault(other, []).append(hit["score"])
                if other not in best or hit["score"] > best[other][0]:
                    best[other] = (hit["score"], hit["chunk_id"])
            for other, scores in per.items():
                totals[other] = totals.get(other, 0.0) + sum(sorted(scores, reverse=True)[:3])
        if not totals:
            return []
        rows = conn.execute(
            "SELECT id, title, kind FROM artifacts WHERE id IN (SELECT value FROM json_each(?))"
            " AND deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL",
            (json.dumps(sorted(totals)),),
        ).fetchall()
        live = {r["id"]: r for r in rows}
        texts: dict[str, str] = {}
        for other, (_, chunk_id) in best.items():
            if other in live:
                row = conn.execute("SELECT text FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
                if row is not None:
                    texts[other] = row["text"]
    finally:
        conn.close()

    out = [
        {
            "artifact_id": aid,
            "title": live[aid]["title"],
            "kind": live[aid]["kind"],
            "score": round(score, 3),
            "snippet": " ".join(texts.get(aid, "").split())[:200],
        }
        for aid, score in totals.items()
        if aid in live
    ]
    return sorted(out, key=lambda r: r["score"], reverse=True)[:limit]


def near_text(artifact_id: str, text: str, limit: int = 3) -> list[dict]:
    """Other live items with a passage close to `text`."""
    words = text.split()
    if len(words) < 12:
        return []
    from ..index.store import get_store

    store = get_store()
    best: dict[str, float] = {}
    for hit in store.search_dense(store.CHUNKS, text, limit=24, as_query=False):
        other = hit["artifact_id"]
        if other != artifact_id and hit["score"] >= PASSAGE_MIN:
            best[other] = max(best.get(other, 0.0), hit["score"])
    if not best:
        return []
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, kind FROM artifacts"
            " WHERE id IN (SELECT value FROM json_each(?))"
            " AND deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL",
            (json.dumps(sorted(best)),),
        ).fetchall()
    finally:
        conn.close()
    found = [dict(r) | {"score": round(best[r["id"]], 3)} for r in rows]
    return sorted(found, key=lambda r: r["score"], reverse=True)[:limit]
