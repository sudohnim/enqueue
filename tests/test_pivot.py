"""The pivot orchestrator: subsets, step chains, grouping, and the planner.

Phase P4. The model does only the per-item judgments through `derive`; this
module's `run` is ordinary code that selects, caches, groups, and renders. The
tests prove the bounded call budget (enrich once per DISTINCT value, never per
artifact), that an empty derived key becomes the '' bucket instead of being
dropped, that subsets are capped, that a misplanned spec is rejected, and - the
generalization guard - that one engine groups two unrelated fixtures with zero
code changes.

The provider is stubbed the way the existing tests stub it (see
tests/test_lens_cache.py): the module's `get_provider` binding is replaced with
one returning a fake provider, so no real model call ever happens. `derive` is
patched for the run path and `pivot` for the planner path, because each module
binds `get_provider` at import time.
"""

from __future__ import annotations

import pytest

from enqueue import derive, notes, pivot


class _FakeProvider:
    """A scripted provider: one reply per call, or the same reply each time.

    Exposes `name` and `model` like the real provider, and `complete()` builds
    the requested response model from the scripted dict, so `_One`, `_Buckets`,
    and the planner's spec model all work through the same stub.
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


class TestRun:
    def test_two_step_spec_groups_by_the_enriched_value(self, store, quiet_queue, monkeypatch):
        solitude = _note("A note about One Hundred Years of Solitude by Gabriel Garcia Marquez.")
        cholera = _note("A note about Love in the Time of Cholera by Gabriel Garcia Marquez.")
        stranger = _note("A note about The Stranger by Albert Camus.")
        provider = _FakeProvider(
            [
                {"value": "Gabriel Garcia Marquez"},  # extract: solitude
                {"value": "Gabriel Garcia Marquez"},  # extract: cholera
                {"value": "Albert Camus"},  # extract: stranger
                {"value": "Europe"},  # enrich: Albert Camus
                {"value": "South America"},  # enrich: Gabriel Garcia Marquez
            ]
        )
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        spec = {
            "subset": {"kind": "ids", "value": f"{solitude} {cholera} {stranger}"},
            "steps": [
                {
                    "op": "extract",
                    "attribute": "author",
                    "instruction": "the author of the book the note is about",
                },
                {
                    "op": "enrich",
                    "attribute": "region",
                    "instruction": "the region the author is from",
                },
            ],
            "group_by": "region",
            "bucketize": False,
        }

        result = pivot.run(spec)

        assert result["group_by"] == "region"
        assert result["truncated"] is False
        by_key = {group["key"]: group for group in result["groups"]}
        assert set(by_key) == {"South America", "Europe"}
        assert by_key["South America"]["artifact_ids"] == [solitude, cholera]
        assert by_key["Europe"]["artifact_ids"] == [stranger]
        # the enrich step made the whole response ungrounded (rule 2: an
        # inferred value is never dressed as the user's data)
        assert all(not group["grounded"] for group in result["groups"])
        # groups are ordered by size, largest first
        sizes = [len(group["artifact_ids"]) for group in result["groups"]]
        assert sizes == sorted(sizes, reverse=True)

    def test_enrich_is_called_once_per_distinct_value(self, store, quiet_queue, monkeypatch):
        # Three notes, but only two distinct authors: enrich must run twice, not
        # three times, so the per-value cache keeps the call budget bounded.
        solitude = _note("A note about One Hundred Years of Solitude by Gabriel Garcia Marquez.")
        cholera = _note("A note about Love in the Time of Cholera by Gabriel Garcia Marquez.")
        stranger = _note("A note about The Stranger by Albert Camus.")
        provider = _FakeProvider(
            [
                {"value": "Gabriel Garcia Marquez"},  # extract: solitude
                {"value": "Gabriel Garcia Marquez"},  # extract: cholera
                {"value": "Albert Camus"},  # extract: stranger
                {"value": "Europe"},  # enrich: Albert Camus
                {"value": "South America"},  # enrich: Gabriel Garcia Marquez
            ]
        )
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        spec = {
            "subset": {"kind": "ids", "value": f"{solitude} {cholera} {stranger}"},
            "steps": [
                {
                    "op": "extract",
                    "attribute": "author",
                    "instruction": "the author of the book the note is about",
                },
                {
                    "op": "enrich",
                    "attribute": "region",
                    "instruction": "the region the author is from",
                },
            ],
            "group_by": "region",
            "bucketize": False,
        }

        pivot.run(spec)

        # three extracts (one per artifact) + two enriches (one per distinct
        # author). A per-artifact enrich would have cost six calls.
        assert provider.calls == 5

    def test_empty_derived_key_lands_in_the_empty_bucket(self, store, quiet_queue, monkeypatch):
        known = _note("A field note: the signal was loud and clear at the estuary.")
        unknown = _note("A cryptic note with no discernible setting.")
        provider = _FakeProvider(
            [
                {"value": "the estuary"},  # extract: known
                {"value": ""},  # extract: unknown - the text supports no setting
            ]
        )
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        spec = {
            "subset": {"kind": "ids", "value": f"{known} {unknown}"},
            "steps": [
                {
                    "op": "extract",
                    "attribute": "setting",
                    "instruction": "the setting the note describes",
                },
            ],
            "group_by": "setting",
            "bucketize": False,
        }

        result = pivot.run(spec)

        by_key = {group["key"]: group for group in result["groups"]}
        assert "" in by_key  # never dropped, never hidden
        assert by_key[""]["artifact_ids"] == [unknown]
        assert by_key["the estuary"]["artifact_ids"] == [known]
        # no enrich ran, so the grouping is fully grounded
        assert all(group["grounded"] for group in result["groups"])

    def test_the_same_engine_groups_an_unrelated_fixture(self, store, quiet_queue, monkeypatch):
        """The generalization guard: zero code change from the book fixture.

        The same run() code, a different spec: recipe notes grouped by cuisine
        instead of book notes grouped by region. If anything in the engine were
        book-shaped, this fixture would fail.
        """
        paella = _note("A recipe note for paella with saffron rice and seafood.")
        tortilla = _note("A recipe note for a potato tortilla with eggs and onions.")
        sushi = _note("A recipe note for sushi with vinegared rice and raw fish.")
        provider = _FakeProvider(
            [
                {"value": "paella"},  # extract: paella
                {"value": "tortilla"},  # extract: tortilla
                {"value": "sushi"},  # extract: sushi
                # enrich runs once per DISTINCT value, in sorted order:
                # paella, sushi, tortilla
                {"value": "Spanish"},  # enrich: paella
                {"value": "Japanese"},  # enrich: sushi
                {"value": "Spanish"},  # enrich: tortilla
            ]
        )
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        spec = {
            "subset": {"kind": "ids", "value": f"{paella} {tortilla} {sushi}"},
            "steps": [
                {
                    "op": "extract",
                    "attribute": "dish",
                    "instruction": "the dish the recipe note describes",
                },
                {
                    "op": "enrich",
                    "attribute": "cuisine",
                    "instruction": "the cuisine the dish belongs to",
                },
            ],
            "group_by": "cuisine",
            "bucketize": False,
        }

        result = pivot.run(spec)

        by_key = {group["key"]: group for group in result["groups"]}
        assert set(by_key) == {"Spanish", "Japanese"}
        assert by_key["Spanish"]["artifact_ids"] == [paella, tortilla]
        assert by_key["Japanese"]["artifact_ids"] == [sushi]


class TestResolveSubset:
    def test_caps_past_the_limit(self):
        many = " ".join(f"id-{i}" for i in range(pivot.MAX_PIVOT_ARTIFACTS + 5))
        ids, truncated = pivot.resolve_subset({"kind": "ids", "value": many})

        assert truncated is True
        assert len(ids) == pivot.MAX_PIVOT_ARTIFACTS
        assert ids[0] == "id-0"
        assert ids[-1] == f"id-{pivot.MAX_PIVOT_ARTIFACTS - 1}"

    def test_under_the_limit_is_not_truncated(self):
        ids, truncated = pivot.resolve_subset({"kind": "ids", "value": "note-a note-b"})

        assert truncated is False
        assert ids == ["note-a", "note-b"]


class TestPlan:
    def test_rejects_a_group_by_that_is_not_the_last_step_attribute(self, store, monkeypatch):
        # The plan is well-formed except for the group key: the last step
        # computes 'region' but the spec asks to group by 'author'.
        provider = _FakeProvider(
            {
                "subset": {"kind": "search", "value": "book notes"},
                "steps": [
                    {
                        "op": "extract",
                        "attribute": "author",
                        "instruction": "the author of the book",
                    },
                    {
                        "op": "enrich",
                        "attribute": "region",
                        "instruction": "the region the author is from",
                    },
                ],
                "group_by": "author",
                "bucketize": False,
                "bucketize_instruction": "",
            }
        )
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)

        with pytest.raises(pivot.PivotError, match="group key has to be the last step's attribute"):
            pivot.plan("organize my book notes by author region")
