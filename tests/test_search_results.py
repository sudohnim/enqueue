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
from enqueue.retrieve.candidates import (
    DROP_BELOW,
    KEEP_ABOVE,
    _apply_floor,
    _floor_verdict,
    search_results,
)

_BODY = "A city can feed itself from its rooftops, one tray of greens at a time."
_UNRELATED = "The ziggurat of Ur stood in the desert, season after season."


@pytest.fixture(autouse=True)
def _no_real_judge(monkeypatch):
    """Tests never touch a real model, but the Q.3b judge (Q.3) would fire
    the moment any corpus query lands in the gray zone. Stub it fail-open -
    keep everything - exactly the gate's error budget, so searches that are
    not about the judge behave as they did before it. Judge-specific tests
    override `get_provider` with their own verdicts.
    """
    from enqueue.retrieve import candidates as cand

    class _KeepAllJudge:
        model = "test-judge"

        def complete(self, *args, **kwargs):
            # No verdicts. All gray-zone candidates fall through to fail-open
            # and are kept - the leak-side choice for a test that is not
            # asserting on the judge.
            return cand._GrayZoneResponse(verdicts=[])

    monkeypatch.setattr(cand, "get_provider", lambda *a, **k: _KeepAllJudge())


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


class TestQueryBatching:
    """P.2: the search rollup is batched, not N+1.

    A trace hook counts every SELECT a search issues. The per-row probes that
    used to dominate (one title/body SELECT per candidate, one chunk SELECT per
    text-less artifact, one staleness probe per candidate) must not appear at
    all; the json_each batches must. The corpus is sized so the old code would
    have issued dozens of probes here.
    """

    @staticmethod
    def _count_statements(monkeypatch):
        """Trace the connection candidates uses; return the collected SQL list."""
        from enqueue.retrieve import candidates

        seen: list[str] = []
        real = candidates.db.get_conn

        def traced(*args, **kwargs):
            conn = real(*args, **kwargs)
            conn.set_trace_callback(lambda sql: seen.append(sql))
            return conn

        monkeypatch.setattr(candidates.db, "get_conn", traced)
        return seen

    def test_no_per_row_probes_in_the_rollup(self, sqlite_store, monkeypatch):
        conn = db.get_conn()
        try:
            # A matching note with chunks, and a facet-only artifact whose
            # current-model facet matches the query (exercises the staleness
            # prefetch and the entity-only body read).
            _note(conn, "a1", "Rooftop farming", _BODY)
            _chunk(conn, "c1", "a1", 0, _BODY)
            _note(conn, "a2", "Trade routes", "Goods moved along the river, season by season.")
            _chunk(conn, "c2", "a2", 0, "Goods moved along the river, season by season.")
            _facet(conn, "f1", "a2", 3, "Ziggurats rose above the mud-brick cities.", 0.9)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()
        sqlite_store.upsert_facets()

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

        statements = self._count_statements(monkeypatch)
        hits = search_results("ziggurat rooftops", limit=20)
        assert any(h["artifact_id"] == "a2" for h in hits), "facet-only match must survive"

        probes = [s for s in statements if " FROM artifacts WHERE id = ?" in s]
        assert probes == [], f"per-row artifact probes found: {probes[:3]}"
        chunk_probes = [s for s in statements if " FROM chunks WHERE artifact_id = ?" in s]
        assert chunk_probes == [], f"per-row chunk probes found: {chunk_probes[:3]}"
        batches = [s for s in statements if "SELECT value FROM json_each" in s]
        assert len(batches) >= 2, f"expected batched json_each queries, saw: {batches}"

    def test_candidate_titles_are_one_query_not_one_per_ranked_id(self, sqlite_store, monkeypatch):
        """The curate path (`candidates`) fetches ranked titles in one batch."""
        from enqueue.retrieve import candidates

        conn = db.get_conn()
        try:
            for i in range(10):
                _note(conn, f"a{i}", f"Rooftop farming {i}", _BODY)
                _chunk(conn, f"c{i}", f"a{i}", 0, _BODY)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        statements = self._count_statements(monkeypatch)
        out = candidates.candidates(["rooftops"], limit=20)
        assert len(out) == 10

        probes = [s for s in statements if " FROM artifacts WHERE id = ?" in s]
        assert probes == [], f"per-row title probes found: {probes[:3]}"
        titles = [s for s in statements if "SELECT id, title FROM artifacts" in s]
        assert len(titles) == 1, f"expected one batched title query, saw: {titles}"


