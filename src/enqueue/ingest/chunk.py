"""Chunking.

A depth-0 block plus all of its descendants becomes one chunk, so a claim and the
author's elaboration on it stay together. Only oversized results get split further.

A depth-0 block with *no* children is a loose paragraph rather than a semantic unit,
so consecutive ones are merged up to a floor. Without this, pasted model output
shreds into headings and single list items: measured on the real corpus, 400 of 1421
chunks came in under ten words, concentrated in eight artifacts of pasted transcript.
A ten-word chunk embeds badly and pollutes retrieval.

The distinction is read off the block tree rather than guessed from the folder,
because pasted content appears in `books` as well as `hideas`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from .. import db

MAX_WORDS = 600  # roughly 800 tokens
SPLIT_WORDS = 380
OVERLAP_WORDS = 60
MERGE_FLOOR_WORDS = 120  # childless paragraphs accumulate to at least this


@dataclass
class Chunk:
    artifact_id: str
    ordinal: int
    text: str
    chunker: str


def _subtree(rows: list[dict], root_id: str) -> list[str]:
    """Text of a block and everything under it, in document order."""
    by_parent: dict[str | None, list[dict]] = {}
    for row in rows:
        by_parent.setdefault(row["parent_id"], []).append(row)

    out: list[str] = []

    def walk(block_id: str, indent: int) -> None:
        row = next(r for r in rows if r["id"] == block_id)
        out.append(("  " * indent) + row["text"])
        for child in sorted(by_parent.get(block_id, []), key=lambda r: r["ordinal"]):
            walk(child["id"], indent + 1)

    walk(root_id, 0)
    return out


def _split_long(text: str) -> list[str]:
    words = text.split()
    if len(words) <= MAX_WORDS:
        return [text]
    out: list[str] = []
    start = 0
    while start < len(words):
        out.append(" ".join(words[start : start + SPLIT_WORDS]))
        start += SPLIT_WORDS - OVERLAP_WORDS
    return out


def chunk_artifact(artifact_id: str, rows: list[dict]) -> list[Chunk]:
    tops = sorted((r for r in rows if r["parent_id"] is None), key=lambda r: r["ordinal"])
    has_child = {r["parent_id"] for r in rows if r["parent_id"] is not None}

    chunks: list[Chunk] = []
    ordinal = 0
    buffer: list[str] = []

    def emit(text: str, chunker: str) -> None:
        nonlocal ordinal
        for piece in _split_long(text):
            label = chunker if "\n" not in piece or chunker != "blocks-v1" else chunker
            chunks.append(Chunk(artifact_id, ordinal, piece, label))
            ordinal += 1

    def flush() -> None:
        nonlocal buffer
        if buffer:
            emit("\n".join(buffer).strip(), "blocks-v1+merged")
            buffer = []

    for top in tops:
        text = "\n".join(_subtree(rows, top["id"])).strip()
        if not text:
            continue

        if top["id"] in has_child:
            # A claim with the author's elaboration under it. Never merged.
            flush()
            emit(text, "blocks-v1")
            continue

        buffer.append(text)
        if sum(len(b.split()) for b in buffer) >= MERGE_FLOOR_WORDS:
            flush()

    flush()
    return chunks


def chunk_all() -> dict[str, int]:
    """Rebuild chunks for every artifact that has blocks. Derived data, so it is dropped first."""
    stats = {"artifacts": 0, "chunks": 0}

    with db.transaction() as conn:
        conn.execute("DELETE FROM chunks")
        artifact_ids = [
            r["artifact_id"] for r in conn.execute("SELECT DISTINCT artifact_id FROM blocks")
        ]

        for artifact_id in artifact_ids:
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT id, parent_id, ordinal, text FROM blocks WHERE artifact_id = ?"
                    " ORDER BY ordinal",
                    (artifact_id,),
                )
            ]
            chunks = chunk_artifact(artifact_id, rows)
            for chunk in chunks:
                conn.execute(
                    "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker)"
                    " VALUES (?,?,?,?,?)",
                    (
                        str(uuid.uuid4()),
                        chunk.artifact_id,
                        chunk.ordinal,
                        chunk.text,
                        chunk.chunker,
                    ),
                )
            stats["artifacts"] += 1
            stats["chunks"] += len(chunks)

    return stats
