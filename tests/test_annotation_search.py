"""R.1: failing end-to-end reproductions of the Chopper bug.

An image was captured, and the text "tony tony chopper" was added as a note on
it. Searching "tony tony chopper" returns nothing. Searching "any one piece
character" returns nothing.

These tests encode that report exactly. They fail today for the two root causes
in GT.1: annotations are never indexed (chunk text is built only from artifact
bodies, page text, and link preview text), and an image whose vision describe
failed has zero searchable text.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest

from enqueue import config, db
from enqueue.index.store import get_store
from enqueue.retrieve.candidates import search_results

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def sqlite_store(store, monkeypatch):
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    yield s
    get_store.cache_clear()


class FakeVision:
    """A vision provider that answers without any model."""

    model = "fake-vision"

    def __init__(self, text: str):
        self._text = text

    def complete(self, *args, **kwargs):  # pragma: no cover - vision has no complete
        raise AssertionError("the vision provider is never asked for structured text")

    def describe_image(self, image: bytes, mime: str) -> str:
        return self._text


def _fake_vision(monkeypatch, text="A red bicycle leaning against a brick wall."):
    seen = {}

    def _provider(local_only=False):
        seen["local_only"] = local_only
        return FakeVision(text)

    from enqueue.providers import base as providers_base

    monkeypatch.setattr(providers_base, "get_vision_provider", _provider)
    return seen


def _broken_vision(monkeypatch):
    """The common case: a text-only backend with no vision model at all."""

    def _provider(local_only=False):
        raise Exception("no vision model named 'llava' on this backend")

    from enqueue.providers import base as providers_base

    monkeypatch.setattr(providers_base, "get_vision_provider", _provider)


def _quiet_derived(monkeypatch):
    """No facet/entity model calls; the real sqlite-vec store stays in place.

    The ingest pipeline generates facets and entities with a model call behind
    the response. These tests are about chunk-level search, so both steps are
    stubbed out; the store itself must stay real so `search_results` can search.
    """
    from enqueue.ingest import queue as ingest_queue

    monkeypatch.setattr(ingest_queue, "_facet_artifact", lambda aid: 0)
    monkeypatch.setattr(ingest_queue, "_entities_artifact", lambda aid: 0)


def _link(conn, aid: str) -> None:
    """A captured link: body NULL by the schema's own invariant (kind != 'note')."""
    conn.execute(
        "INSERT INTO artifacts (id, kind, title, body, content_hash, source_url, status,"
        " created_at, updated_at) VALUES (?, 'link', 'A link', NULL, ?,"
        " 'https://example.com/tony', 'ok', datetime('now'), datetime('now'))",
        (aid, aid + "_hash"),
    )


def _annotate(conn, aid: str, text: str) -> None:
    conn.execute(
        "INSERT INTO annotations (id, artifact_id, text, created_at) VALUES (?,?,?,"
        " datetime('now'))",
        (str(uuid.uuid4()), aid, text),
    )


def _image(monkeypatch, title="A capture") -> str:
    """An image artifact row plus its blob, bypassing the queue."""
    artifact_id = str(uuid.uuid4())
    data = PNG + artifact_id.encode()
    digest = hashlib.sha256(data).hexdigest()
    blob = config.BLOB_DIR / digest
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(data)
    now = "2024-01-01T00:00:00+00:00"
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, mime, filename,"
            " created_at, updated_at, status) VALUES (?, 'image', ?, NULL, ?, 'image/png',"
            " 'capture.png', ?, ?, 'text_only')",
            (artifact_id, title, digest, now, now),
        )
    return artifact_id


class TestChopperRepro:
    def test_annotation_text_is_searchable(self, sqlite_store, quiet_queue, monkeypatch):
        """An annotation on a link must make the link findable by that text."""
        from enqueue import preview as preview_mod
        from enqueue.ingest import queue as ingest_queue

        # The link has no body and no preview; a real fetch would be a network call.
        monkeypatch.setattr(preview_mod, "auto_enabled", lambda: False)
        _quiet_derived(monkeypatch)

        aid = str(uuid.uuid4())
        conn = db.get_conn()
        try:
            _link(conn, aid)
            _annotate(conn, aid, "tony tony chopper")
            conn.commit()
        finally:
            conn.close()

        ingest_queue.process(aid)

        hits = search_results("tony tony chopper")
        ids = [h["artifact_id"] for h in hits]
        assert aid in ids

    def test_vision_described_image_matches_conceptual_query(
        self, sqlite_store, quiet_queue, monkeypatch
    ):
        """A described image answers a conceptual query about what it shows."""
        from enqueue.ingest import queue as ingest_queue

        aid = _image(monkeypatch)
        _fake_vision(
            monkeypatch,
            "A Tony Tony Chopper plush figure from One Piece, a small reindeer with a pink hat",
        )
        _quiet_derived(monkeypatch)

        ingest_queue.process(aid)

        hits = search_results("one piece character")
        ids = [h["artifact_id"] for h in hits]
        assert aid in ids

    def test_image_without_body_and_annotation_only(self, sqlite_store, quiet_queue, monkeypatch):
        """An undescribed image annotated with a name stays findable by that name."""
        from enqueue.ingest import queue as ingest_queue

        aid = _image(monkeypatch)
        _broken_vision(monkeypatch)
        _quiet_derived(monkeypatch)
        conn = db.get_conn()
        try:
            _annotate(conn, aid, "tony tony chopper")
            conn.commit()
        finally:
            conn.close()

        ingest_queue.process(aid)

        hits = search_results("tony tony chopper")
        ids = [h["artifact_id"] for h in hits]
        assert aid in ids


