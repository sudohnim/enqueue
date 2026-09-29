"""Related artifacts: other notes that make the same point, or name the same thing.

Idea links: each of an artifact's facet statements searches the facet index, and
another artifact's closeness is its best facet similarity to any of them.
Mention links: another artifact whose entities name the same person, place or thing
(case-insensitive), scored MENTION_SCORE and carrying the name in `via`; a name that
more than MENTION_MAX_SHARED artifacts mention is too common to connect anything.
The top RELATED_LIMIT at or above RELATED_MIN become links, stored in both directions
(a newer note links back to the older one). Stale facets and entities never count,
and readers only show links to live artifacts. Local and cheap: no model call.
"""

from __future__ import annotations

import json

from .. import db

RELATED_LIMIT = 5
RELATED_MIN = 0.7
MENTION_SCORE = 0.7
MENTION_MAX_SHARED = 8
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
        via = _mentions(conn, artifact_id, cache)
        for other in via:
            best.setdefault(other, MENTION_SCORE)
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
                    " (artifact_id, related_id, score, model_version, created_at, via)"
                    " VALUES (?,?,?,?,?,?)",
                    (a, b, round(score, 4), model, now, via.get(other)),
                )
        conn.commit()
        return len(top)
    finally:
        conn.close()


def _mentions(conn, artifact_id: str, cache: dict) -> dict[str, str]:
    """Other live artifacts whose current entities share a name with this one's, mapped
    to the shared name (the rarest one, when several are shared)."""
    from ..retrieve.candidates import hit_is_stale

    mine = [
        dict(r)
        for r in conn.execute(
            "SELECT artifact_id, entity, model_version, body_version FROM entities"
            " WHERE artifact_id = ?",
            (artifact_id,),
        )
    ]
    names = {
        e["entity"].strip().lower(): e["entity"] for e in mine if not hit_is_stale(conn, e, cache)
    }
    if not names:
        return {}
    rows = conn.execute(
        "SELECT e.artifact_id, lower(trim(e.entity)) AS name, e.model_version, e.body_version"
        " FROM entities e JOIN artifacts a ON a.id = e.artifact_id"
        " WHERE lower(trim(e.entity)) IN (SELECT value FROM json_each(?))"
        " AND e.artifact_id != ?"
        " AND a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL",
        (json.dumps(sorted(names)), artifact_id),
    ).fetchall()
    sharers: dict[str, set[str]] = {}
    for r in rows:
        if not hit_is_stale(conn, dict(r), cache):
            sharers.setdefault(r["name"], set()).add(r["artifact_id"])
    out: dict[str, str] = {}
    for name, others in sorted(sharers.items(), key=lambda kv: len(kv[1]), reverse=True):
        if len(others) + 1 > MENTION_MAX_SHARED:
            continue
        for other in others:
            out[other] = names[name]  # rarest name last, so it wins
    return out


def for_artifact(conn, artifact_id: str) -> list[dict]:
    """Live related artifacts, closest first, each with `via` (a shared name) or None."""
    rows = conn.execute(
        "SELECT a.id, a.title, a.kind, r.score, r.via FROM related r JOIN artifacts a"
        " ON a.id = r.related_id WHERE r.artifact_id = ?"
        " AND a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL"
        " ORDER BY r.score DESC LIMIT ?",
        (artifact_id, RELATED_LIMIT),
    ).fetchall()
    return [dict(r) for r in rows]
