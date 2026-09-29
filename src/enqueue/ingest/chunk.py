"""Chunking markdown.

The previous build chunked a tree of immutable blocks. The insight it produced still
holds and is what this preserves: a claim plus its elaboration is one unit, and loose
paragraphs shred into uselessly small pieces unless they are merged.

Measured on a real corpus then: a paragraph-per-chunk rule produced 1,421 chunks at a
median of 17 words, with 400 under ten. A ten-word chunk embeds badly and pollutes
retrieval. Merging fixed it without breaking the units that were already coherent.

Here the same shape is read from markdown structure instead of `parent_id`:

  - a heading and everything under it, until the next heading of equal or higher rank
  - a list and its nested items, kept whole
  - consecutive loose paragraphs, merged to a floor
"""

from __future__ import annotations

import re
import uuid

from .. import db

# The embedder reads at most config.EMBED_MAX_TOKENS and silently drops the rest, and
# the index text is the title, the chunk's context line, then the chunk. So a chunk may
# use CHUNK_MAX_TOKENS and the title and context get the remainder.
CHUNK_MAX_TOKENS = 400
OVERLAP_TOKENS = 60
MERGE_FLOOR_WORDS = 120
CHUNKER = "markdown-v2"

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _tokens(text: str) -> int:
    from ..index.embed import token_count

    return token_count(text)


def _fits(text: str) -> bool:
    # A token covers at least one character, so a short text needs no tokenizer.
    return len(text) <= CHUNK_MAX_TOKENS or _tokens(text) <= CHUNK_MAX_TOKENS


def _units(text: str) -> list[tuple[str, str]]:
    """(unit, separator) pairs: lines, then sentences within a line. Joining every unit
    with its separator gives the text back."""
    out: list[tuple[str, str]] = []
    for line in text.split("\n"):
        parts = _SENTENCE_END.split(line)
        out.extend((p, " ") for p in parts[:-1])
        out.append((parts[-1], "\n"))
    return out


