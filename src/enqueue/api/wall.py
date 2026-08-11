"""Shared wall-shaping helpers: what a wall row is and how a batch is decorated.

Used by the artifacts wall, pivot runs, and anything that renders cards. All
SQL work happens on a caller-supplied connection so a router can batch several
of these into one transaction. ORDERINGS rides here because it is the wall's
ordering vocabulary, consumed by the same routers.
"""

from __future__ import annotations

import json

from .. import capture


def _excerpt(body: str, title: str, limit: int = 600) -> str:
    """The opening of a note, kept as markdown so the wall renders its structure.

    The face is the note's own opening, not a paraphrase: a bullet list stays a
    bullet list and a paragraph keeps its line breaks. The opening heading is
    dropped because the card title above it already carries that line. The slice
    stops at a line boundary so no list item or sentence is cut mid-line; the
    client renders the slice with the same markdown renderer the editor uses.
    """
    lines = body.splitlines()
    if lines and lines[0].lstrip("#").strip() == title.strip():
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines.pop(0)

    out: list[str] = []
    used = 0
    for ln in lines:
        used += len(ln) + 1
        if used > limit and out:
            break
        out.append(ln)
    return "\n".join(out).strip()


ORDERINGS = {
    # When it was last touched. This is the wall's default: saving, editing, or
    # annotating an artifact bumps `updated_at`, so the wall rises to what you
    # are working on. "Ingested" is the shelf order, the order things
    # landed in; it stays available but is not the default. (The previous text
    # here claimed ingested was the default; the endpoint has always defaulted
    # to touched, and notes.py says the wall is ordered by last touch.)
    "ingested": "created_at DESC",
    "touched": "updated_at DESC",
    "title": "title COLLATE NOCASE ASC",
    # Relevance has no SQL ordering: there is no score column on the wall. It is
    # listed so an ordering control could express it someday; the wall rejects it
    # with a clear 400.
    "relevance": None,
}


_ARTIFACT_COLUMNS = (
    "id, kind, title, body, source_url, mime, filename, created_at,"
    " updated_at, local_only, pinned, status, pages"
)


def _link_images(conn, link_ids: list[str]) -> set[str]:
    """Which of these links have a preview image. One query, no per-row opens."""
    if not link_ids:
        return set()
    # json_each keeps the IN clause fully parameterized: the ids travel as one
    # JSON string argument, never interpolated into the SQL text.
    return {
        r["artifact_id"]
        for r in conn.execute(
            "SELECT artifact_id FROM link_previews"
            " WHERE artifact_id IN (SELECT value FROM json_each(?))"
            " AND image_hash IS NOT NULL",
            (json.dumps(link_ids),),
        )
    }


def _wall_tags(conn, artifact_ids: list[str]) -> dict[str, list[str]]:
    """All tags for a batch of artifacts, one query, name lists per id.

    The wall's Tags grouping needs every row's tags up front (an artifact can
    sit under several shelves), so the batch comes back as id -> names and
    `_wall_item` copies its slice into the row.
    """
    if not artifact_ids:
        return {}
    rows = conn.execute(
        "SELECT at.artifact_id, t.name FROM artifact_tags at"
        " JOIN tags t ON t.id = at.tag_id"
        " WHERE at.artifact_id IN (SELECT value FROM json_each(?))",
        (json.dumps(sorted(set(artifact_ids))),),
    ).fetchall()
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(row["artifact_id"], []).append(row["name"])
    return out


def _wall_item(
    conn, row, with_image: set[str] | None = None, with_tags: dict[str, list[str]] | None = None
) -> dict:
    """One wall row, with everything the client renders, no second call.

    The page-count lazy fill opens the PDF once, then writes the count back so
    no listing ever pays for that row again (the file cannot change, so the
    stored count cannot go stale). Tags ride along for the wall's Tags
    grouping; conversations cannot be tagged, so their slice is always empty.
    """
    item = dict(row)
    item["excerpt"] = _excerpt(item.pop("body") or "", row["title"])
    item["has_blob"] = row["mime"] is not None and row["kind"] != "link"
    if row["kind"] != "pdf":
        item.pop("pages", None)
    elif item["pages"] is None:
        item["pages"] = capture.page_count(row["id"])
    if row["kind"] == "link":
        item["has_preview_image"] = row["id"] in (with_image or set())
    item["tags"] = (with_tags or {}).get(row["id"], [])
    return item
