"""Entities: extraction, enrichment, and the per-artifact index.

The entity layer closes the vocabulary gap from the name side: "notes on
presidents" reaches a Roosevelt biography that never says "president" because
the biography's names were enriched into one-line world-knowledge facts that
are indexed like facets. These tests prove the generation discipline (one bad
entity never fails the artifact, regen replaces rows, the fact must name the
entity) and the index path (rows land in vec + fts tables, drop removes them).

The provider is scripted exactly like the derive/fields tests: the module's
lazy `providers.base.get_provider` binding is replaced (patching the entities
module itself silently fails, because `generate_for_artifact` imports the
function lazily at call time), so no real model call ever happens.
"""

from __future__ import annotations

import pytest

from enqueue import db, notes
from enqueue.ingest import entities as entities_mod

ROOSEVELT = "Theodore Roosevelt - 26th US President, known for trust-busting."
CURIE = "Marie Curie - physicist and chemist who pioneered radioactivity research."
WAR = "World War II - global conflict from 1939 to 1945, the deadliest in history."


class _FakeProvider:
    """A scripted provider: one reply per call, or a queue of replies.

    The first call is the extraction (a `_RawEntitySet`), every later call is
    an enrichment (a `_RawFact`), which is exactly the order
    `generate_for_artifact` makes.
    """

    name = "fake"
    model = "fake-model"

    def __init__(self, script):
        self.script = script
        self.calls = 0

    def complete(self, system, user, response_model, context=None, max_retries=None):
        self.calls += 1
        reply = self.script.pop(0) if isinstance(self.script, list) else self.script
        if isinstance(reply, Exception):
            raise reply
        return response_model(**reply)


def _patch_provider(monkeypatch, script):
    import enqueue.providers.base as base_mod

    provider = _FakeProvider(script)
    monkeypatch.setattr(base_mod, "get_provider", lambda **kw: provider)
    return provider


def _generate(aid):
    """Run generation the way the queue does: one connection, then commit."""
    conn = db.get_conn()
    try:
        return entities_mod.generate_for_artifact(conn, aid)
    finally:
        conn.commit()
        conn.close()


def _entities(conn, aid):
    return conn.execute(
        "SELECT entity, fact, model_version, body_version FROM entities"
        " WHERE artifact_id = ? ORDER BY entity",
        (aid,),
    ).fetchall()


@pytest.fixture
def sqlite_store(store, monkeypatch):
    """The real sqlite-vec store against the per-test database."""
    from enqueue import config
    from enqueue.index.store import get_store

    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    yield s
    get_store.cache_clear()


@pytest.fixture(autouse=True)
def _no_real_judge(monkeypatch):
    """Retrieval tests here assert the entity/facet ladder, not the gray-zone
    judge. Stub it fail-open (keep everything) exactly as test_chats.py and
    test_search_results.py do, so a gray-zone hit never waits on the real local
    model and a verdict can never make a ladder test flake."""
    from enqueue.retrieve import candidates as cand

    class _KeepAllJudge:
        model = "test-judge"

        def complete(self, *args, **kwargs):
            return cand._GrayZoneResponse(verdicts=[])

    monkeypatch.setattr(cand, "get_provider", lambda *a, **k: _KeepAllJudge())


