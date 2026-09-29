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


def generate_for_artifact(conn, artifact_id: str) -> tuple[int, str | None]:
    """Write context for each chunk of one artifact. Returns (count, error).

    Skips artifacts with fewer than two chunks, and anything the secret scanner
    marked text_only, whose text must never reach a model.
    """
    from ..prompts import CHUNK_CONTEXT
    from ..providers.base import get_provider
    from .source import ingest_text

    row = conn.execute(
        "SELECT title, status, local_only FROM artifacts WHERE id = ?", (artifact_id,)
    ).fetchone()
    if row is None or row["status"] == "text_only":
        return 0, None
    chunks = conn.execute(
        "SELECT id, text FROM chunks WHERE artifact_id = ? ORDER BY ordinal", (artifact_id,)
    ).fetchall()
    if len(chunks) < 2:
        return 0, None

    provider = get_provider(local_only=bool(row["local_only"]), role="ingest")
    document = ingest_text(conn, artifact_id)
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
            return written, f"{type(exc).__name__}: {exc}"[:300]
        by_index = {c.index: _clean(c.context) for c in raw.contexts}
        for i, c in enumerate(batch, start=1):
            context = by_index.get(i)
            if context:
                conn.execute(
                    "UPDATE chunks SET context = ?, context_model = ? WHERE id = ?",
                    (context, provider.model, c["id"]),
                )
                written += 1
    return written, None
