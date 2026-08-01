"""Candidate generation: search both layers, roll up to artifacts.

At POC scale this returns nearly the whole corpus, which is correct and expected.
Recall is trivially high when the candidate pool is the collection, so the number
that matters here is the ranking after rerank, not this stage. Do not add filtering
to make the count look better.

`candidates` rolls chunk and facet hits up to one entry per artifact, which is
what the rerank stage needs. `search_results` is the same rollup shaped for the
/search surface: one row per artifact (an artifact cannot occupy every result
slot), with a snippet, fused chunk + facet scores, and the matched-facet marker.
"""

from __future__ import annotations

from collections import defaultdict

from .. import db
from ..index.store import get_store


def _log_sub_queries(queries: list[str]) -> None:
    """Make the cost of expansion visible in the engine log.

    A lens expands into several sub-queries; each one searches both
    collections and both branches. The count is the multiplier on retrieval
    cost, so it is printed once per search rather than hidden.
    """
    if len(queries) > 1:
        print(f"[search] {len(queries)} sub-queries (query expansion)", flush=True)


def candidates(
    queries: list[str], limit: int = 150, per_query: int = 40, prefetch: int = 100
) -> list[dict]:
    """Artifact ids ordered by best hit across both collections.

    Facet hits are weighted by the facet's trust score, so an abstraction that keeps
    winning matches the director then ejects quietly stops pulling artifacts in.

    `prefetch` widens the per-branch window the store searches before fusion. The
    default keeps ordinary retrieval unchanged; whole-library scoring raises it so
    that every chunk is actually searched (otherwise a chunk beyond the fixed
    window is silently never seen, which would make a "complete" coverage label a
    lie).
    """
    _log_sub_queries(queries)
    best: dict[str, float] = defaultdict(float)
    why: dict[str, str] = {}
    matched_facet: dict[str, str] = {}

    store = get_store()
    for query in queries:
        for hit in store.search(store.CHUNKS, query, limit=per_query, prefetch=prefetch):
            aid = hit["artifact_id"]
            if hit["score"] > best[aid]:
                best[aid] = hit["score"]
                why[aid] = "chunk"

        for hit in store.search(store.FACETS, query, limit=per_query, prefetch=prefetch):
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


def search_results(q: str, limit: int = 20) -> list[dict]:
    """One result per artifact for the /search surface.

    Chunk and facet hits are rolled up to artifact ids (a facet hit weighted
    by trust) and deduplicated, so one artifact cannot occupy every result
    slot: six chunks of one note come back as one row. The snippet is the
    text of the best matching chunk; a facet-only match shows the artifact
    face instead.
    """
    store = get_store()
    # A wider per-branch window than the final limit, so the dedup rolls up
    # from enough chunk and facet hits to rank fairly.
    per_query = limit * 3
    prefetch = max(100, limit * 5)
    chunk_hits = store.search(store.CHUNKS, q, limit=per_query, prefetch=prefetch)
    facet_hits = store.search(store.FACETS, q, limit=per_query, prefetch=prefetch)

    best: dict[str, dict] = {}
    for hit in chunk_hits:
        aid = hit["artifact_id"]
        if aid not in best or hit["score"] > best[aid]["score"]:
            best[aid] = {"score": hit["score"], "chunk_id": hit["chunk_id"], "why": "chunk"}
    for hit in facet_hits:
        aid = hit["artifact_id"]
        try:
            trust = float(hit.get("trust") or 0.5)
        except (TypeError, ValueError):  # noqa: PERF203 - a bad trust value is data rot
            trust = 0.5
        score = hit["score"] * trust * 2.0
        if aid not in best or score > best[aid]["score"]:
            best[aid] = {"score": score, "chunk_id": None, "why": f"facet L{hit.get('level')}"}

    ranked = sorted(best.items(), key=lambda kv: kv[1]["score"], reverse=True)[:limit]

    conn = db.get_conn()
    try:
        out = []
        for aid, info in ranked:
            if info["chunk_id"]:
                row = conn.execute(
                    "SELECT a.title, a.kind, c.text AS snippet FROM chunks c"
                    " JOIN artifacts a ON a.id = c.artifact_id WHERE c.id = ?",
                    (info["chunk_id"],),
                ).fetchone()
                if row is None:
                    continue
                title, kind, snippet = row["title"], row["kind"], row["snippet"]
            else:
                row = conn.execute(
                    "SELECT title, kind FROM artifacts WHERE id = ?", (aid,)
                ).fetchone()
                if row is None:
                    continue
                title, kind = row["title"], row["kind"]
                snippet = artifact_text(conn, aid, max_words=40)
            out.append(
                {
                    "score": round(info["score"], 4),
                    "artifact_id": aid,
                    "title": title,
                    "kind": kind,
                    "why": info["why"],
                    "snippet": " ".join(snippet.split())[:200],
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