class TestExtraction:
    def test_extracts_and_enriches(self, store, monkeypatch):
        aid = notes.create(body="The words of Theodore Roosevelt on grit.")["artifact"]["id"]
        provider = _patch_provider(
            monkeypatch,
            [
                {"entities": [{"name": "Theodore Roosevelt"}, {"name": "Marie Curie"}]},
                {"fact": ROOSEVELT},
                {"fact": CURIE},
            ],
        )

        count, error = _generate(aid)

        assert error is None
        assert count == 2
        assert provider.calls == 3  # one extraction, one enrich per entity
        conn = db.get_conn()
        rows = _entities(conn, aid)
        conn.close()
        assert [r["entity"] for r in rows] == ["Marie Curie", "Theodore Roosevelt"]
        assert [r["fact"] for r in rows] == [CURIE, ROOSEVELT]
        assert all(r["model_version"] == "fake-model" for r in rows)

    def test_body_version_travels_with_the_rows(self, store, monkeypatch):
        aid = notes.create(body="A note about Marie Curie and radium.")["artifact"]["id"]
        conn = db.get_conn()
        version = conn.execute(
            "SELECT MAX(created_at) AS v FROM artifact_versions WHERE artifact_id = ?", (aid,)
        ).fetchone()["v"]
        conn.close()
        _patch_provider(
            monkeypatch,
            [
                {"entities": [{"name": "Marie Curie"}]},
                {"fact": CURIE},
            ],
        )

        _generate(aid)

        conn = db.get_conn()
        row = _entities(conn, aid)[0]
        conn.close()
        assert row["body_version"] == version

    def test_one_bad_entity_never_fails_the_artifact(self, store, monkeypatch):
        aid = notes.create(body="Roosevelt and Curie both left a mark.")["artifact"]["id"]
        _patch_provider(
            monkeypatch,
            [
                {"entities": [{"name": "Theodore Roosevelt"}, {"name": "Marie Curie"}]},
                RuntimeError("model down"),
                {"fact": CURIE},
            ],
        )

        count, error = _generate(aid)

        assert error is None
        assert count == 1
        conn = db.get_conn()
        rows = _entities(conn, aid)
        conn.close()
        assert [r["entity"] for r in rows] == ["Marie Curie"]

    def test_quality_gate_drops_weak_lines(self, store, monkeypatch):
        aid = notes.create(body="Roosevelt, Curie, and the war.")["artifact"]["id"]
        _patch_provider(
            monkeypatch,
            [
                {
                    "entities": [
                        {"name": "Theodore Roosevelt"},
                        {"name": "Marie Curie"},
                        {"name": "World War II"},
                    ]
                },
                # Fact that never names the entity: cannot bridge the gap.
                {"fact": "A famous president who led reforms in the early 1900s."},
                # Too short, and no period.
                {"fact": "Curie!"},
                {"fact": WAR},
            ],
        )

        count, error = _generate(aid)

        assert error is None
        assert count == 1
        conn = db.get_conn()
        rows = _entities(conn, aid)
        conn.close()
        assert [r["entity"] for r in rows] == ["World War II"]

    def test_unknown_entity_is_dropped(self, store, monkeypatch):
        aid = notes.create(body="Something about Roosevelt.")["artifact"]["id"]
        _patch_provider(
            monkeypatch,
            [
                {"entities": [{"name": "Theodore Roosevelt"}]},
                {"fact": ""},  # the model does not know the entity
            ],
        )

        count, error = _generate(aid)

        assert error is not None
        assert count == 0

    def test_extraction_failure_writes_nothing(self, store, monkeypatch):
        aid = notes.create(body="Roosevelt and Curie.")["artifact"]["id"]
        _patch_provider(monkeypatch, [RuntimeError("provider down")])

        count, error = _generate(aid)

        assert count == 0
        assert error
        conn = db.get_conn()
        rows = _entities(conn, aid)
        conn.close()
        assert rows == []

    def test_regen_replaces_rows(self, store, monkeypatch):
        aid = notes.create(body="About Roosevelt and Curie.")["artifact"]["id"]
        _patch_provider(
            monkeypatch,
            [
                {"entities": [{"name": "Theodore Roosevelt"}, {"name": "Marie Curie"}]},
                {"fact": ROOSEVELT},
                {"fact": CURIE},
            ],
        )
        _generate(aid)

        _patch_provider(
            monkeypatch,
            [
                {"entities": [{"name": "Marie Curie"}]},
                {"fact": CURIE},
            ],
        )
        count, error = _generate(aid)

        assert error is None
        assert count == 1
        conn = db.get_conn()
        rows = _entities(conn, aid)
        conn.close()
        assert [r["entity"] for r in rows] == ["Marie Curie"]

    def test_entity_count_is_capped(self, store, monkeypatch):
        aid = notes.create(body="Many names in this text.")["artifact"]["id"]
        names = [{"name": f"Person {i}"} for i in range(12)]
        facts = [{"fact": f"Person {i} - a notable figure from history books."} for i in range(12)]
        _patch_provider(monkeypatch, [{"entities": names}, *facts])

        count, error = _generate(aid)

        assert error is None
        assert count == entities_mod.MAX_ENTITIES


