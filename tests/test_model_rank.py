"""Model re-ranking: the search model orders the top results, cached, fail-open."""

from __future__ import annotations

from enqueue import settings
from enqueue.retrieve import model_rank


class _Provider:
    name = "fake"
    model = "search-model"

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0
        self.users = []

    def complete(self, system, user, response_model, context=None, max_retries=None):
        self.calls += 1
        self.users.append(user)
        if isinstance(self.reply, Exception):
            raise self.reply
        return response_model(**self.reply)


def _patch(monkeypatch, reply):
    import enqueue.providers.base as base_mod

    provider = _Provider(reply)
    monkeypatch.setattr(base_mod, "get_provider", lambda **kw: provider)
    return provider


def _hits(*ids):
    return [{"artifact_id": i, "title": f"Note {i}", "snippet": f"text of {i}"} for i in ids]


def _ids(hits):
    return [h["artifact_id"] for h in hits]


def test_apply_order_puts_named_hits_first_and_keeps_the_rest():
    hits = _hits("a", "b", "c", "d")
    assert _ids(model_rank.apply_order(hits, ["c", "zzz", "a", "c"])) == ["c", "a", "b", "d"]


def test_the_model_orders_the_window_and_the_order_is_cached(store, monkeypatch):
    provider = _patch(monkeypatch, {"ids": ["c", "not-offered", "a"]})
    hits = _hits("a", "b", "c")

    first = model_rank.order("notes on staying calm", hits)
    again = model_rank.order("notes  on staying calm", list(reversed(hits)))

    assert _ids(first) == ["c", "a", "b"]
    assert _ids(again) == ["c", "a", "b"]  # same candidates, any order: served from cache
    assert provider.calls == 1
    assert "[id:b]" in provider.users[0]


def test_only_the_window_is_sent_and_the_tail_keeps_its_place(store, monkeypatch):
    monkeypatch.setattr(model_rank, "WINDOW", 2)
    provider = _patch(monkeypatch, {"ids": ["b", "a"]})

    ranked = model_rank.order("calm", _hits("a", "b", "c"))

    assert _ids(ranked) == ["b", "a", "c"]
    assert "[id:c]" not in provider.users[0]


def test_a_failure_keeps_the_fused_order_and_is_not_cached(store, monkeypatch):
    provider = _patch(monkeypatch, RuntimeError("model down"))
    hits = _hits("a", "b")

    assert _ids(model_rank.order("calm", hits)) == ["a", "b"]
    assert _ids(model_rank.order("calm", hits)) == ["a", "b"]
    assert provider.calls == 2


def test_search_orders_by_the_model_only_when_enabled(store, monkeypatch):
    from enqueue.retrieve import candidates as cand

    monkeypatch.setattr(cand, "_hybrid_results", lambda q, limit, lifts=None: _hits("a", "b"))
    monkeypatch.setattr(cand, "_apply_floor", lambda q, hits: hits)
    monkeypatch.setattr(cand, "_needs_fuzzy", lambda hybrid: False)
    monkeypatch.setattr(model_rank, "order", lambda q, hits: list(reversed(hits)))

    assert model_rank.enabled() is False
    assert _ids(cand.search_results("staying calm under pressure")) == ["a", "b"]
    settings.update({"search_model_rank": "on"})
    assert _ids(cand.search_results("staying calm under pressure")) == ["b", "a"]
