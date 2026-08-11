"""The /search rollup: one row per artifact, chunk + facet fusion.

Phase 22. Search used to return raw chunk hits, so six chunks of one note
occupied six result slots and a facet-only match had no row at all. The
rollup turns chunk and facet hits into one ranked row per artifact (an
artifact cannot occupy every slot), and the /doctor gate means the endpoint
is only reachable when the index is current.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from enqueue import config, db
from enqueue.api import app
from enqueue.index import bootstrap
from enqueue.index.store import get_store
from enqueue.index.store_sqlite import _trigram_query
from enqueue.retrieve.candidates import search_results

_BODY = "A city can feed itself from its rooftops, one tray of greens at a time."
_UNRELATED = "The ziggurat of Ur stood in the desert, season after season."


@pytest.fixture
def sqlite_store(store, monkeypatch):
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    yield s
    get_store.cache_clear()


def _note(conn, aid, title, body):
    conn.execute(
        "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
        " created_at, updated_at) VALUES (?, 'note', ?, ?, ?, 'ok',"
        " datetime('now'), datetime('now'))",
        (aid, title, body, aid + "_hash"),
    )


def _chunk(conn, cid, aid, ordinal, text):
    conn.execute(
        "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker)"
        " VALUES (?, ?, ?, ?, 'test')",
        (cid, aid, ordinal, text),
    )


def _facet(conn, fid, aid, level, statement, trust, model_version="test-model"):
    conn.execute(
        "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (fid, aid, level, statement, model_version, trust),
    )


class TestDedup:
    def test_six_chunks_of_one_artifact_return_it_once(self, sqlite_store):
        # One artifact whose six chunks all match the query; a second that
        # does not. The rollup must emit a1 exactly once, ranked first.
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            for i in range(6):
                _chunk(conn, f"c{i}", "a1", i, _BODY)
            _note(conn, "a2", "The Ur dig", _UNRELATED)
            _chunk(conn, "c9", "a2", 0, _UNRELATED)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("rooftops", limit=20)
        ids = [h["artifact_id"] for h in hits]
        assert ids.count("a1") == 1, f"a1 appeared {ids.count('a1')} times: {ids}"
        assert ids[0] == "a1"
        assert hits[0]["why"] == "chunk"
        assert "rooftops" in hits[0]["snippet"].lower()

    def test_snippet_comes_from_the_best_chunk(self, sqlite_store):
        # The winning chunk's own text is the snippet, not a shorter chunk.
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            _chunk(conn, "c1", "a1", 0, _BODY)
            _chunk(
                conn,
                "c2",
                "a1",
                1,
                "Rooftops and rooftops and rooftops: the city grows its greens above the street.",
            )
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("rooftops", limit=20)
        assert hits[0]["artifact_id"] == "a1"
        assert "street" in hits[0]["snippet"].lower()


class TestFusion:
    def test_facet_only_match_still_returns_a_row(self, sqlite_store):
        # a2's chunks never mention the query, but its facet does: the facet
        # hit must surface the artifact, not disappear in the rollup.
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            _chunk(conn, "c1", "a1", 0, _BODY)
            _note(
                conn,
                "a2",
                "Trade routes",
                "Goods moved along the river, season by season.",
            )
            _chunk(conn, "c2", "a2", 0, "Goods moved along the river, season by season.")
            _facet(conn, "f1", "a2", 3, "Ziggurats rose above the mud-brick cities.", 0.9)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()
        sqlite_store.upsert_facets()

        # The /search rollup now drops a facet written by an older model the way
        # the candidates path always did (I2.3); seed the facet with the running
        # model so it proves a current facet-only match still surfaces.
        from enqueue.providers.base import get_provider

        conn = db.get_conn()
        try:
            conn.execute(
                "UPDATE facets SET model_version = ? WHERE id = 'f1'",
                (get_provider(local_only=False).model,),
            )
            conn.commit()
        finally:
            conn.close()

        hits = search_results("ziggurat", limit=20)
        a2 = [h for h in hits if h["artifact_id"] == "a2"]
        assert a2, "a facet-only match must not vanish from search results"
        assert a2[0]["why"].startswith("facet")
        # Facet-only rows show the artifact face, not a chunk.
        assert "river" in a2[0]["snippet"].lower()


class TestSearchEndpoint:
    def test_endpoint_returns_deduplicated_rows(self, sqlite_store):
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            for i in range(6):
                _chunk(conn, f"c{i}", "a1", i, _BODY)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()
        # The /search gate: the index must be current before it answers.
        assert bootstrap.ensure_index()

        with TestClient(app) as client:
            resp = client.get("/search", params={"q": "rooftops"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "rooftops"
        ids = [h["artifact_id"] for h in body["hits"]]
        assert ids.count("a1") == 1

    def test_empty_query_returns_everything(self, sqlite_store):
        # An empty query means "everything", newest touch first. The embedding
        # store cannot answer an empty vector, and a request to group the whole
        # library plans into search(""), so the empty query reads the library
        # directly instead of crashing (or matching nothing).
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            _note(conn, "a2", "The ziggurat", _UNRELATED)
            conn.commit()
        finally:
            conn.close()

        hits = search_results("")

        assert {h["artifact_id"] for h in hits} == {"a1", "a2"}
        assert all(h["why"] == "all" for h in hits)


class TestTitleWeight:
    def test_title_match_outranks_body_match(self, sqlite_store):
        # The Chopper bug: "tony tony chopper" only found the note whose body
        # mentioned the name, because the keyword index had no separate title
        # column and bm25 could not weight it. Here a1's title is the match,
        # a2's body is; the title must win.
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Tony Tony Chopper", _UNRELATED)
            _chunk(conn, "c1", "a1", 0, _UNRELATED)
            _note(conn, "a2", "Field notes", "tony tony chopper appears once in the body.")
            _chunk(conn, "c2", "a2", 0, "tony tony chopper appears once in the body.")
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("tony tony chopper", limit=20)
        ids = [h["artifact_id"] for h in hits]
        assert ids[0] == "a1", f"title match should rank first, got {ids}"
        assert "a2" in ids


class TestTrigramRecall:
    def test_prefix_query_finds_chunk(self, sqlite_store):
        # "tony chopp" is a prefix of "chopper". unicode61 with the prefix
        # star already covers this; the trigram branch must not disturb it.
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Field notes", "tony tony chopper appears once in the body.")
            _chunk(conn, "c1", "a1", 0, "tony tony chopper appears once in the body.")
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("tony chopp", limit=20)
        ids = [h["artifact_id"] for h in hits]
        assert "a1" in ids

    def test_infix_query_finds_chunk(self, sqlite_store):
        # The trigram branch exists for substrings unicode61 cannot see:
        # "hopper" sits inside "chopper", and no unicode61 prefix star can
        # match the middle of a word. Only trigram tokens (hop/opp/ppe/per)
        # see it, so this test fails without the branch.
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Field notes", "tony tony chopper appears once in the body.")
            _chunk(conn, "c1", "a1", 0, "tony tony chopper appears once in the body.")
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("hopper", limit=20)
        ids = [h["artifact_id"] for h in hits]
        assert "a1" in ids

    def test_two_char_query_skips_trigram_branch(self, sqlite_store):
        # Tokens under three characters cannot form a trigram, so the query
        # is empty and the branch is skipped entirely - not an error. The
        # other branches still run (dense matches the chunk for "to").
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Field notes", "tony tony chopper appears once in the body.")
            _chunk(conn, "c1", "a1", 0, "tony tony chopper appears once in the body.")
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        assert _trigram_query("to") == ""
        assert sqlite_store._search_trigram(sqlite_store.CHUNKS, "to", 20) == []
        hits = search_results("to", limit=20)
        assert [h["artifact_id"] for h in hits] == ["a1"]


class TestExactPhrase:
    def test_quoted_phrase_pins_exact_note_first(self, sqlite_store):
        # R.10: `"tony tony chopper"` is a needle, not a bag of tokens. The
        # note with the phrase verbatim and in order must come first with
        # why="exact", above the note whose words are scattered - even
        # though the scattered note matches every token of the query.
        conn = db.get_conn()
        try:
            _note(
                conn,
                "a1",
                "Chopper plush",
                "tony tony chopper is a small reindeer with a pink hat.",
            )
            _chunk(
                conn,
                "c1",
                "a1",
                0,
                "tony tony chopper is a small reindeer with a pink hat.",
            )
            _note(
                conn,
                "a2",
                "Scattered words",
                "tony and chopper and tony are just scattered words.",
            )
            _chunk(
                conn,
                "c2",
                "a2",
                0,
                "tony and chopper and tony are just scattered words.",
            )
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results('"tony tony chopper"', limit=20)
        assert hits[0]["artifact_id"] == "a1"
        assert hits[0]["why"] == "exact"
        ids = [h["artifact_id"] for h in hits]
        assert "a2" in ids
        # One artifact never occupies two slots: the exact hit and the hybrid
        # copy of the same note are deduped, not doubled.
        assert len(ids) == len(set(ids))

    def test_unquoted_query_is_not_exact(self, sqlite_store):
        # Only a query wrapped ENTIRELY in double quotes activates the exact
        # branch. The same words without quotes stay a normal hybrid search.
        conn = db.get_conn()
        try:
            _note(
                conn,
                "a1",
                "Chopper plush",
                "tony tony chopper is a small reindeer with a pink hat.",
            )
            _chunk(
                conn,
                "c1",
                "a1",
                0,
                "tony tony chopper is a small reindeer with a pink hat.",
            )
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("tony tony chopper", limit=20)
        assert [h["artifact_id"] for h in hits] == ["a1"]
        assert all(h["why"] != "exact" for h in hits)


class TestRecency:
    def test_newer_note_breaks_identical_body_tie(self, sqlite_store, monkeypatch):
        # Two notes with identical bodies: the dense and keyword branches split
        # the pair one-to-one, so the fused base scores are exactly equal - a
        # genuine tie. The R.8 decay must break it toward the note touched
        # recently, and must not reorder when RECENCY_WEIGHT is zeroed (the
        # order ties out to the base score).
        #
        # Construction notes. With fully identical notes the branches rank
        # them 1-2 in lockstep, and the RRF gap (rank-1 vs rank-2, a
        # (k+2)/(k+1) ratio) is small at the canonical k=60 (62/61, ~1.016x) -
        # well under the 1.5x maximum recency boost - so a fresh note could
        # overtake the older one. The titles here are distinct-but-neutral so
        # the branches disagree symmetrically instead: the dense branch
        # (embedding similarity) ranks old first, while the keyword branch
        # ranks new first - its FTS row was written first, because the
        # rebuild's select_all follows idx_artifacts_live, whose (deleted_at,
        # created_at DESC) order puts the freshly-created note ahead. Both
        # notes then fuse to the same score (1/61 + 1/62 each) and recency is
        # the only tie-breaker that can separate them.
        #
        # The spec's "updated_at 180 days ago" is set on both timestamps:
        # created_at participates in the index order above, and a note that
        # old naturally has both.
        from enqueue.retrieve import candidates

        conn = db.get_conn()
        try:
            _note(conn, "old", "Field notes", _BODY)
            _chunk(conn, "oldc", "old", 0, _BODY)
            conn.execute(
                "UPDATE artifacts SET created_at = datetime('now', '-180 days'),"
                " updated_at = datetime('now', '-180 days') WHERE id = 'old'"
            )
            _note(conn, "new", "City farming", _BODY)
            _chunk(conn, "newc", "new", 0, _BODY)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("rooftops", limit=20)
        ids = [h["artifact_id"] for h in hits]
        assert ids[0] == "new", f"newer note should rank first, got {ids}"
        assert "old" in ids

        monkeypatch.setattr(candidates, "RECENCY_WEIGHT", 0.0)
        hits = search_results("rooftops", limit=20)
        ids = [h["artifact_id"] for h in hits]
        assert ids[0] == "old", f"weight 0 ties out to base score, got {ids}"
        assert ids[1] == "new"


class _FakeReranker:
    """Stands in for the BAAI/bge-reranker-base cross-encoder in tests.

    `rerank` returns the scores it was built with, so a test can pin exactly
    how the fused order should come out without downloading a gigabyte.
    """

    def __init__(self, scores: list[float]):
        self._scores = scores

    def rerank(self, query: str, documents):
        return self._scores[: len(list(documents))]


class TestRerank:
    def test_flag_off_never_touches_the_reranker(self, sqlite_store, monkeypatch):
        # The R.9 flag-off path must be byte-identical in behavior to R.8: it
        # must not construct the cross-encoder, let alone call it. A stub that
        # raises proves the machinery is unreachable, and the fused order is
        # exactly the R.8 order (this file's other tests, all written before
        # R.9, run with the flag off and pass unchanged).
        from enqueue.retrieve import candidates

        monkeypatch.setattr(config, "SEARCH_RERANK", False)

        def _boom():
            raise AssertionError("reranker must not load when SEARCH_RERANK is off")

        monkeypatch.setattr(candidates, "_cross_encoder", _boom)
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            _chunk(conn, "c1", "a1", 0, _BODY)
            _note(conn, "a2", "The Ur dig", _UNRELATED)
            _chunk(conn, "c2", "a2", 0, _UNRELATED)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("rooftops", limit=20)
        assert hits[0]["artifact_id"] == "a1"
        assert hits[0]["why"] == "chunk"

    def test_flag_on_reorders_by_cross_encoder_score(self, sqlite_store, monkeypatch):
        # With the flag on, the fused order is re-scored by the cross-encoder:
        # the stub's scores invert the fused ranking, and the result follows
        # the stub. The artifact rows themselves are untouched - only the
        # order changes, and `why` survives the rerank.
        from enqueue.retrieve import candidates

        monkeypatch.setattr(config, "SEARCH_RERANK", True)
        conn = db.get_conn()
        try:
            for i in range(3):
                aid = f"a{i}"
                _note(conn, aid, f"Rooftop note {i}", _BODY)
                _chunk(conn, f"c{i}", aid, 0, _BODY)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        # Whatever the fused order is, the stub says relevance runs the other
        # way: the last fused artifact gets the top score and the first gets
        # the bottom, so the reranked list must be the fused list reversed.
        fused = candidates._hybrid_results("rooftops", limit=30)
        fused_ids = [h["artifact_id"] for h in fused]
        scores = [round((i + 1) * 0.1, 2) for i in range(len(fused_ids))]
        monkeypatch.setattr(candidates, "_cross_encoder", lambda: _FakeReranker(scores))
        hits = search_results("rooftops", limit=20)
        assert [h["artifact_id"] for h in hits] == list(reversed(fused_ids))
        assert {h["why"] for h in hits} == {"chunk"}

    def test_flag_on_reranks_a_wider_window_than_limit(self, sqlite_store, monkeypatch):
        # The rerank stage pulls a wider fused window than the final limit, so
        # a candidate that ranked just past the cutoff can still be promoted.
        # With limit=5, the 21st note of 30 is outside the top five fused
        # results; the stub scoring it top must surface it at rank 1.
        from enqueue.retrieve import candidates

        monkeypatch.setattr(config, "SEARCH_RERANK", True)
        conn = db.get_conn()
        try:
            for i in range(30):
                aid = f"a{i:02d}"
                _note(conn, aid, f"Rooftop note {i:02d}", _BODY)
                _chunk(conn, f"c{i:02d}", aid, 0, _BODY)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        fused = candidates._hybrid_results("rooftops", limit=30)
        fused_ids = [h["artifact_id"] for h in fused]
        assert "a20" in fused_ids, "a20 should be inside the 30-wide fused window"
        assert "a20" not in fused_ids[:5], "a20 must start outside the top five"
        scores = [0.0] * len(fused_ids)
        scores[fused_ids.index("a20")] = 1.0
        monkeypatch.setattr(candidates, "_cross_encoder", lambda: _FakeReranker(scores))
        hits = search_results("rooftops", limit=5)
        assert hits[0]["artifact_id"] == "a20"
        assert len(hits) == 5

    def test_reranker_failure_degrades_to_fused_order(self, sqlite_store, monkeypatch):
        # A cross-encoder crash is not a search failure: the fused order is
        # returned unchanged, exactly what the flag-off path would produce.
        from enqueue.retrieve import candidates

        monkeypatch.setattr(config, "SEARCH_RERANK", True)

        def _boom():
            raise RuntimeError("model load failed")

        monkeypatch.setattr(candidates, "_cross_encoder", _boom)
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            _chunk(conn, "c1", "a1", 0, _BODY)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("rooftops", limit=20)
        assert [h["artifact_id"] for h in hits] == ["a1"]
