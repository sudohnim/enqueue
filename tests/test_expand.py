"""Query expansion: bounded by EXPANSION_CAP, degradable on model failure.

Phase 22. A lens expands into restatements and hypothetical passages; each
one is a sub-query that searches both collections, so the cap makes retrieval
cost explicit and bounded. The default (0 = no cap) reproduces the behavior
the retrieval baseline was measured at.
"""

from __future__ import annotations


from enqueue import config
from enqueue.retrieve import expand
from enqueue.schemas import LensExpansion


class _Scripted:
    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls = 0

    def complete(self, system, user, response_model, context=None, max_retries=None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.reply


def _expansion() -> LensExpansion:
    return LensExpansion(
        restatements=["r1", "r2", "r3", "r4", "r5"],
        passages=["p1", "p2", "p3"],
    )


class TestCap:
    def test_default_has_no_cap(self, monkeypatch):
        provider = _Scripted(reply=_expansion())
        monkeypatch.setattr(expand, "get_provider", lambda: provider)
        assert expand.expand("hydroponics") == [
            "hydroponics",
            "r1",
            "r2",
            "r3",
            "r4",
            "r5",
            "p1",
            "p2",
            "p3",
        ]

    def test_cap_bounds_the_sub_queries(self, monkeypatch):
        provider = _Scripted(reply=_expansion())
        monkeypatch.setattr(expand, "get_provider", lambda: provider)
        monkeypatch.setattr(config, "EXPANSION_CAP", 3)
        assert expand.expand("hydroponics") == ["hydroponics", "r1", "r2"]

    def test_cap_of_one_keeps_only_the_lens(self, monkeypatch):
        provider = _Scripted(reply=_expansion())
        monkeypatch.setattr(expand, "get_provider", lambda: provider)
        monkeypatch.setattr(config, "EXPANSION_CAP", 1)
        assert expand.expand("hydroponics") == ["hydroponics"]

    def test_model_failure_degrades_to_the_bare_lens(self, monkeypatch):
        provider = _Scripted(error=RuntimeError("boom"))
        monkeypatch.setattr(expand, "get_provider", lambda: provider)
        assert expand.expand("hydroponics") == ["hydroponics"]
        assert provider.calls == 1
