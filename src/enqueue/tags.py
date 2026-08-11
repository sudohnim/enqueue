"""Tags: optional, user-authored labels on artifacts.

A tag is a later act on an artifact that already exists. Nothing at capture
time ever asks for one, and nothing here is required. The two tables (tags,
artifact_tags) are SOURCE data: they are never derived from content and they
survive `enq rebuild`.

One canonical tag name is stored: lowercased and trimmed. Matching is exact,
never fuzzy. Conversations cannot be tagged; only rows in `artifacts`.
"""

from __future__ import annotations

import json
import uuid

from . import db


def normalize(name: str) -> str:
    """The canonical form of a tag name: lowercased and trimmed."""
    out = name.strip().lower()
    if not out:
        raise ValueError("a tag needs a name")
    return out


def add(artifact_id: str, name: str) -> dict:
    """Attach a tag to an artifact. Idempotent: tagging twice is tagging once."""
    tag_name = normalize(name)
    now = db.now()
    with db.transaction() as conn:
        exists = conn.execute("SELECT 1 FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if exists is None:
            raise KeyError(artifact_id)

        conn.execute(
            "INSERT OR IGNORE INTO tags (id, name, created_at) VALUES (?,?,?)",
            (str(uuid.uuid4()), tag_name, now),
        )
        tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()["id"]
        conn.execute(
            "INSERT OR IGNORE INTO artifact_tags (artifact_id, tag_id, created_at)"
            " VALUES (?,?,?)",
            (artifact_id, tag_id, now),
        )
        # Tagging is touching the artifact, and the wall is ordered by last touch.
        conn.execute("UPDATE artifacts SET updated_at = ? WHERE id = ?", (now, artifact_id))
    return {"artifact_id": artifact_id, "name": tag_name}


def remove(artifact_id: str, name: str) -> dict:
    """Detach a tag, and drop the tag itself when nothing references it anymore."""
    tag_name = normalize(name)
    now = db.now()
    with db.transaction() as conn:
        conn.execute(
            "DELETE FROM artifact_tags WHERE artifact_id = ? AND tag_id = ("
            "  SELECT id FROM tags WHERE name = ?"
            ")",
            (artifact_id, tag_name),
        )
        conn.execute(
            "DELETE FROM tags WHERE name = ? AND NOT EXISTS ("
            "  SELECT 1 FROM artifact_tags WHERE tag_id = tags.id"
            ")",
            (tag_name,),
        )
        conn.execute("UPDATE artifacts SET updated_at = ? WHERE id = ?", (now, artifact_id))
    return {"artifact_id": artifact_id, "name": tag_name, "removed": True}


def for_artifact(artifact_id: str) -> list[str]:
    """An artifact's tag names, ordered by name."""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT t.name FROM tags t JOIN artifact_tags at ON at.tag_id = t.id"
            " WHERE at.artifact_id = ? ORDER BY t.name",
            (artifact_id,),
        ).fetchall()
    finally:
        conn.close()
    return [r["name"] for r in rows]


def cloud() -> list[dict]:
    """Every tag with its artifact count, most-used first."""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT t.name, COUNT(at.artifact_id) AS n FROM tags t"
            " JOIN artifact_tags at ON at.tag_id = t.id"
            " GROUP BY t.id ORDER BY n DESC, t.name"
        ).fetchall()
    finally:
        conn.close()
    return [{"name": r["name"], "count": r["n"]} for r in rows]


def parse_tags(q: str) -> tuple[str, list[str]]:
    """Split a query into free text and tag filters.

    A token shaped `#word` or `tag:word` is a tag: the prefix is stripped and the
    name normalized. Everything else rejoins into the free text, which is what the
    hybrid search sees. A bare `#` or `tag:` with nothing after it is not a tag and
    stays in the free text.
    """
    free: list[str] = []
    names: list[str] = []
    for token in q.split():
        rest = None
        if token.startswith("#"):
            rest = token[1:]
        elif token.startswith("tag:"):
            rest = token[4:]
        if rest is not None and rest.strip():
            names.append(normalize(rest))
        else:
            free.append(token)
    return " ".join(free), names


def ids_with_all(names: list[str]) -> set[str]:
    """Artifact ids carrying ALL of the given (already normalized) tag names.

    Empty input returns an empty set; the caller treats that as no filter.
    """
    if not names:
        return set()
    # json_each keeps the IN clause fully parameterized: the names travel as one
    # JSON string argument, never interpolated into the SQL text.
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT artifact_id FROM artifact_tags at"
            " JOIN tags t ON t.id = at.tag_id"
            " WHERE t.name IN (SELECT value FROM json_each(?))"
            " GROUP BY artifact_id"
            " HAVING COUNT(DISTINCT t.name) = ?",
            (json.dumps(names), len(names)),
        ).fetchall()
    finally:
        conn.close()
    return {r["artifact_id"] for r in rows}
