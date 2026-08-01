"""score_all: one entry per artifact, no model calls, zero when unmatched.

The stage-one contract: every non-deleted artifact appears in the result, an
artifact with no hit scores zero rather than being omitted, and nothing in
this stage calls a language model.
"""

from __future__ import annotations

import pytest

from enqueue import db, notes
from enqueue.index.store import get_store
from enqueue.ingest import chunk as chunk_mod
from enqueue.retrieve import score


@pytest.fixture
def scored_store(store):
    """An isolated vector store for one test."""
    get_store.cache_clear()
    s = get_store()
    s.ensure()  # both collections, so a facets search does not 404
    return s


def _chunk_and_index(store, artifact_id: str) -> None:
    conn = db.get_conn()
    try:
        chunk_mod.chunk_artifact(conn, artifact_id)
        conn.commit()
    finally:
        conn.close()
    store.upsert_chunks()


class TestScoreAll:
    def test_every_artifact_has_exactly_one_entry(self, store, quiet_queue, scored_store):
        a = notes.create("Hydroponics feeds the city from a rooftop.")
        b = notes.create("A joint that moves outlasts one that does not.")
        c = notes.create("The commons is what we share.")

        for note in (a, b, c):
            _chunk_and_index(scored_store, note["artifact"]["id"])

        scores = score.score_all("growing food without soil")

        assert set(scores) == {a["artifact"]["id"], b["artifact"]["id"], c["artifact"]["id"]}
        # hydroponics scores above zero on this lens
        assert scores[a["artifact"]["id"]] > 0
        assert len(scores) == 3

    def test_trashed_artifacts_are_excluded(self, store, quiet_queue, scored_store):
        from enqueue import trash

        note = notes.create("A joint that moves outlasts one that does not.")
        _chunk_and_index(scored_store, note["artifact"]["id"])

        trash.delete(note["artifact"]["id"])

        scores = score.score_all("joints")
        assert note["artifact"]["id"] not in scores

    def test_no_model_calls(self, store, quiet_queue, scored_store, monkeypatch):
        # score_all must never reach a provider: the stage is required to be
        # instant, and a model call would make it seconds per lens.
        def explode(*a, **k):
            raise AssertionError("score_all must not call a language model")

        monkeypatch.setattr("enqueue.providers.base.get_provider", explode)

        note = notes.create("Hydroponics feeds the city from a rooftop.")
        _chunk_and_index(scored_store, note["artifact"]["id"])

        scores = score.score_all("hydroponics")
        assert scores[note["artifact"]["id"]] > 0.0

    def test_zero_is_a_score_not_an_absence(self, store, quiet_queue, scored_store):
        chunked = notes.create("Hydroponics feeds the city from a rooftop.")
        _chunk_and_index(scored_store, chunked["artifact"]["id"])
        # Never chunked: not part of the search space at all.
        unchunked = notes.create("The boxer's advantage is patience.")

        scores = score.score_all("quantum flux capacitor")

        # Both artifacts appear, one entry each, even though the unchunked one
        # was never searched. Its entry is exactly zero, not an omission.
        assert set(scores) == {chunked["artifact"]["id"], unchunked["artifact"]["id"]}
        assert scores[unchunked["artifact"]["id"]] == 0.0
