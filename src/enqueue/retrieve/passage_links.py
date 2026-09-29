"""Passage connections: for each passage of one artifact, the other notes that say
something close to it.

Related notes (ingest/related.py) link whole artifacts; a long note or PDF touches
many subjects, and the link a person wants is often to one paragraph. Each indexed
chunk's stored vector finds its nearest chunks in other live artifacts; those at or
above PASSAGE_MIN, best first and at most LINKS_PER_PASSAGE per passage, become its
connections. Computed on demand from the index (no model call, nothing stored), for
at most MAX_PASSAGES passages.
"""

from __future__ import annotations

import json
import re

from .. import db

PASSAGE_MIN = 0.78  # passage-to-passage cosine; ~a quarter of eval-corpus passages link
LINKS_PER_PASSAGE = 3
MAX_PASSAGES = 40
_NEIGHBOURS = 12
EXCERPT_WORDS = 24


def for_artifact(artifact_id: str) -> list[dict]:
    """[{chunk_id, ordinal, excerpt, links: [{id, title, kind, score}]}], passages
    with no connection left out, in document order."""
    from ..index.store import get_store

    store = get_store()
    conn = db.get_conn()
    try:
        chunks = conn.execute(
            "SELECT id, ordinal, text FROM chunks WHERE artifact_id = ? ORDER BY ordinal LIMIT ?",
            (artifact_id, MAX_PASSAGES),
        ).fetchall()
        found: list[tuple] = []
        others: set[str] = set()
        for c in chunks:
            best: dict[str, float] = {}
            for hit in store.similar_chunks(c["id"], limit=_NEIGHBOURS):
                other = hit["artifact_id"]
                if other != artifact_id and hit["score"] >= PASSAGE_MIN:
                    best[other] = max(best.get(other, 0.0), hit["score"])
            if best:
                top = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
                found.append((c, top[:LINKS_PER_PASSAGE]))
                others.update(best)
        if not found:
            return []
        live = {
            r["id"]: r
            for r in conn.execute(
                "SELECT id, title, kind FROM artifacts WHERE id IN (SELECT value FROM json_each(?))"
                " AND deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL",
                (json.dumps(sorted(others)),),
            )
        }
    finally:
        conn.close()

    out = []
    for c, top in found:
        links = [
            {
                "id": aid,
                "title": live[aid]["title"],
                "kind": live[aid]["kind"],
                "score": round(s, 3),
            }
            for aid, s in top
            if aid in live
        ]
        if links:
            # A note's first chunk opens with its "# Title" heading; the drawer already
            # names the note, so the excerpt starts at its words.
            text = re.sub(r"^(?:#+[^\n]*\n+)+", "", c["text"].lstrip())
            words = " ".join(text.split()).split(" ")
            excerpt = " ".join(words[:EXCERPT_WORDS]) + (
                " ..." if len(words) > EXCERPT_WORDS else ""
            )
            out.append(
                {"chunk_id": c["id"], "ordinal": c["ordinal"], "excerpt": excerpt, "links": links}
            )
    return out