class TestFuzzyTypo:
    def test_one_edit_typo_is_found_via_fuzzy(self, sqlite_store, quiet_queue, monkeypatch):
        """GT.1's typo: 'tony tony copper' is one edit off the annotation text.

        The trigram branch cannot see it (copper and chopper share too few
        trigrams), but the fuzzy branch matches the short annotation text at
        ratio >= FUZZY_RATIO and marks the hit why="fuzzy".
        """
        from enqueue.ingest import queue as ingest_queue

        aid = _image(monkeypatch)
        _broken_vision(monkeypatch)
        _quiet_derived(monkeypatch)
        conn = db.get_conn()
        try:
            _annotate(conn, aid, "tony tony chopper")
            conn.commit()
        finally:
            conn.close()

        ingest_queue.process(aid)

        hits = search_results("tony tony copper")
        row = next((h for h in hits if h["artifact_id"] == aid), None)
        assert row is not None, f"typo query should find the annotated image, got {hits}"
        assert row["why"] == "fuzzy"

    def test_unrelated_artifact_below_threshold_is_not_fuzzy(self, sqlite_store, monkeypatch):
        """A title with no real similarity stays below FUZZY_RATIO."""
        conn = db.get_conn()
        try:
            _link(conn, "unrelated")
            conn.execute(
                "UPDATE artifacts SET title = 'Field notes on tides' WHERE id = 'unrelated'"
            )
            conn.commit()
        finally:
            conn.close()

        from enqueue.retrieve.candidates import _fuzzy_hits

        fuzzy = _fuzzy_hits("tony tony copper", 20)
        assert all(h["artifact_id"] != "unrelated" for h in fuzzy)

    def test_fuzzy_ratio_typo_vs_far(self):
        """The ratio separates a one-edit typo from an unrelated string."""
        from enqueue.retrieve.candidates import _fuzzy_ratio

        assert _fuzzy_ratio("tony tony copper", "tony tony chopper") >= 0.75
        assert _fuzzy_ratio("tony tony copper", "field notes on tides") < 0.75


class TestAnnotateRequeues:
    def test_annotate_requeues_ingest(self, store, quiet_queue):
        """Writing an annotation re-queues the artifact so its chunks rebuild."""
        from enqueue import notes

        aid = str(uuid.uuid4())
        conn = db.get_conn()
        try:
            _link(conn, aid)
            conn.commit()
        finally:
            conn.close()

        notes.annotate(aid, "tony tony chopper")

        # quiet_queue is the submit spy: annotate must put the artifact back
        # through the ingest queue, or the new text never reaches the index.
        assert quiet_queue == [aid]

    def test_superseded_annotation_is_not_indexed(self, sqlite_store, quiet_queue, monkeypatch):
        """A superseded annotation stops describing the artifact: the new text is
        findable, the superseded text never reaches the index.

        The old-string search cannot assert zero hits on a small corpus: the dense
        branch returns the nearest neighbor for any query, so the artifact still
        appears. What R.2a guarantees is that the superseded text is not chunk
        source, so the assertion is on the index content, not on hit presence.
        """
        from enqueue import notes
        from enqueue.ingest import queue as ingest_queue

        aid = _image(monkeypatch)
        _broken_vision(monkeypatch)
        _quiet_derived(monkeypatch)

        first = notes.annotate(aid, "tony tony chopper")
        notes.annotate(aid, "chopper the reindeer", supersedes_id=first["id"])

        ingest_queue.process(aid)

        # The current annotation is indexed and searchable.
        hits = search_results("chopper the reindeer")
        assert aid in [h["artifact_id"] for h in hits]

        # The superseded text never reaches a chunk.
        conn = db.get_conn()
        try:
            rows = conn.execute("SELECT text FROM chunks WHERE artifact_id = ?", (aid,)).fetchall()
        finally:
            conn.close()
        assert rows, "the current annotation must produce at least one chunk"
        assert all("tony tony chopper" not in c["text"] for c in rows)


class TestDescribeFailure:
    def test_failed_describe_marks_artifact_failed(self, store, quiet_queue, monkeypatch):
        """A describe failure is surfaced, not swallowed: status becomes 'failed'."""
        from enqueue.ingest import queue as ingest_queue

        aid = _image(monkeypatch)
        _broken_vision(monkeypatch)
        _quiet_derived(monkeypatch)

        ingest_queue.process(aid)

        conn = db.get_conn()
        try:
            status = conn.execute("SELECT status FROM artifacts WHERE id = ?", (aid,)).fetchone()[
                "status"
            ]
        finally:
            conn.close()
        assert status == "failed"

    def test_bodyless_image_is_findable_by_its_name(self, sqlite_store, quiet_queue, monkeypatch):
        """An image with no body is still reachable through its title and filename."""
        from enqueue.ingest import queue as ingest_queue

        aid = _image(monkeypatch, title="chopper-plush.png")
        _broken_vision(monkeypatch)
        _quiet_derived(monkeypatch)

        ingest_queue.process(aid)

        hits = search_results("chopper plush")
        ids = [h["artifact_id"] for h in hits]
        assert aid in ids
