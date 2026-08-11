"""The three model primitives of the pivot engine and their cache.

Phase P2. Every derived value is cached in `derived_values`, keyed by
(scope, subject, attribute, source), and a user correction (source='user')
always wins over the model row on read (rule 2: the director beats the
curator). The tests prove the cache hits, the `grounded` flag travels with the
value, and a failed model call is never cached.

The provider is stubbed: the module's `get_provider` binding is replaced
with one returning a fake provider, so no real model call ever happens.
"""

from __future__ import annotations

from enqueue import db, derive, notes


class _FakeProvider:
    """A scripted provider: one reply per call, or a queue of replies.

    Exposes `name` and `model` like the real provider, and `complete()` builds
    the requested response model from the scripted dict, so both `_One` and
    `_Buckets` work through the same stub.
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


def _note(body: str) -> str:
    return notes.create(body=body)["artifact"]["id"]


def _cached(scope: str, subject: str, attribute: str):
    """The raw cached row, or None."""
    conn = db.get_conn()
    try:
        return conn.execute(
            "SELECT value, grounded, source, model_version FROM derived_values"
            " WHERE scope = ? AND subject = ? AND attribute = ?",
            (scope, subject, attribute),
        ).fetchone()
    finally:
        conn.close()


class TestExtract:
    def test_second_call_makes_no_model_call(self, store, quiet_queue, monkeypatch):
        artifact_id = _note("A field note: the signal was loud and clear at the estuary.")
        provider = _FakeProvider({"value": "the estuary"})
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        first = derive.extract(artifact_id, "setting", "the place the note describes")
        second = derive.extract(artifact_id, "setting", "the place the note describes")

        assert second == first
        assert provider.calls == 1  # the second call was a cache hit

    def test_result_is_grounded(self, store, quiet_queue, monkeypatch):
        artifact_id = _note("A field note: the signal was loud and clear at the estuary.")
        monkeypatch.setattr(derive, "get_provider", lambda: _FakeProvider({"value": "the estuary"}))

        result = derive.extract(artifact_id, "setting", "the place the note describes")

        assert result["value"] == "the estuary"
        assert result["grounded"] is True  # it came from the artifact's own text
        assert result["source"] == "model"


class TestEnrich:
    def test_two_artifacts_with_the_same_value_cost_one_enrich_call(
        self, store, quiet_queue, monkeypatch
    ):
        first_note = _note("A note about the southern ice field.")
        second_note = _note("Another note about the southern ice field too.")
        provider = _FakeProvider(
            [{"value": "Patagonia"}, {"value": "Patagonia"}, {"value": "the Andes"}]
        )
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        first = derive.extract(first_note, "place", "the place the note describes")
        second = derive.extract(second_note, "place", "the place the note describes")
        derived = derive.enrich(first["value"], "region", "the region this place belongs to")
        replayed = derive.enrich(second["value"], "region", "the region this place belongs to")

        assert first["value"] == second["value"] == "Patagonia"
        assert derived == {"value": "the Andes", "grounded": False, "source": "model"}
        assert replayed == derived  # same input value, served from the cache
        assert provider.calls == 3  # two extracts + one enrich, never two

    def test_empty_input_returns_ungrounded_without_a_model_call(self, store, monkeypatch):
        monkeypatch.setattr(derive, "get_provider", lambda: _FakeProvider({"value": "never"}))

        result = derive.enrich("", "region", "the region this place belongs to")

        assert result == {"value": "", "grounded": False}


class TestOverride:
    def test_user_correction_wins_over_a_model_row(self, store, quiet_queue, monkeypatch):
        artifact_id = _note("A field note: the signal was loud and clear at the estuary.")
        provider = _FakeProvider({"value": "the estuary"})
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        derive.extract(artifact_id, "setting", "the place the note describes")
        stored = derive.override("artifact", artifact_id, "setting", "the river mouth")

        assert stored["value"] == "the river mouth"
        assert stored["source"] == "user"
        assert stored["model_version"] == ""
        assert derive._read("artifact", artifact_id, "setting") == {
            "value": "the river mouth",
            "grounded": True,
            "source": "user",
        }
        # extract reads the cache first, so a re-run serves the correction
        # without another model call
        assert derive.extract(artifact_id, "setting", "anything")["value"] == "the river mouth"
        assert provider.calls == 1


class TestModelFailure:
    def test_extract_failure_returns_empty_and_caches_nothing(
        self, store, quiet_queue, monkeypatch
    ):
        artifact_id = _note("A field note: the signal was loud and clear at the estuary.")
        monkeypatch.setattr(derive, "get_provider", lambda: _FakeProvider(RuntimeError("down")))

        result = derive.extract(artifact_id, "setting", "the place the note describes")

        assert result["value"] == ""
        assert result["grounded"] is True
        assert result["source"] == "model"
        assert "error" in result
        assert _cached("artifact", artifact_id, "setting") is None

    def test_enrich_failure_returns_empty_and_caches_nothing(self, store, monkeypatch):
        monkeypatch.setattr(derive, "get_provider", lambda: _FakeProvider(RuntimeError("down")))

        result = derive.enrich("Patagonia", "region", "the region this place belongs to")

        assert result["value"] == ""
        assert result["grounded"] is False
        assert "error" in result
        assert _cached("value", "Patagonia", "region") is None


class TestBucketize:
    def test_maps_many_values_onto_fewer_buckets(self, store, monkeypatch):
        provider = _FakeProvider(
            {
                "mapping": {
                    "Colombia": "South America",
                    "Argentina": "South America",
                    "France": "Europe",
                }
            }
        )
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        mapping = derive.bucketize(
            ["France", "Colombia", "Argentina"],
            "the continent each country belongs to",
        )

        assert provider.calls == 1
        assert mapping["Colombia"] == "South America"
        assert mapping["Argentina"] == "South America"
        assert mapping["France"] == "Europe"
        assert len(set(mapping.values())) < len(mapping)  # fewer buckets than values
