"""Score every artifact against a lens, with no model calls.

Stage one of the two-stage lens. Vector + keyword search over the whole
library (through the Part 1 `VectorStore` interface), rolled up to artifact
ids the same way the curate path does, one score per artifact. Instant by
construction: a couple of searches and no language model anywhere in this
file.

Whole-library scoring is a heavy query shape on the current engine: a search
whose limit is the library size rather than a page size. The limit is set
from the counts rather than guessed, so the coverage claim the lens makes
later (Phase 10) stays true. This becomes a natural shape after Part 3.
"""

from __future__ import annotations

from .. import db
from .candidates import candidates as get_candidates


def score_all(lens: str, cap: int | None = None) -> dict[str, float]:
    """A relevance score for every non-deleted artifact; zero when unmatched.

    Uses the same rollup as the curate path (chunk hits, facet hits weighted
    by trust) so these scores are comparable to what the model judges later.
    Model expansion is deliberately excluded: it costs seconds, and this stage
    is required to be instant. The lens text is the query.

    `cap` bounds the search window (chunk-level per-query limit and prefetch).
    When the window is smaller than the chunk count, some chunks are never
    searched; the caller reports `partial` coverage in that case (D3). The
    default covers everything.
    """
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id FROM artifacts WHERE deleted_at IS NULL ORDER BY created_at, id"
        ).fetchall()
        chunk_count = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
    finally:
        conn.close()

    ids = [r["id"] for r in rows]
    # The chunk-level limit must cover every chunk, not a page, or artifacts
    # whose best chunk ranks low would be missed and quietly score zero. The
    # artifact-level limit is the whole library for the same reason. The
    # prefetch window is raised to match, because a window narrower than the
    # chunk count would silently leave chunks outside the fusion.
    window = chunk_count if cap is None else min(cap, chunk_count)
    rows = get_candidates(
        [lens],
        limit=max(len(ids), 1),
        per_query=max(window, len(ids), 1),
        prefetch=max(window, 1),
    )
    best = {row["artifact_id"]: row["score"] for row in rows}

    # Zero is a score, not an absence: every artifact gets an entry, so the
    # caller can trust the dictionary has exactly one entry per artifact.
    return {aid: best.get(aid, 0.0) for aid in ids}
