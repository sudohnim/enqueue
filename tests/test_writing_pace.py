"""A note being written is saved at every pause; drafts and summaries keep a slower clock.

One draft per save buried the drafts worth going back to (149 of one note), and one
summary per save spent 56 model calls in ten minutes of writing. Every save still
lands in the note and is indexed for search at once.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from enqueue import config, db, notes
from enqueue.ingest import queue as q

T0 = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)


def _at(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


def _drafts(artifact_id: str) -> list[str]:
    conn = db.get_conn()
    try:
        return [
            r["body"]
            for r in conn.execute(
                "SELECT body FROM artifact_versions WHERE artifact_id = ? ORDER BY created_at",
                (artifact_id,),
            )
        ]
    finally:
        conn.close()


@pytest.fixture
def slow_drafts(store, quiet_queue, monkeypatch):
    monkeypatch.setattr(config, "DRAFT_EVERY_S", 300)


class TestDrafts:
    def _note(self) -> str:
        aid = notes.create(body="first")["artifact"]["id"]
        with db.transaction() as conn:  # written yesterday
            conn.execute(
                "UPDATE artifact_versions SET created_at = ? WHERE artifact_id = ?",
                ((T0 - timedelta(days=1)).isoformat(), aid),
            )
        return aid

    def _save(self, aid: str, body: str, seconds: float) -> None:
        with db.transaction() as conn:
            notes._append_version(conn, aid, body, _at(seconds))

    def test_a_stretch_of_writing_keeps_its_start_and_its_latest(self, slow_drafts):
        aid = self._note()

        for n, seconds in enumerate([0, 2, 5, 9, 14, 60, 200]):
            self._save(aid, f"typing {n}", seconds)

        assert _drafts(aid) == ["first", "typing 0", "typing 6"]

    def test_a_draft_is_left_standing_every_interval(self, slow_drafts):
        aid = self._note()

        for seconds in range(0, 16 * 60, 30):  # sixteen minutes, a save every 30s
            self._save(aid, f"at {seconds}", seconds)

        kept = _drafts(aid)
        assert kept[0] == "first" and kept[1] == "at 0" and kept[-1] == "at 930"
        assert len(kept) == 6, kept  # yesterday, the start, then one per five minutes

    def test_an_accidental_deletion_is_never_far_from_a_whole_draft(self, slow_drafts):
        aid = self._note()
        self._save(aid, "a long paragraph", 0)
        self._save(aid, "a long paragraph, more", 100)

        self._save(aid, "", 130)  # select all, delete, pause

        assert "a long paragraph" in _drafts(aid)

    def test_coming_back_later_starts_a_new_draft(self, slow_drafts):
        aid = self._note()
        self._save(aid, "morning", 0)
        self._save(aid, "morning, more", 20)

        self._save(aid, "evening", 8 * 3600)

        assert _drafts(aid) == ["first", "morning", "morning, more", "evening"]

    def test_editing_through_the_api_follows_the_same_clock(self, slow_drafts):
        aid = notes.create(body="one")["artifact"]["id"]

        for body in ("one two", "one two three", "one two three four"):
            notes.edit(aid, body)

        # Created a moment ago, so the note as created is this stretch's start.
        assert _drafts(aid) == ["one", "one two three four"]
        assert notes.get(aid)["artifact"]["body"] == "one two three four"


class _Model:
    """Counts what the ingest model is asked, and answers nothing useful."""

    model = "test-model"
    base_url = "http://127.0.0.1:11434/v1"

    def __init__(self):
        self.calls = 0

    def complete(self, *a, **k):
        self.calls += 1
        raise RuntimeError("no model in this test")


class TestSummaryWaitsForQuiet:
    BODY = "Kilns fire clay at cone six. " * 30

    @pytest.fixture
    def model(self, store, quiet_queue, monkeypatch):
        from enqueue.index.store import get_store
        from enqueue.ingest import context, entities, facets, source
        from enqueue.providers import base

        monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
        get_store.cache_clear()
        get_store().ensure()
        fake = _Model()
        for module in (facets, entities, context, source, base):
            monkeypatch.setattr(module, "get_provider", lambda *a, **k: fake, raising=False)
        monkeypatch.setattr(config, "SUMMARY_QUIET_S", 300)
        yield fake
        get_store.cache_clear()

    def _retry(self, aid: str):
        conn = db.get_conn()
        try:
            return conn.execute(
                "SELECT next_at, last_error FROM facet_retry WHERE artifact_id = ?", (aid,)
            ).fetchone()
        finally:
            conn.close()

    def test_a_note_just_edited_is_indexed_but_not_read_by_the_model(self, model):
        aid = notes.create(body=self.BODY)["artifact"]["id"]

        result = q.process(aid)

        assert result["chunks"] >= 1, "the words are searchable at once"
        assert model.calls == 0
        owed = self._retry(aid)
        assert owed["last_error"] == q.WAITING
        due = datetime.fromisoformat(owed["next_at"])
        assert timedelta(seconds=240) < due - datetime.now(timezone.utc) <= timedelta(seconds=300)
        assert notes.get(aid)["summary_waiting"] is True

    def test_once_it_has_been_left_alone_the_model_reads_it(self, model):
        aid = notes.create(body=self.BODY)["artifact"]["id"]
        q.process(aid)
        with db.transaction() as conn:  # six minutes pass
            conn.execute(
                "UPDATE artifact_versions SET created_at = ? WHERE artifact_id = ?",
                ((datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat(), aid),
            )

        q.process(aid)

        assert model.calls >= 1

    def test_an_edit_while_waiting_moves_the_wait(self, model):
        aid = notes.create(body=self.BODY)["artifact"]["id"]
        q.process(aid)
        with db.transaction() as conn:
            conn.execute(
                "UPDATE facet_retry SET next_at = ? WHERE artifact_id = ?",
                ((datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(), aid),
            )

        notes.edit(aid, self.BODY + " And a slow cool.")
        q.process(aid)

        assert model.calls == 0
        assert datetime.fromisoformat(self._retry(aid)["next_at"]) > datetime.now(timezone.utc)

    def test_asking_for_a_summary_is_not_made_to_wait(self, model):
        from enqueue.ingest import facets

        aid = notes.create(body=self.BODY)["artifact"]["id"]
        facets.force(aid)

        q.process(aid)

        assert model.calls >= 1

    def test_a_capture_is_never_made_to_wait(self, model):
        from enqueue import capture

        aid = capture.link("https://example.com/kilns-and-cones")["id"]

        assert q._wait_for_quiet(aid) is False
