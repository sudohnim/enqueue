"""The chunker keeps every chunk inside what the embedder reads."""

from __future__ import annotations

import base64
import re
import uuid

from enqueue import config, db
from enqueue.index.embed import token_count
from enqueue.index.store_sqlite import CHUNK_INDEX_TEXT_WITH_CONTEXT
from enqueue.ingest import chunk as chunk_mod

SENTENCES = [
    f"Sentence {i} explains how the {w} reacts when pressure builds over a long season."
    for i, w in enumerate(["clay", "kiln", "glaze", "wheel", "slip", "trimming tool"] * 40)
]


def _pieces(markdown: str) -> list[str]:
    return [text for text, _ in chunk_mod.chunk_markdown(markdown)]


def test_short_text_is_one_chunk_labelled_with_the_chunker():
    assert chunk_mod.chunk_markdown("A short note about wedging clay.") == [
        ("A short note about wedging clay.", "markdown-v2+merged")
    ]


def test_long_prose_splits_on_sentences_and_every_piece_fits():
    pieces = _pieces(" ".join(SENTENCES))

    assert len(pieces) > 1
    for p in pieces:
        assert token_count(p) <= chunk_mod.CHUNK_MAX_TOKENS
        assert p.startswith("Sentence ") and p.endswith("season.")


def test_pieces_overlap_and_lose_nothing():
    pieces = _pieces(" ".join(SENTENCES))

    for before, after in zip(pieces, pieces[1:]):
        assert after.split(". ")[0] in before  # the next piece opens with the last one's tail
    seen = {int(n) for p in pieces for n in re.findall(r"Sentence (\d+)", p)}
    assert seen == set(range(len(SENTENCES)))


def test_long_list_splits_on_lines():
    items = "\n".join(f"- {s}" for s in SENTENCES)

    pieces = _pieces(items)

    assert len(pieces) > 1
    for p in pieces:
        assert token_count(p) <= chunk_mod.CHUNK_MAX_TOKENS
        assert all(line.startswith("- ") for line in p.splitlines())


def test_an_unbroken_run_still_fits():
    blob = base64.b64encode(bytes(range(256)) * 12).decode()

    pieces = _pieces(f"Key material:\n\n{blob}")

    assert "".join(pieces).replace("Key material:", "").replace("\n", "") == blob
    assert all(token_count(p) <= chunk_mod.CHUNK_MAX_TOKENS for p in pieces)


def test_a_full_chunk_with_title_and_context_is_not_truncated():
    """What the embedder reads is title + context + chunk; none of it may fall past the cap."""
    title = "Notes from a year of pottery classes at the community studio downtown"
    context = (
        "This passage is from the final session of a year-long pottery course, where the "
        "teacher explains wedging clay to find trapped air before a piece is fired. It "
        "follows sections on throwing, trimming and glazing."
    )
    for piece in _pieces(" ".join(SENTENCES)):
        text = CHUNK_INDEX_TEXT_WITH_CONTEXT.format(title=title, context=context, text=piece)
        assert token_count(text) < config.EMBED_MAX_TOKENS - 2


def _insert_artifact(kind: str) -> str:
    aid = str(uuid.uuid4())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status, created_at,"
            " updated_at) VALUES (?, ?, 'Doc', NULL, ?, 'ok', ?, ?)",
            (aid, kind, aid, db.now(), db.now()),
        )
    return aid


def test_pages_for_pdf_chunks(store):
    aid = _insert_artifact("pdf")
    texts = ["## page 1\n\nalpha", "more of page one", "## page 2\n\nbeta"]
    with db.transaction() as conn:
        for i, text in enumerate(texts):
            conn.execute(
                "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker) VALUES (?,?,?,?,?)",
                (f"{aid}-{i}", aid, i, text, "test"),
            )
        out = chunk_mod.pages_for(conn, aid)
    assert [out[f"{aid}-{i}"] for i in range(3)] == [0, 0, 1]


def test_pages_for_non_pdf_is_empty(store):
    aid = _insert_artifact("note")
    with db.transaction() as conn:
        assert chunk_mod.pages_for(conn, aid) == {}


def test_quote_of_skips_headings_and_blank_lines():
    assert chunk_mod.quote_of("# Title\n\none two three") == "one two three"
