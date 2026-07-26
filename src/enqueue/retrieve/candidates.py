"""Candidate generation: search both layers, roll up to artifacts.

At POC scale this returns nearly the whole corpus, which is correct and expected.
Recall is trivially high when the candidate pool is the collection, so the number
that matters here is the ranking after rerank, not this stage. Do not add filtering
to make the count look better.
"""

from __future__ import annotations

from collections import defaultdict

from .. import db
from ..index import qdrant


def candidates(queries: list[str], limit: int = 150, per_query: int = 40) -> list[dict]:
    """Artifact ids ordered by best hit across both collections.

    Facet hits are weighted by the facet's trust score, so an abstraction that keeps
    winning matches the director then ejects quietly stops pulling artifacts in.
    """
    best: dict[str, float] = defaultdict(float)
    why: dict[str, str] = {}
    matched_facet: dict[str, str] = {}

    for query in queries:
        for hit in qdrant.search(qdrant.CHUNKS, query, limit=per_query):
            aid = hit["artifact_id"]
            if hit["score"] > best[aid]:
                best[aid] = hit["score"]
                why[aid] = "chunk"

        for hit in qdrant.search(qdrant.FACETS, query, limit=per_query):
            aid = hit["artifact_id"]
            score = hit["score"] * float(hit.get("trust", 0.5)) * 2.0
            if score > best[aid]:
                best[aid] = score
                why[aid] = f"facet L{hit.get('level')}"
                matched_facet[aid] = hit.get("facet_id")

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
    rows = conn.execute(
        "SELECT text, depth FROM blocks WHERE artifact_id = ? ORDER BY ordinal", (artifact_id,)
    ).fetchall()
    text = "\n".join(("  " * r["depth"]) + r["text"] for r in rows)
    words = text.split()
    return text if len(words) <= max_words else " ".join(words[:max_words])
