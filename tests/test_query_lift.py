"""Query lifting: facet-style restatements of a search, cached, fail-soft."""

from __future__ import annotations

from enqueue import settings
from enqueue.retrieve import lift as lift_mod

REAL_LIFT = lift_mod.lift  # captured before the autouse fixture stubs it


class _Provider:
    name = "fake"
    model = "search-model"

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def complete(self, system, user, response_model, context=None, max_retries=None):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return response_model(**self.reply)


def _patch(monkeypatch, reply):
    import enqueue.providers.base as base_mod

    provider = _Provider(reply)
    asked = []

    def _get(**kw):
        asked.append(kw.get("role"))
        return provider

    monkeypatch.setattr(base_mod, "get_provider", _get)
    return provider, asked


CLAIMS = {
    "claims": [
        "Systems that yield a little under stress outlast rigid ones that fail all at once.",
        "short",
        "Systems that yield a little under stress outlast rigid ones that fail all at once.",
        "Shedding small losses early prevents one total collapse later on.",
    ]
}


def test_lifts_with_the_search_model_cleans_and_caches(store, monkeypatch):
    provider, asked = _patch(monkeypatch, CLAIMS)

    first = REAL_LIFT("software that degrades gracefully under load")
    again = REAL_LIFT("software  that degrades gracefully under load")

    assert first == [
        "Systems that yield a little under stress outlast rigid ones that fail all at once.",
        "Shedding small losses early prevents one total collapse later on.",
    ]
    assert again == first
    assert provider.calls == 1  # the second call is served from the cache
    assert asked[0] == "search"


def test_short_queries_and_failures_lift_nothing(store, monkeypatch):
    provider, _ = _patch(monkeypatch, RuntimeError("model down"))

    assert REAL_LIFT("Hypatia") == []
    assert provider.calls == 0
    assert REAL_LIFT("keeping a habit alive for years") == []
    assert REAL_LIFT("keeping a habit alive for years") == []
    assert provider.calls == 2  # a failure is not cached


def test_search_lift_setting_defaults_off(store):
    assert lift_mod.enabled_for_search() is False
    settings.update({"search_lift": "on"})
    assert lift_mod.enabled_for_search() is True


def test_search_passes_lifts_only_when_enabled(store, monkeypatch):
    from enqueue.retrieve import candidates as cand

    seen = []
    monkeypatch.setattr(lift_mod, "lift", lambda q: ["A lifted claim about the query."])
    monkeypatch.setattr(
        cand, "_hybrid_results", lambda q, limit, lifts=None: seen.append(lifts) or []
    )

    cand.search_results("software that degrades gracefully")
    settings.update({"search_lift": "on"})
    cand.search_results("software that degrades gracefully")
    cand.search_results('"an exact phrase needle"')

    assert seen == [[], ["A lifted claim about the query."], []]


def test_lifted_claims_reach_facets_in_search(store, monkeypatch):
    """A lifted claim lifts a facet's similarity past the floor's keep bar."""
    from enqueue import config, db
    from enqueue.index.store import get_store
    from enqueue.retrieve import candidates as cand

    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    claim = "Structures last by yielding under stress rather than resisting it."
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status, created_at,"
            " updated_at) VALUES ('w', 'note', 'Willow', 'x', 'w', 'ok', ?, ?)",
            (db.now(), db.now()),
        )
        conn.execute(
            "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust)"
            " VALUES ('f', 'w', 3, ?, ?, 1.0)",
            (claim, cand._get_model(False)),
        )
    s.upsert_facets()
    monkeypatch.setattr(cand, "judge_gray_zone", lambda q, hits: {h["artifact_id"] for h in hits})

    without = cand._hybrid_results("apps that degrade gracefully", 10)
    with_lift = cand._hybrid_results("apps that degrade gracefully", 10, [claim])

    # The only facet is always the nearest neighbour; lifting is what makes it close.
    before = next(h for h in without if h["artifact_id"] == "w")
    hit = next(h for h in with_lift if h["artifact_id"] == "w")
    assert hit["why"].startswith("facet") and hit["had_lexical_hit"] is False
    assert hit["dense_similarity"] >= cand.KEEP_ABOVE > before["dense_similarity"]
    get_store.cache_clear()
