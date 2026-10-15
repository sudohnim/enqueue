"""Contextual chunks: the ingest model places each chunk of a long document in it.

Embedding a chunk on its own loses its document: a passage that says "the second
approach failed too" never matches a search for what the approach was. For every
artifact with more than one chunk, the ingest model reads the document and writes
one or two sentences per chunk (what document, which part, what it refers to). The
line is embedded and keyword-indexed with the chunk (index/store_sqlite.py).

Single-chunk artifacts are skipped: the title already gives them their context.
Best effort like facets: a failure leaves plain chunks, which still index.
"""

from __future__ import annotations

from pydantic import BaseModel

# Chunks per model call. A long PDF is contextualized in batches of this size, each
# call seeing the same document text.
BATCH = 30
# Words of each chunk shown to the model; enough to recognise it, not the whole text.
CHUNK_PREVIEW_WORDS = 80
MAX_CONTEXT_WORDS = 50


class _RawChunkContext(BaseModel):
    index: int
    context: str


class _RawChunkContextSet(BaseModel):
    contexts: list[_RawChunkContext]


def _clean(context: str | None) -> str | None:
    text = " ".join((context or "").split())
    if not text or len(text.split()) > MAX_CONTEXT_WORDS:
        return None
    return text


def generate_for_artifact(conn, artifact_id: str, redo: bool = False) -> tuple[int, str | None]:
    """Write context for each chunk of one artifact. Returns (count, error).

    Skips artifacts with fewer than two chunks, and anything the secret scanner
    marked text_only, whose text must never reach a model. A chunk that already has a
    context keeps it, whichever model or device wrote it, unless `redo` (the ingest
    model was changed, or the person asked to rebuild): then only this model's count.
    """
    from ..prompts import CHUNK_CONTEXT
    from ..providers.base import get_provider
    from .source import SummariesOwed, ingest_text, owed_or_plain

    row = conn.execute(
        "SELECT title, status, local_only FROM artifacts WHERE id = ?", (artifact_id,)
    ).fetchone()
    if row is None or row["status"] == "text_only":
        return 0, None
    chunks = conn.execute(
        "SELECT id, text, context, context_model FROM chunks WHERE artifact_id = ?"
        " ORDER BY ordinal",
        (artifact_id,),
    ).fetchall()
    if len(chunks) < 2:
        return 0, None

    provider = get_provider(local_only=bool(row["local_only"]), role="ingest")
    # Only chunks without a context: a retry after a partial run, a re-chunk that kept
    # most chunks (ingest/chunk.py carries contexts over) or a document whose contexts
    # arrived from another device (sync/snapshot.py) costs only what is missing.
    chunks = [
        c for c in chunks if not c["context"] or (redo and c["context_model"] != provider.model)
    ]
    if not chunks:
        return 0, None
    try:
        document = ingest_text(conn, artifact_id)
    except SummariesOwed as exc:
        return 0, owed_or_plain(exc)
    written = 0
    for start in range(0, len(chunks), BATCH):
        batch = chunks[start : start + BATCH]
        listing = "\n\n".join(
            f"[{i}] " + " ".join(c["text"].split()[:CHUNK_PREVIEW_WORDS])
            for i, c in enumerate(batch, start=1)
        )
        try:
            raw = provider.complete(
                system=CHUNK_CONTEXT,
                user=f"Title: {row['title']}\n\nDocument:\n{document}\n\nChunks:\n\n{listing}",
                response_model=_RawChunkContextSet,
            )
        except Exception as exc:  # noqa: BLE001 - the caller logs; chunks stay plain
            return written, owed_or_plain(exc)
        by_index = {c.index: _clean(c.context) for c in raw.contexts}
        for i, c in enumerate(batch, start=1):
            context = by_index.get(i)
            if context:
                conn.execute(
                    "UPDATE chunks SET context = ?, context_model = ? WHERE id = ?",
                    (context, provider.model, c["id"]),
                )
                remember(conn, artifact_id, c["text"], context, provider.model)
                written += 1
    return written, None


def remember(conn, artifact_id: str, text: str, context: str, model: str) -> None:
    """Keep a passage's placement by the hash of its text, where a re-chunk on this
    device and a snapshot for another (sync/snapshot.py, derived_layers) find it."""
    import hashlib

    from .. import db

    conn.execute(
        "INSERT OR REPLACE INTO derived_values (scope, subject, attribute, value, grounded,"
        " source, model_version, created_at) VALUES ('chunk_context', ?, ?, ?, 1, 'model', ?, ?)",
        (artifact_id, hashlib.sha256(text.encode("utf-8")).hexdigest(), context, model, db.now()),
    )


def remembered(conn, artifact_id: str) -> dict[str, tuple[str, str]]:
    """Placements kept for this artifact, by the hash of the passage's text."""
    return {
        r["attribute"]: (r["value"], r["model_version"])
        for r in conn.execute(
            "SELECT attribute, value, model_version FROM derived_values"
            " WHERE scope = 'chunk_context' AND subject = ?",
            (artifact_id,),
        )
    }
