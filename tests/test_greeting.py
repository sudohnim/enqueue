"""The wall's greeting: bucket math, fallback timing, and the cached phrase.

No model runs here. Generation is a background thread, so the pieces are tested
directly - the validator, the bucket boundaries, the cache, and `_generate` with a
fake provider - rather than waiting on real threads or a model. The one thread that
does run is a recorder blocked on an event, so the in-flight guard is deterministic.
"""

from __future__ import annotations

import threading
from datetime import datetime

import pytest
from pydantic import ValidationError

from enqueue import greeting
from enqueue.greeting import Greeting
from enqueue.providers.base import ProviderError


@pytest.fixture(autouse=True)
def _clean_state():
    with greeting._lock:
        greeting._phrases.clear()
        greeting._pending.clear()
    yield
    with greeting._lock:
        greeting._phrases.clear()
        greeting._pending.clear()


class _FakeProvider:
    """Returns one phrase for any call, like a well-behaved model."""

    def __init__(self, phrase: str) -> None:
        self._phrase = phrase

    def complete(self, system, user, response_model):
        return response_model(text=self._phrase)


class _BoomProvider:
    """Fails like a dead or misconfigured endpoint."""

    def complete(self, system, user, response_model):
        raise ProviderError("the model is on fire")


def _bucket_for(dt: datetime) -> int:
    return greeting.bucket(dt.timestamp())


# ---------------------------------------------------------------------- buckets


def test_bucket_boundaries():
    assert greeting.bucket(0) == 0
    assert greeting.bucket(greeting.BUCKET_SECONDS - 1) == 0
    assert greeting.bucket(greeting.BUCKET_SECONDS) == 1


def test_bucket_rejects_garbage():
    with pytest.raises(TypeError):
        greeting.bucket("not a timestamp")  # type: ignore[arg-type]


def test_fallback_by_hour():
    morning = datetime(2025, 1, 1, 8)
    afternoon = datetime(2025, 1, 1, 14)
    evening = datetime(2025, 1, 1, 20)
    assert greeting.fallback(morning) == "Good morning"
    assert greeting.fallback(afternoon) == "Good afternoon"
    assert greeting.fallback(evening) == "Good evening"


def test_fallback_boundaries():
    assert greeting.fallback(datetime(2025, 1, 1, 11)) == "Good morning"
    assert greeting.fallback(datetime(2025, 1, 1, 12)) == "Good afternoon"
    assert greeting.fallback(datetime(2025, 1, 1, 16)) == "Good afternoon"
    assert greeting.fallback(datetime(2025, 1, 1, 17)) == "Good evening"


# ---------------------------------------------------------------------- validator


def test_validator_accepts_a_short_phrase():
    assert Greeting(text="Up late tonight").text == "Up late tonight"


def test_validator_strips_quotes_and_trailing_punctuation():
    assert Greeting(text='"Good morning"').text == "Good morning"
    assert Greeting(text="Up late tonight?").text == "Up late tonight"


def test_validator_rejects_empty_or_overlong():
    with pytest.raises(ValidationError):
        Greeting(text="")
    with pytest.raises(ValidationError):
        Greeting(text="one two three four five six")


# --------------------------------------------------------------------------- get


def test_get_returns_cached_without_kicking(monkeypatch):
    monkeypatch.setattr(greeting, "ensure", lambda now=None: 1 / 0)
    b = _bucket_for(datetime(2025, 1, 1, 14))
    with greeting._lock:
        greeting._phrases[b] = "Up late tonight"
    r = greeting.get(datetime(2025, 1, 1, 14))
    assert r == {"text": "Up late tonight", "bucket": b, "generated": True}


def test_get_falls_back_and_kicks_generation(monkeypatch):
    kicked: list = []
    monkeypatch.setattr(greeting, "ensure", lambda now=None: kicked.append(now))
    b = _bucket_for(datetime(2025, 1, 1, 14))
    r = greeting.get(datetime(2025, 1, 1, 14))
    assert r["text"] == "Good afternoon"
    assert r["generated"] is False
    assert r["bucket"] == b
    assert len(kicked) == 1


# ------------------------------------------------------------------------- ensure


def test_ensure_generates_once_per_bucket(monkeypatch):
    release = threading.Event()
    calls: list = []

    def _recorder(b, hour):
        calls.append((b, hour))
        release.wait(2)

    monkeypatch.setattr(greeting, "_generate", _recorder)
    dt = datetime(2025, 1, 1, 14)
    b = _bucket_for(dt)
    greeting.ensure(dt)
    greeting.ensure(dt)  # in-flight guard: no second thread
    release.set()
    assert calls == [(b, 14)]


def test_ensure_skips_cached_bucket(monkeypatch):
    monkeypatch.setattr(greeting, "_generate", lambda b, h: 1 / 0)
    dt = datetime(2025, 1, 1, 14)
    b = _bucket_for(dt)
    with greeting._lock:
        greeting._phrases[b] = "Already said"
    greeting.ensure(dt)  # must not spawn a thread for a cached bucket


# ---------------------------------------------------------------------- generate


def test_generate_stores_the_phrase(monkeypatch):
    monkeypatch.setattr(greeting, "get_provider", lambda: _FakeProvider("Up late tonight"))
    b = _bucket_for(datetime(2025, 1, 1, 2))
    with greeting._lock:
        greeting._pending.add(b)
    greeting._generate(b, 2)
    with greeting._lock:
        assert greeting._phrases[b] == "Up late tonight"
        assert b not in greeting._pending


def test_generate_failure_keeps_the_fallback(monkeypatch):
    monkeypatch.setattr(greeting, "get_provider", lambda: _BoomProvider())
    b = _bucket_for(datetime(2025, 1, 1, 14))
    with greeting._lock:
        greeting._pending.add(b)
    greeting._generate(b, 14)
    with greeting._lock:
        assert b not in greeting._phrases
        assert b not in greeting._pending  # a later request may try again