class TestQ2PerLegSignals:
    """Q.2: the /search rollup carries per-leg signals at the fusion point so
    the relevance floor (Q.3) can judge raw legs, not the fused RRF score.
    Every result must carry `dense_similarity` (the best cosine similarity
    the dense branch produced for this artifact) and `had_lexical_hit`
    (whether any of keyword / trigram / facet / entity hit it)."""

    def test_a_real_match_carries_a_dense_similarity_and_a_lexical_flag(self, sqlite_store):
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            _chunk(conn, "c1", "a1", 0, _BODY)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("rooftops", limit=20)
        assert hits[0]["artifact_id"] == "a1"
        assert (
            "dense_similarity" in hits[0]
        ), "every search hit must carry the per-leg dense signal (Q.2)"
        assert (
            "had_lexical_hit" in hits[0]
        ), "every search hit must carry the per-leg lexical flag (Q.2)"
        # The chunk side is the one that produced this match: keyword + dense
        # both touched a1, so the lexical flag is on and the dense similarity
        # is well above 0 (the corpus is small so cosine is generous).
        assert hits[0]["had_lexical_hit"]
        assert hits[0]["dense_similarity"] > 0.0

    def test_a_query_with_no_dense_match_still_carries_zero_similarity(self, sqlite_store):
        """When the dense branch returns nothing for an artifact, the flag is
        0.0 (not missing) so the floor (Q.3) can read it without a KeyError."""
        # a1 has no chunks at all - the dense branch cannot score it. The
        # keyword branch on its title may still hit, so the artifact can
        # appear in results, but its dense_similarity is 0.0.
        conn = db.get_conn()
        try:
            conn.execute(
                "INSERT INTO artifacts (id, kind, title, body, content_hash,"
                " status, created_at, updated_at) VALUES (?, 'note', ?, '',"
                " ?, 'ok', datetime('now'), datetime('now'))",
                ("a-title-only", "A title only", "a-title-only_hash"),
            )
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("title", limit=20)
        if hits:
            for h in hits:
                assert "dense_similarity" in h
                assert "had_lexical_hit" in h
                assert isinstance(h["dense_similarity"], float)
                assert isinstance(h["had_lexical_hit"], bool)


class TestQ3RelevanceFloor:
    """Q.3: the two-tier gray-zone gate (Minh's DECISION after the single-
    threshold block-out). A hit with a lexical leg, or a dense-only hit at or
    above KEEP_ABOVE, is kept without a model call; a dense-only hit below
    DROP_BELOW is dropped without one; the gray zone between the bars is
    fail-open kept until Q.3b's judge decides it. A query whose entire
    result set drops returns [] - the honest "nothing found" (a gibberish
    query's nearest neighbors score below DROP_BELOW, so the wall no longer
    lights up with unrelated notes)."""

    def test_lexical_hit_passes_without_a_model_call(self):
        assert _floor_verdict({"had_lexical_hit": True, "dense_similarity": 0.1}) == "keep"

    def test_dense_above_keep_above_passes_without_a_model_call(self):
        assert _floor_verdict({"had_lexical_hit": False, "dense_similarity": KEEP_ABOVE}) == "keep"
        assert _floor_verdict({"had_lexical_hit": False, "dense_similarity": 0.9}) == "keep"

    def test_dense_below_drop_below_drops_without_a_model_call(self):
        assert _floor_verdict({"had_lexical_hit": False, "dense_similarity": 0.3}) == "drop"
        assert _floor_verdict({"had_lexical_hit": False, "dense_similarity": 0.0}) == "drop"

    def test_gray_zone_is_the_judges_patch(self):
        """The strip between the bars is a gray zone - neither keep nor drop
        on constants alone; only the Q.3b judge may split it."""
        assert _floor_verdict({"had_lexical_hit": False, "dense_similarity": 0.6}) == "gray"
        assert _floor_verdict({"had_lexical_hit": False, "dense_similarity": DROP_BELOW}) == "gray"

    def test_a_gibberish_query_below_drop_below_drops_to_empty(self, sqlite_store):
        """A query no real artifact matches must come back as `[]`. This is the
        PLAN Phase Q headline bug: dense kNN always returns its nearest
        neighbors, so the wall used to light up with unrelated notes. The
        floor fixes that for the clearly-far case: "quantum flux capacitor"
        measures ~0.40 against this corpus, below DROP_BELOW, with no
        lexical hit, so every hit drops."""
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            _chunk(conn, "c1", "a1", 0, _BODY)
            _note(conn, "a2", "Trade routes", _UNRELATED)
            _chunk(conn, "c2", "a2", 0, _UNRELATED)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("quantum flux capacitor", limit=20)
        assert hits == [], f"gibberish query below DROP_BELOW must return [], got {hits}"

    def test_a_gray_zone_hit_is_kept_only_if_the_judge_says_relevant(
        self, sqlite_store, monkeypatch
    ):
        """The gray zone between the two bars is the judge's patch (Q.3b).

        "hyperdimensional cheese grater" measures 0.469 against the rooftops
        note - below KEEP_ABOVE, at or above DROP_BELOW - so it is neither
        clearly relevant nor clearly irrelevant. One batched model call
        decides it: a "not relevant" ruling drops the hit to [], a
        "relevant" ruling keeps it.
        """
        from enqueue.retrieve import candidates as cand

        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            _chunk(conn, "c1", "a1", 0, _BODY)
            _note(conn, "a2", "Trade routes", _UNRELATED)
            _chunk(conn, "c2", "a2", 0, _UNRELATED)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        class _Judge:
            """Stub: one batched call returning the verdicts it was built with."""

            def __init__(self, verdicts):
                self.model = "test-model"
                self.verdicts = verdicts

            def complete(self, system, user, response_model, context=None, max_retries=3):
                return response_model(verdicts=self.verdicts)

        monkeypatch.setattr(
            cand, "get_provider", lambda *a, **k: _Judge([{"id": "a1", "relevant": False}])
        )
        hits = search_results("hyperdimensional cheese grater", limit=20)
        assert hits == [], f"judge said not relevant, expected [], got {hits}"
        # Clear the judge's cache so the next call is judged fresh.
        conn = db.get_conn()
        try:
            conn.execute("DELETE FROM derived_values WHERE scope = 'gray_judge'")
            conn.commit()
        finally:
            conn.close()
        monkeypatch.setattr(
            cand, "get_provider", lambda *a, **k: _Judge([{"id": "a1", "relevant": True}])
        )
        hits = search_results("hyperdimensional cheese grater", limit=20)
        assert len(hits) == 1 and hits[0]["artifact_id"] == "a1"
        assert not hits[0]["had_lexical_hit"]
        assert DROP_BELOW <= hits[0]["dense_similarity"] < KEEP_ABOVE