class TestQueueHook:
    def test_entities_artifact_writes_and_indexes(self, store, quiet_queue, monkeypatch):
        # quiet_queue: this test calls the hook directly, and a real submit would
        # let the live worker thread race it and consume the scripted provider.
        from enqueue.ingest import queue

        aid = notes.create(body="The words of Theodore Roosevelt on grit.")["artifact"]["id"]
        indexed = []
        import enqueue.index.store as store_mod

        monkeypatch.setattr(
            store_mod,
            "get_store",
            lambda: type("S", (), {"index_entities_artifact": indexed.append})(),
        )
        _patch_provider(
            monkeypatch,
            [
                {"entities": [{"name": "Theodore Roosevelt"}]},
                {"fact": ROOSEVELT},
            ],
        )

        made = queue._entities_artifact(aid)

        assert made == 1
        assert indexed == [aid]

    def test_gated_artifact_makes_no_call(self, store, quiet_queue, monkeypatch):
        from enqueue.ingest import queue

        aid = notes.create(body="A long enough note body to be eligible for entity work.")[
            "artifact"
        ]["id"]
        conn = db.get_conn()
        conn.execute(
            "INSERT INTO facet_skips (artifact_id, reason) VALUES (?, 'text_only')", (aid,)
        )
        conn.commit()
        conn.close()

        def _boom(*a, **k):
            raise AssertionError("provider must not be called for a gated artifact")

        import enqueue.providers.base as base_mod

        monkeypatch.setattr(base_mod, "get_provider", _boom)

        assert queue._entities_artifact(aid) == 0

    def test_process_reports_entities_and_indexes_them(self, store, sqlite_store, monkeypatch):
        """The full queue path: note to chunks to indexed entity rows.

        The facet call runs first and is scripted to fail (facets swallow that), so
        the script's real payload goes to the entity extraction and enrichment.
        """
        from enqueue.ingest import queue

        conn = db.get_conn()
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
            " created_at, updated_at) VALUES ('e2e', 'note', 'Grit notes',"
            " 'The words of Theodore Roosevelt on grit and perseverance in hard times.'"
            " , 'e2e-hash', 'ok', datetime('now'), datetime('now'))",
        )
        conn.commit()
        conn.close()
        _patch_provider(
            monkeypatch,
            [
                RuntimeError("facet generation down"),
                {"entities": [{"name": "Theodore Roosevelt"}]},
                {"fact": ROOSEVELT},
            ],
        )

        result = queue.process("e2e")

        assert result["chunks"] > 0
        assert result["entities"] == 1
        assert sqlite_store.counts()["entities"] == 1


