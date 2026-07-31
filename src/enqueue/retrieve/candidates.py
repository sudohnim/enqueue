"""Candidate generation: search both layers, roll up to artifacts.

At POC scale this returns nearly the whole corpus, which is correct and expected.
Recall is trivially high when the candidate pool is the collection, so the number
that matters here is the ranking after rerank, not this stage. Do not add filtering
to make the count look better.
"""

from __future__ import annotations

from collections import defaultdict

from .. import db
from ..index.store import get_store


def candidates(queries: list[str], limit: int = 150, per_query: int = 40) -> list[dict]:
    """Artifact ids ordered by best hit across both collections.

    Facet hits are weighted by the facet's trust score, so an abstraction that keeps
    winning matches the director then ejects quietly stops pulling artifacts in.
    """
    best: dict[str, float] = defaultdict(float)
    why: dict[str, str] = {}
    matched_facet: dict[str, str] = {}

    store = get_store()
    for query in queries:
        for hit in store.search(store.CHUNKS, query, limit=per_query):
            aid = hit["artifact_id"]
            if hit["score"] > best[aid]:
                best[aid] = hit["score"]
                why[aid] = "chunk"

        for hit in store.search(store.FACETS, query, limit=per_query):
            aid = hit["artifact_id"]
            try:
                trust = float(hit.get("trust") or 0.5)
            except (TypeError, ValueError):  # noqa: PERF203 - a bad trust value is data rot
                trust = 0.5
            score = hit["score"] * trust * 2.0
            if score > best[aid]:
                best[aid] = score
                why[aid] = f"facet L{hit.get('level')}"
                facet_id = hit.get("facet_id")
                if facet_id:
                    matched_facet[aid] = facet_id

    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:limit]

    conn = db.get_conn()
    try:
        out = []
        for aid, score in ranked:
            row = conn.execute("SELECT title FROM artifacts WHERE id = ?", (aid,)).fetchone()
            if row is None:
                continue
            out.append(
                {
                    "artifact_id": aid,
                    "title": row["title"],
                    "score": score,
                    "why": why.get(aid),
                    "matched_facet_id": matched_facet.get(aid),
                }
            )
        return out
    finally:
        conn.close()


def artifact_text(conn, artifact_id: str, max_words: int = 1200) -> str:
    """The text a judgment reads. A note has a body; a capture has its chunks."""
    row = conn.execute("SELECT body FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    text = (row["body"] if row else None) or ""
    if not text.strip():
        chunks = conn.execute(
            "SELECT text FROM chunks WHERE artifact_id = ? ORDER BY ordinal", (artifact_id,)
        ).fetchall()
        text = "\n\n".join(c["text"] for c in chunks)
    words = text.split()
    return text if len(words) <= max_words else " ".join(words[:max_words])