class TestQ3bGrayZoneJudge:
    """Q.3b: the gray-zone judge's behavior and its hard contract.

    The judge is one batched model call over only the gray-zone candidates
    (Q.3's strip no constant can split). Three rules are pinned here: a
    clearly-answered verdict is honored (relevant kept, not relevant
    dropped), a raising or unhelpful call keeps every candidate (fail-open -
    the gate's error budget is a small leak, never a hidden real note), and a
    re-run of the same search is served from cache with no new call (Q.4
    measures the same query repeatedly, and a paging wall re-runs it).
    """

    @staticmethod
    def _hits(*aids, sim=0.6):
        return [
            {
                "artifact_id": aid,
                "title": f"note {aid}",
                "kind": "note",
                "snippet": f"body of {aid}",
                "dense_similarity": sim,
                "had_lexical_hit": False,
            }
            for aid in aids
        ]

    def test_relevant_is_kept_and_not_is_dropped(self, store, monkeypatch):
        from enqueue.retrieve import candidates as cand

        class _Judge:
            model = "test-model"

            def __init__(self, verdicts):
                self.verdicts = verdicts

            def complete(self, system, user, response_model, context=None, max_retries=3):
                return response_model(verdicts=self.verdicts)

        monkeypatch.setattr(
            cand,
            "get_provider",
            lambda *a, **k: _Judge(
                [{"id": "a1", "relevant": True}, {"id": "a2", "relevant": False}]
            ),
        )
        out = _apply_floor("quantum flux capacitor", self._hits("a1", "a2"))
        assert [h["artifact_id"] for h in out] == ["a1"]

    def test_raising_provider_keeps_everything(self, store, monkeypatch):
        from enqueue.retrieve import candidates as cand

        def _boom(*a, **k):
            raise RuntimeError("provider down")

        monkeypatch.setattr(cand, "get_provider", _boom)
        hits = self._hits("a1", "a2", sim=0.5)
        assert [h["artifact_id"] for h in _apply_floor("quantum flux capacitor", hits)] == [
            "a1",
            "a2",
        ]

    def test_second_identical_search_makes_no_new_call(self, store, monkeypatch):
        from enqueue.retrieve import candidates as cand

        class _CountingJudge:
            model = "test-model"

            def __init__(self):
                self.n = 0

            def complete(self, system, user, response_model, context=None, max_retries=3):
                self.n += 1
                return response_model(verdicts=[{"id": "a1", "relevant": True}])

        judge = _CountingJudge()
        monkeypatch.setattr(cand, "get_provider", lambda *a, **k: judge)
        hits = self._hits("a1")
        _apply_floor("quantum flux capacitor", hits)
        _apply_floor("quantum flux capacitor", hits)
        assert judge.n == 1