class TestRetrieval:
    """The I3 payoff: a question in the world's vocabulary reaches an artifact
    that never uses it, through its enriched entity line."""

    BIO_CHUNK = "The recipe calls for three cups of flour and a pinch of salt."

    def _seed(self, store, body_version=None, model_version="fake-model"):
        conn = db.get_conn()
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
            " created_at, updated_at) VALUES ('bio', 'note', 'Roosevelt biography',"
            " 'The man hunted and wrote and built.' , 'bio-hash', 'ok',"
            " datetime('now'), datetime('now'))",
        )
        conn.execute(
            "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker)"
            " VALUES ('bio-chunk', 'bio', 0, ?, 'test')",
            (self.BIO_CHUNK,),
        )
        conn.execute(
            "INSERT INTO entities (id, artifact_id, entity, fact, model_version,"
            " body_version, trust) VALUES ('bio-ent', 'bio', 'Theodore Roosevelt',"
            " ?, ?, ?, 0.5)",
            (ROOSEVELT, model_version, body_version),
        )
        conn.commit()
        conn.close()
        return "bio"

    def _patch_model(self, monkeypatch):
        """Make the retrieval staleness check see the seeded model version."""
        import enqueue.providers.base as base_mod

        fake = type("P", (), {"model": "fake-model", "name": "fake"})()
        monkeypatch.setattr(base_mod, "get_provider", lambda **kw: fake)

    def test_search_results_reaches_a_biography_that_never_says_president(
        self, store, sqlite_store, monkeypatch
    ):
        aid = self._seed(store)
        sqlite_store.index_entities_artifact(aid)
        self._patch_model(monkeypatch)

        from enqueue.retrieve.candidates import search_results

        out = search_results("presidents", limit=10)

        assert any(r["artifact_id"] == aid for r in out)
        row = next(r for r in out if r["artifact_id"] == aid)
        assert row["why"] == "entity"
        assert "President" in row["snippet"]

    def test_without_entity_line_the_biography_is_unreachable(self, store, sqlite_store):
        aid = self._seed(store)
        # Chunk and entity table rows exist, but nothing is indexed: no entity line
        # bridges "presidents".
        from enqueue.retrieve.candidates import search_results

        out = search_results("presidents", limit=10)

        assert not any(r["artifact_id"] == aid for r in out)

    def test_candidates_surfaces_the_artifact_via_entity(self, store, sqlite_store, monkeypatch):
        aid = self._seed(store)
        sqlite_store.index_entities_artifact(aid)
        self._patch_model(monkeypatch)

        from enqueue.retrieve.candidates import candidates

        out = candidates(["presidents"], limit=10)

        assert any(c["artifact_id"] == aid for c in out)
        row = next(c for c in out if c["artifact_id"] == aid)
        assert row["why"] == "entity"

    def test_stale_entity_line_never_wins_a_slot(self, store, sqlite_store, monkeypatch):
        # A line written by an older model than the running one is dropped, the
        # same provenance discipline as facets.
        aid = self._seed(store, model_version="old-model")
        sqlite_store.index_entities_artifact(aid)
        self._patch_model(monkeypatch)

        from enqueue.retrieve.candidates import candidates

        out = candidates(["presidents"], limit=10)

        assert not any(c["artifact_id"] == aid for c in out)

    def test_chats_passages_reach_the_biography_via_entity(self, store, sqlite_store, monkeypatch):
        aid = self._seed(store)
        sqlite_store.index_entities_artifact(aid)
        self._patch_model(monkeypatch)

        from enqueue.chats import passages

        out = passages("presidents", "library", None)

        assert any(r["id"] == "bio-chunk" for r in out)
        assert any(r["why"] == "entity" for r in out)


class TestIndex:
    def _seed(self, store):
        conn = db.get_conn()
        aid = notes.create(body="About Theodore Roosevelt and Marie Curie.")["artifact"]["id"]
        conn.execute(
            "INSERT INTO entities (id, artifact_id, entity, fact, model_version,"
            " body_version, trust) VALUES ('entity-1', ?, ?, ?, 'fake-model', NULL, 0.5)",
            (aid, "Theodore Roosevelt", ROOSEVELT),
        )
        conn.commit()
        conn.close()
        return aid

    def test_index_entities_artifact_lands_in_both_tables(self, store, sqlite_store):
        aid = self._seed(store)

        n = sqlite_store.index_entities_artifact(aid)

        assert n == 1
        counts = sqlite_store.counts()
        assert counts["entities"] == 1
        assert counts["fts_entities"] == 1

    def test_keyword_search_finds_a_fact_line(self, store, sqlite_store):
        aid = self._seed(store)
        sqlite_store.index_entities_artifact(aid)

        hits = sqlite_store._search_keyword(sqlite_store.ENTITIES, "President", limit=5)

        assert any(h["entity_id"] == "entity-1" for h in hits)

    def test_drop_artifact_removes_entity_rows(self, store, sqlite_store):
        aid = self._seed(store)
        sqlite_store.index_entities_artifact(aid)

        sqlite_store.drop_artifact(sqlite_store.ENTITIES, aid)

        counts = sqlite_store.counts()
        assert counts["entities"] == 0
        assert counts["fts_entities"] == 0

    def test_upsert_entities_rebuilds_collection(self, store, sqlite_store):
        self._seed(store)

        result = sqlite_store.upsert_entities()

        assert result["indexed"] == 1
        assert result["collection"] == sqlite_store.ENTITIES
