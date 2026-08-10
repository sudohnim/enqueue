"""Build the deterministic fixture database the search eval runs against.

The harness must be deterministic offline, so this seeds a fresh sqlite-vec
database at `evals/search/eval.db` (rebuilt on every run) with:

  - every note from `evals/corpus/` (artifact ids are the MANIFEST ids, so the
    queries in `evals/search/queries.json` reference real rows), and
  - the two Chopper-class needle artifacts:
      * `chopper_annotated_image`: an image whose vision describe failed (the
        common case on a text-only backend), carrying the annotation
        "tony tony chopper" as its only text, and
      * `chopper_described_image`: an image described by a fake vision provider
        as a One Piece plush figure.

Both images are routed through the real ingest pipeline with the vision
provider faked (the test_image_vision.py pattern), so the fixture exercises
the exact code path a capture would. The corpus notes are inserted directly
(the tests/test_search_results.py::_note pattern); chunking and indexing run
as one deterministic pass at the end.

Usage: uv run python scripts/seed_search_eval.py [db_path]
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

from enqueue import config

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "evals" / "corpus"
DEFAULT_DB = ROOT / "evals" / "search" / "eval.db"

FAKE_DESCRIPTION = (
    "A Tony Tony Chopper plush figure from One Piece, a small reindeer with a pink hat"
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class _FakeVision:
    """A vision provider that answers without any model."""

    model = "fake-vision"

    def __init__(self, text: str):
        self._text = text

    def describe_image(self, image: bytes, mime: str) -> str:
        return self._text


def _fake_vision_provider(local_only: bool = False) -> _FakeVision:
    return _FakeVision(FAKE_DESCRIPTION)


def _insert_note(conn, aid: str, title: str, body: str) -> None:
    conn.execute(
        "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
        " created_at, updated_at) VALUES (?, 'note', ?, ?, ?, 'ok',"
        " datetime('now'), datetime('now'))",
        (aid, title, body, aid + "_hash"),
    )


def _insert_image(conn, aid: str) -> None:
    conn.execute(
        "INSERT INTO artifacts (id, kind, title, body, content_hash, mime, filename,"
        " created_at, updated_at, status) VALUES (?, 'image', 'A capture', NULL, ?,"
        " 'image/png', 'capture.png', datetime('now'), datetime('now'), 'text_only')",
        (aid, aid + "_hash"),
    )


def _annotate(conn, aid: str, text: str) -> None:
    conn.execute(
        "INSERT INTO annotations (id, artifact_id, text, created_at) VALUES (?,?,?,"
        " datetime('now'))",
        (str(uuid.uuid4()), aid, text),
    )


def _write_blob(aid: str) -> str:
    """The image bytes live at blobs/<content_hash>; returns the hash."""
    data = PNG + aid.encode()
    digest = hashlib.sha256(data).hexdigest()
    blob = config.BLOB_DIR / digest
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(data)
    return digest


def seed(db_path: Path) -> Path:
    """Rebuild the fixture database at db_path and return it."""
    from enqueue import config, db
    from enqueue.index.store import get_store
    from enqueue.ingest import chunk as chunk_mod
    from enqueue.ingest import queue as ingest_queue
    from enqueue.notes import title_from_body
    from enqueue.providers import base as providers_base

    if db_path.exists():
        db_path.unlink()

    config.DATA_DIR = db_path.parent
    config.DB_PATH = db_path
    config.BLOB_DIR = db_path.parent / "blobs"
    config.VECTOR_STORE = "sqlite-vec"
    db.reset_migration_state()
    db.migrate()
    get_store.cache_clear()
    store = get_store()
    store.ensure()

    # The corpus notes, inserted directly with the MANIFEST ids as artifact ids.
    try:
        manifest = json.loads((CORPUS / "MANIFEST.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise SystemExit(f"corpus manifest missing or corrupt: {exc}") from exc
    with db.transaction() as conn:
        for entry in manifest["artifacts"]:
            body = (CORPUS / entry["filename"]).read_text()
            _insert_note(conn, entry["id"], title_from_body(body), body)

    # The two needle images: body NULL, blobs on disk, annotation on the
    # annotated one. The ingest pipeline describes/indexes them below.
    annotated = "chopper_annotated_image"
    described = "chopper_described_image"
    with db.transaction() as conn:
        for aid in (annotated, described):
            _insert_image(conn, aid)
            _write_blob(aid)
        _annotate(conn, annotated, "tony tony chopper")

    # Facet/entity generation is a model call; the harness is about chunk
    # retrieval, so both steps are stubbed like the tests do.
    ingest_queue._facet_artifact = lambda aid: 0
    ingest_queue._entities_artifact = lambda aid: 0

    # The described image: the fake vision provider answers.
    providers_base.get_vision_provider = _fake_vision_provider
    ingest_queue.process(described)

    # The annotated image: the common production case, a text-only backend
    # with no vision model. The failure is surfaced (status 'failed'), and
    # the annotation text is its only chunk source.
    def _broken(local_only=False):
        raise RuntimeError("no vision model named 'llava' on this backend")

    providers_base.get_vision_provider = _broken
    ingest_queue.process(annotated)

    # One deterministic pass over everything: re-chunk from the source tables
    # (bodies, previews, page text, and annotations) and rebuild the index.
    with db.transaction() as conn:
        chunk_mod.chunk_all()
    store.upsert_chunks()

    return db_path


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    print(f"seeded {seed(path)}")
