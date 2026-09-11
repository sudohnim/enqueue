"""The retrieval accuracy overhaul: a summary model separate from the interactive
one, facet staleness keyed to that summary model (not the chat/judge model), the
gray-zone judge reading facets, and model-reported confidence stored as facet trust.
"""

from __future__ import annotations

from enqueue import db, notes, settings
from enqueue.ingest import facets as facets_mod
from enqueue.ingest.facets import _RawFacet, _RawFacetSet, _trust_from_confidence
from enqueue.providers import base as provider_base


def test_summarize_provider_splits_from_the_interactive_model(store, monkeypatch):
    """summarize=True uses summarize_model when set, and falls back to llm_model when
    not - so a single-model setup is unchanged and a split setup routes each path."""
    settings.update({"llm_backend": "ollama", "llm_model": "chat-model", "summarize_model": ""})
    assert provider_base.get_provider(summarize=True).model == "chat-model"

    settings.update({"summarize_model": "summary-model"})
    assert provider_base.get_provider().model == "chat-model"  # interactive path
    assert provider_base.get_provider(summarize=True).model == "summary-model"  # summary path


def test_facets_stay_valid_when_only_the_interactive_model_changes(store, quiet_queue, monkeypatch):
    """The staleness fix: a facet is stale only when the SUMMARY model that would
    rewrite it changes - not when the chat/judge model swaps. Switching llm_model
    (e.g. to a fast judge model) must not silently void every facet in search."""
    settings.update({"llm_backend": "ollama", "llm_model": "summary-model", "summarize_model": ""})

    class _Prov:
        model = "summary-model"

        def complete(self, system, user, response_model, context=None, max_retries=None):
            return _RawFacetSet(
                facets=[
                    _RawFacet(
                        level=1,
                        statement="Systems tend to persist long after the belief that justified them has gone.",
                    )
                ]
            )

    monkeypatch.setattr(provider_base, "get_provider", lambda **_: _Prov())
    aid = notes.create(body="word " * 80)["artifact"]["id"]
    with db.transaction() as conn:
        n, err = facets_mod.generate_for_artifact(conn, aid)
    assert err is None and n == 1

    # Now the interactive model changes but the summary model does not.
    settings.update({"llm_model": "fast-judge-model", "summarize_model": "summary-model"})

    from enqueue.retrieve.candidates import hit_is_stale

    conn = db.get_conn()
    try:
        fac = conn.execute(
            "SELECT model_version, body_version FROM facets WHERE artifact_id = ?", (aid,)
        ).fetchone()
        hit = {
            "artifact_id": aid,
            "model_version": fac["model_version"],
            "body_version": fac["body_version"],
        }
        # Staleness reads the summary model (summary-model), which still matches, so the
        # facet is live - even though the interactive model is now something else.
        assert hit_is_stale(conn, hit, {}) is False
    finally:
        conn.close()


def test_confidence_is_stored_as_trust(store, quiet_queue, monkeypatch):
    """The live-trust change: the model's per-facet confidence lands in the trust
    column, so a speculative facet no longer weighs the same as a solid one."""
    settings.update({"llm_backend": "ollama", "llm_model": "m", "summarize_model": ""})

    class _Prov:
        model = "m"

        def complete(self, system, user, response_model, context=None, max_retries=None):
            return _RawFacetSet(
                facets=[
                    _RawFacet(
                        level=1,
                        statement="Institutions tend to persist long after the belief that justified them fades.",
                        confidence=0.95,
                    ),
                    _RawFacet(
                        level=4,
                        statement="Every measurable relation between people quietly installs a hierarchy where none was.",
                        confidence=0.2,
                    ),
                ]
            )

    monkeypatch.setattr(provider_base, "get_provider", lambda **_: _Prov())
    aid = notes.create(body="word " * 80)["artifact"]["id"]
    with db.transaction() as conn:
        n, err = facets_mod.generate_for_artifact(conn, aid)
    assert err is None and n == 2

    conn = db.get_conn()
    try:
        trusts = {
            r["level"]: r["trust"]
            for r in conn.execute("SELECT level, trust FROM facets WHERE artifact_id = ?", (aid,))
        }
    finally:
        conn.close()
    assert trusts[1] == 0.95 and trusts[4] == 0.2  # not the old flat 0.5


def test_trust_from_confidence_is_robust():
    assert _trust_from_confidence(0.9) == 0.9
    assert _trust_from_confidence(None) == 0.5  # model omitted it
    assert _trust_from_confidence("nonsense") == 0.5
    assert _trust_from_confidence(1.7) == 1.0  # clamped
    assert _trust_from_confidence(-1.0) == 0.0


def test_gray_zone_judge_is_given_the_facets(store, quiet_queue, monkeypatch):
    """The judge fix: the gray-zone judge prompt now carries each candidate's facets,
    so a book-of-lessons note can't read as an LLM note on one nearby snippet."""
    from enqueue.retrieve import candidates as cand

    aid = notes.create(body="word " * 80)["artifact"]["id"]
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO facets (id, artifact_id, level, statement, model_version,"
            " body_version, trust) VALUES ('f1', ?, 1, ?, 'm', 't', 0.5)",
            (aid, "This concerns leadership and debt, not language models."),
        )

    seen = {}

    class _Prov:
        model = "m"

        def complete(self, system, user, response_model, context=None, max_retries=None):
            seen["user"] = user
            return cand._GrayZoneResponse(verdicts=[])

    monkeypatch.setattr(cand, "get_provider", lambda **_: _Prov())
    cand.judge_gray_zone(
        "notes on LLMs",
        [{"artifact_id": aid, "title": "Backfill", "snippet": "assorted", "kind": "note"}],
    )
    assert "leadership and debt" in seen["user"]  # the facet reached the judge
