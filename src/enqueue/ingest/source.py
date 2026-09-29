"""The text an ingest model reads for one artifact.

A note carries its words in `body`; a link, PDF or image carries its extracted text
in `page_text` and leaves `body` empty. Every ingest writer (facets, entities) reads
through here so a capture is never summarized from its title alone. The person's own
current annotations are appended, marked as theirs: often they are the reason the
thing was saved, so they must shape what the model writes. A document too long to
read whole is map-reduced into section summaries (see `ingest_text`).
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel

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
    """What the ingest model reads, then the annotations in full.

    A document that fits in FACET_INPUT_CHARS is read whole. A longer one is
    map-reduced: each section is summarized by the ingest model and the model reads
    the summaries in order, so an idea on page 40 shapes the facets as much as one on
    page 1. If any section cannot be summarized, it falls back to the opening
    FACET_INPUT_CHARS, as before.
    """
    text = document_text(conn, artifact_id)
    if len(text) > config.FACET_INPUT_CHARS:
        text = _map_reduce(conn, artifact_id, text) or text[: config.FACET_INPUT_CHARS]
    yours = annotations_text(conn, artifact_id)
    if yours:
        text = (text + "\n\n" if text.strip() else "") + yours
    return text


# Map-reduce for long documents. A section is at most SECTION_CHARS, split on paragraph
# boundaries; at most MAX_SECTIONS are summarized (a longer tail is dropped rather than
# letting one save cost unbounded calls). Summaries are cached per section text and
# model in derived_values (scope 'section_summary'), so re-ingesting unchanged text
# costs nothing.
SECTION_CHARS = 10_000
MAX_SECTIONS = 24
SUMMARY_MAX_WORDS = 120


class _RawSectionSummary(BaseModel):
    summary: str


def sections(text: str) -> list[str]:
    """Split on paragraph boundaries into chunks of at most SECTION_CHARS."""
    out: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        while len(para) > SECTION_CHARS:  # one enormous paragraph: hard-split it
            if current:
                out.append(current)
                current = ""
            out.append(para[:SECTION_CHARS])
            para = para[SECTION_CHARS:]
        if current and len(current) + 2 + len(para) > SECTION_CHARS:
            out.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current.strip():
        out.append(current)
    return out


def _map_reduce(conn, artifact_id: str, text: str) -> str | None:
    """Ordered section summaries of a long document, or None if any section failed."""
    from ..prompts import SECTION_SUMMARY
    from ..providers.base import get_provider

    row = conn.execute(
        "SELECT title, status, local_only FROM artifacts WHERE id = ?", (artifact_id,)
    ).fetchone()
    if row is None or row["status"] == "text_only":
        return None  # secret-flagged text never reaches a model
    try:
        provider = get_provider(local_only=bool(row["local_only"]), role="ingest")
    except Exception:  # noqa: BLE001 - fall back to the capped opening
        return None
    parts = sections(text)[:MAX_SECTIONS]
    summaries = []
    for i, part in enumerate(parts, start=1):
        key = hashlib.sha256(part.encode("utf-8")).hexdigest()
        cached = conn.execute(
            "SELECT value FROM derived_values WHERE scope = 'section_summary' AND subject = ?"
            " AND attribute = ? AND model_version = ?",
            (artifact_id, key, provider.model),
        ).fetchone()
        if cached:
            summary = cached["value"]
        else:
            try:
                raw = provider.complete(
                    system=SECTION_SUMMARY,
                    user=f"Document: {row['title']}\nSection {i} of {len(parts)}\n\n{part}",
                    response_model=_RawSectionSummary,
                )
            except Exception:  # noqa: BLE001 - one failed section: use the capped opening
                return None
            summary = " ".join(raw.summary.split()[:SUMMARY_MAX_WORDS])
            if not summary:
                return None
            conn.execute(
                "INSERT OR REPLACE INTO derived_values (scope, subject, attribute, value,"
                " grounded, source, model_version, created_at)"
                " VALUES ('section_summary', ?, ?, ?, 1, 'model', ?, ?)",
                (artifact_id, key, summary, provider.model, _now()),
            )
        summaries.append(summary)
    _store_sections(conn, artifact_id, summaries, provider.model)
    return "(A long document, read as summaries of its sections in order.)\n\n" + "\n\n".join(
        f"Section {i} of {len(summaries)}: {s}" for i, s in enumerate(summaries, start=1)
    )


def _store_sections(conn, artifact_id: str, summaries: list[str], model: str) -> None:
    """Replace the artifact's searchable section summaries (the `sections` layer).

    Stamped like facets, with the ingest model and the body version they were read
    from, so search drops them once either moves on. The ingest queue indexes them.
    """
    import uuid

    body_version = conn.execute(
        "SELECT MAX(created_at) AS v FROM artifact_versions WHERE artifact_id = ?",
        (artifact_id,),
    ).fetchone()["v"]
    existing = conn.execute(
        "SELECT summary, model_version, body_version FROM sections WHERE artifact_id = ?"
        " ORDER BY ordinal",
        (artifact_id,),
    ).fetchall()
    if [tuple(r) for r in existing] == [(s, model, body_version) for s in summaries]:
        return  # map-reduce runs once per ingest writer; unchanged rows keep their index
    conn.execute("DELETE FROM sections WHERE artifact_id = ?", (artifact_id,))
    conn.executemany(
        "INSERT INTO sections (id, artifact_id, ordinal, summary, model_version,"
        " body_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (str(uuid.uuid4()), artifact_id, i, s, model, body_version, _now())
            for i, s in enumerate(summaries, start=1)
        ],
    )


def _now() -> str:
    from .. import db

    return db.now()