def _windows(unit: str) -> list[str]:
    """A unit too long for one chunk (a run-on sentence, a long line of code), cut into
    overlapping word windows that each fit."""
    words = unit.split()
    out, start = [], 0
    while start < len(words):
        n = min(len(words) - start, CHUNK_MAX_TOKENS)
        while n > 1 and not _fits(" ".join(words[start : start + n])):
            n = n * 3 // 4
        piece = " ".join(words[start : start + n])
        if n == 1 and not _fits(piece):
            # One unbroken token run (base64, a long URL): a token is at least a character.
            out.extend(
                piece[i : i + CHUNK_MAX_TOKENS] for i in range(0, len(piece), CHUNK_MAX_TOKENS)
            )
        else:
            out.append(piece)
        if start + n >= len(words):
            break
        start += max(1, n - n * OVERLAP_TOKENS // CHUNK_MAX_TOKENS)
    return out


def _split_long(text: str) -> list[str]:
    """Pieces of `text` that each fit the embedder, cut at line and sentence boundaries,
    each starting with the last OVERLAP_TOKENS worth of units from the one before."""
    if _fits(text):
        return [text]
    units: list[tuple[str, str, int]] = []
    for unit, sep in _units(text):
        n = _tokens(unit)
        if n <= CHUNK_MAX_TOKENS:
            units.append((unit, sep, n))
        else:
            units.extend((w, sep, _tokens(w)) for w in _windows(unit))

    pieces: list[str] = []
    current: list[tuple[str, str, int]] = []
    size = 0
    for u in units:
        if current and size + u[2] > CHUNK_MAX_TOKENS:
            pieces.append("".join(t + s for t, s, _ in current).strip())
            carried, kept = [], 0
            for prev in reversed(current):
                if kept + prev[2] > OVERLAP_TOKENS or kept + prev[2] + u[2] > CHUNK_MAX_TOKENS:
                    break
                carried.insert(0, prev)
                kept += prev[2]
            current, size = carried, kept
        current.append(u)
        size += u[2]
    if current:
        pieces.append("".join(t + s for t, s, _ in current).strip())
    return [p for p in pieces if p]


def _segments(markdown: str) -> list[tuple[str, str]]:
    """Split into (kind, text) where kind is heading, list, code, or prose.

    Blank lines are held rather than consumed, because a blank line inside a list is
    a gap between items and a blank line before prose is the end of the list. That
    cannot be decided until the next non-blank line is seen. Consuming them eagerly
    made a single list swallow the entire rest of the document.
    """
    segments: list[tuple[str, str]] = []
    buf: list[str] = []
    blanks: list[str] = []
    mode = "prose"
    in_fence = False

    def flush():
        nonlocal buf, blanks
        text = "\n".join(buf).strip()
        if text:
            segments.append((mode, text))
        buf, blanks = [], []

    for line in markdown.splitlines():
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_fence:
                buf.append(line)
                in_fence = False
                flush()
            else:
                flush()
                mode = "code"
                buf.append(line)
                in_fence = True
            continue

        if in_fence:
            buf.append(line)
            continue

        if not stripped:
            blanks.append(line)
            continue

        if _HEADING.match(line):
            flush()
            mode = "heading"
        elif _LIST_ITEM.match(line):
            if mode != "list":
                flush()
                mode = "list"
            else:
                buf.extend(blanks)  # a gap between items of the same list
                blanks = []
        elif mode in ("heading", "list") and not blanks:
            pass  # a wrapped line continues what it follows
        elif mode == "heading" and blanks:
            buf.extend(blanks)  # body under a heading belongs to it
            blanks = []
        else:
            if mode != "prose" or blanks:
                flush()
                mode = "prose"

        buf.append(line)

    flush()
    return segments


def chunk_markdown(markdown: str) -> list[tuple[str, str]]:
    """Return (text, chunker) pairs.

    Headings, lists, and code fences are coherent on their own and never merge.
    Loose prose accumulates to a floor, because that is the case that shredded before.
    """
    chunks: list[tuple[str, str]] = []
    pending: list[str] = []

    def flush_pending():
        nonlocal pending
        if pending:
            joined = "\n\n".join(pending).strip()
            for piece in _split_long(joined):
                chunks.append((piece, f"{CHUNKER}+merged"))
            pending = []

    for kind, text in _segments(markdown):
        if kind in ("heading", "list", "code"):
            flush_pending()
            for piece in _split_long(text):
                chunks.append((piece, f"{CHUNKER}+{kind}"))
        else:
            pending.append(text)
            if sum(len(p.split()) for p in pending) >= MERGE_FLOOR_WORDS:
                flush_pending()

    flush_pending()
    return chunks


def chunk_artifact(conn, artifact_id: str) -> int:
    """Rebuild chunks for one artifact. Derived data, so it is replaced wholesale."""
    row = conn.execute(
        "SELECT kind, title, body, filename FROM artifacts WHERE id = ?", (artifact_id,)
    ).fetchone()
    if row is None:
        return 0

    # A chunk whose text survives the re-chunk keeps its model-written context
    # (ingest/context.py), so a reprocess or retry pays only for chunks that changed.
    kept_context = {
        r["text"]: (r["context"], r["context_model"])
        for r in conn.execute(
            "SELECT text, context, context_model FROM chunks"
            " WHERE artifact_id = ? AND context IS NOT NULL",
            (artifact_id,),
        )
    }
    conn.execute("DELETE FROM chunks WHERE artifact_id = ?", (artifact_id,))

    # Notes carry their own text. A link carries whatever its preview found out, which
    # is the only reason fetching one is worth a network request at all: it turns a
    # bare URL into something the index can match. Other captures wait for extraction.
    body = row["body"] or ""
    if not body.strip() and row["kind"] == "link":
        # Prefer the article body when the fetch captured one; fall back to the four
        # preview fields for pages that defeated extraction (JS shells, paywalls).
        page = conn.execute(
            "SELECT text FROM page_text WHERE artifact_id = ? AND page = 0",
            (artifact_id,),
        ).fetchone()
        if page:
            body = page["text"]
        else:
            from ..preview import text_for_index

            body = text_for_index(artifact_id)
    if not body.strip() and row["kind"] == "file":
        page = conn.execute(
            "SELECT text FROM page_text WHERE artifact_id = ? AND page = 0", (artifact_id,)
        ).fetchone()
        body = page["text"] if page else ""
    if not body.strip() and row["kind"] == "pdf":
        # A page is already a unit a person navigates by, so the page boundary is a
        # better chunk boundary than anything the markdown chunker would invent. Long
        # pages still split; short ones still merge.
        pages = conn.execute(
            "SELECT page, text FROM page_text WHERE artifact_id = ? ORDER BY page",
            (artifact_id,),
        ).fetchall()
        body = "\n\n".join(f"## page {p['page'] + 1}\n\n{p['text']}" for p in pages)

    # Annotations are your commentary on a captured artifact, and they are index
    # source text: the artifact must be findable by what you wrote about it. Only
    # current annotations are included (a superseded one no longer describes the
    # artifact), matching the `current` flag logic in notes.get(). The artifacts
    # body column is not touched; this is index text only.
    # L.1: prefix each annotation with the (note added by you) marker so the
    # answer model can attribute the line to a user-supplied note on the
    # artifact rather than to the artifact's own body (the PLAN Phase L chopper
    # repro: the model answered "this is just text, not an image" when the only
    # text on an image was a user annotation, because the body and the note
    # looked identical in the passage).
    notes = conn.execute(
        "SELECT a.text FROM annotations a"
        " WHERE a.artifact_id = ?"
        " AND NOT EXISTS (SELECT 1 FROM annotations b WHERE b.supersedes_id = a.id)"
        " ORDER BY a.created_at",
        (artifact_id,),
    ).fetchall()
    if notes:
        marked = "\n\n".join(f"(note added by you) {n['text']}" for n in notes)
        body = (body + "\n\n" if body.strip() else "") + marked

    # A capture whose text never materialised (an image whose vision describe
    # failed, a preview that never arrived) must still be reachable by its own
    # name: the title and filename are the only words it owns. This guarantees
    # every artifact has at least one chunk, so it is also eligible for facet
    # and entity generation, which are gated on chunks existing.
    if not body.strip() and row["kind"] != "note":
        name = " ".join(filter(None, (row["title"], row["filename"]))).strip()
        if name:
            body = name

    if not body.strip():
        return 0

    made = chunk_markdown(body)
    for ordinal, (text, chunker) in enumerate(made):
        context, context_model = kept_context.get(text, (None, None))
        conn.execute(
            "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker, context,"
            " context_model) VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), artifact_id, ordinal, text, chunker, context, context_model),
        )
    return len(made)


def chunk_all() -> dict:
    stats = {"artifacts": 0, "chunks": 0}
    with db.transaction() as conn:
        ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM artifacts WHERE deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL AND (body IS NOT NULL"
                " OR id IN (SELECT artifact_id FROM link_previews WHERE status = 'ok')"
                " OR id IN (SELECT DISTINCT artifact_id FROM page_text)"
                " OR id IN (SELECT DISTINCT artifact_id FROM annotations))"
            )
        ]
        for artifact_id in ids:
            made = chunk_artifact(conn, artifact_id)
            if made:
                stats["artifacts"] += 1
                stats["chunks"] += made
    return stats
