"""The text an ingest model reads for one artifact.

A note carries its words in `body`; a link, PDF or image carries its extracted text
in `page_text` and leaves `body` empty. Every ingest writer (facets, entities) reads
through here so a capture is never summarized from its title alone. The person's own
current annotations are appended, marked as theirs: often they are the reason the
thing was saved, so they must shape what the model writes.
"""

from __future__ import annotations

from .. import config


def document_text(conn, artifact_id: str) -> str:
    """The artifact's own words: its body, else its extracted pages in order."""
    row = conn.execute("SELECT body FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    text = (row["body"] if row else "") or ""
    if text.strip():
        return text
    pages = conn.execute(
        "SELECT text FROM page_text WHERE artifact_id = ? ORDER BY page", (artifact_id,)
    ).fetchall()
    return "\n\n".join(p["text"] for p in pages if p["text"])


def annotations_text(conn, artifact_id: str) -> str:
    """Current (non-superseded) annotations, each marked "(your note)"."""
    rows = conn.execute(
        "SELECT a.text FROM annotations a WHERE a.artifact_id = ?"
        " AND NOT EXISTS (SELECT 1 FROM annotations b WHERE b.supersedes_id = a.id)"
        " ORDER BY a.created_at",
        (artifact_id,),
    ).fetchall()
    return "\n\n".join(f"(your note) {a['text']}" for a in rows if a["text"])


def ingest_text(conn, artifact_id: str) -> str:
    """Document text capped at FACET_INPUT_CHARS, then the annotations in full."""
    text = document_text(conn, artifact_id)[: config.FACET_INPUT_CHARS]
    yours = annotations_text(conn, artifact_id)
    if yours:
        text = (text + "\n\n" if text.strip() else "") + yours
    return text
