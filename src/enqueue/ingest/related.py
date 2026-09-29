"""Related artifacts: which other notes make the same point, found at ingest.

Each of an artifact's facet statements searches the facet index. Another artifact's
closeness is its best facet similarity to any of them; the top RELATED_LIMIT at or
above RELATED_MIN become links, stored in both directions (a newer note links back
to the older one it resembles). Stale facets (older body or model) never count, and
readers only show links to live artifacts. Local and cheap: no model call.
"""

from __future__ import annotations

from .. import db

RELATED_LIMIT = 5
RELATED_MIN = 0.7
_PER_STATEMENT = 20


def compute(artifact_id: str) -> int:
    """Recompute one artifact's links. Returns how many were written."""
    from ..index.store import get_store
    from ..providers.base import model_for
    from ..retrieve.candidates import hit_is_stale

    store = get_store()
    conn = db.get_conn()
    try:
        statements = [
            r["statement"]
            for r in conn.execute(
                "SELECT statement FROM facets WHERE artifact_id = ?", (artifact_id,)
            )
        ]
        best: dict[str, float] = {}
        cache: dict = {}
        for statement in statements:
            for hit in store.search_dense(
                store.FACETS, statement, limit=_PER_STATEMENT, as_query=False
            ):
                other = hit["artifact_id"]
                if other == artifact_id or hit["score"] < RELATED_MIN:
                    continue
                if hit_is_stale(conn, hit, cache):
                    continue
                best[other] = max(best.get(other, 0.0), hit["score"])
        top = sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:RELATED_LIMIT]

        model = model_for("ingest")
        now = db.now()
        conn.execute(
            "DELETE FROM related WHERE artifact_id = ? OR related_id = ?",
            (artifact_id, artifact_id),
        )
        for other, score in top:
            for a, b in ((artifact_id, other), (other, artifact_id)):
                conn.execute(
                    "INSERT OR REPLACE INTO related"
                    " (artifact_id, related_id, score, model_version, created_at)"
                    " VALUES (?,?,?,?,?)",
                    (a, b, round(score, 4), model, now),
                )
        conn.commit()
        return len(top)
    finally:
        conn.close()


def for_artifact(conn, artifact_id: str) -> list[dict]:
    """Live related artifacts, closest first."""
    rows = conn.execute(
        "SELECT a.id, a.title, a.kind, r.score FROM related r JOIN artifacts a"
        " ON a.id = r.related_id WHERE r.artifact_id = ?"
        " AND a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL"
        " ORDER BY r.score DESC LIMIT ?",
        (artifact_id, RELATED_LIMIT),
    ).fetchall()
    return [dict(r) for r in rows]
