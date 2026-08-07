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

from enqueue import capture, derive, notes, pivot
from enqueue.providers.base import ProviderError


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

    def test_field_step_groups_with_no_model_calls(self, store, quiet_queue, monkeypatch):
        """A one-step `field` spec groups by a stored column with zero model calls.

        The provider raises if `complete` is ever called: a field lead is a SQL
        read, not a judgment, so the whole run must not touch a model. The
        groups are fully grounded - no enrich ran - and the empty-key bucket
        rule still holds for an artifact whose stored value reads "".
        """
        note = _note("A note about the estuary.")
        link = capture.link("https://example.com/some/page")["id"]
        pdf = capture.upload(b"%PDF-1.4 fake", "paper.pdf", "application/pdf")["id"]
        provider = _FakeProvider([])  # any call is a failure
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        spec = {
            "subset": {"kind": "ids", "value": f"{note} {link} {pdf}"},
            "steps": [
                {"op": "field", "attribute": "kind", "instruction": ""},
            ],
            "group_by": "kind",
            "bucketize": False,
        }

        result = pivot.run(spec)

        assert provider.calls == 0  # no model call anywhere in the run
        assert result["group_by"] == "kind"
        assert result["truncated"] is False
        by_key = {group["key"]: group for group in result["groups"]}
        assert set(by_key) == {"note", "link", "pdf"}
        assert by_key["note"]["artifact_ids"] == [note]
        assert by_key["link"]["artifact_ids"] == [link]
        assert by_key["pdf"]["artifact_ids"] == [pdf]
        # no enrich ran, so the grouping is fully grounded
        assert all(group["grounded"] for group in result["groups"])

    def test_field_step_empty_value_lands_in_the_empty_bucket(
        self, store, quiet_queue, monkeypatch
    ):
        """A stored value that reads "" is never dropped, even from a field lead."""
        note = _note("A note about the estuary.")
        provider = _FakeProvider([])
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        spec = {
            "subset": {"kind": "ids", "value": note},
            "steps": [
                {"op": "field", "attribute": "source", "instruction": ""},
            ],
            "group_by": "source",
            "bucketize": False,
        }

        result = pivot.run(spec)

        assert provider.calls == 0
        by_key = {group["key"]: group for group in result["groups"]}
        assert "" in by_key  # the note has no url: the "not determined" bucket
        assert by_key[""]["artifact_ids"] == [note]

    def test_field_then_enrich(self, store, quiet_queue, monkeypatch):
        """A field lead composes with an enrich step: structured read, then inference.

        The enrich runs once per distinct kind (not per artifact), and it
        taints the whole run ungrounded exactly as an extract lead would: an
        inferred value is never dressed as the user's data.
        """
        first_note = _note("A note about the estuary.")
        second_note = _note("Another note about the delta.")
        link = capture.link("https://example.com/some/page")["id"]
        # two distinct kinds -> exactly two enrich calls, in sorted order
        provider = _FakeProvider(
            [
                {"value": "web"},  # enrich: link
                {"value": "text"},  # enrich: note
            ]
        )
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        spec = {
            "subset": {"kind": "ids", "value": f"{first_note} {second_note} {link}"},
            "steps": [
                {"op": "field", "attribute": "kind", "instruction": ""},
                {
                    "op": "enrich",
                    "attribute": "medium",
                    "instruction": "the medium this kind belongs to",
                },
            ],
            "group_by": "medium",
            "bucketize": False,
        }

        result = pivot.run(spec)

        assert provider.calls == 2  # one enrich per distinct kind, never per artifact
        by_key = {group["key"]: group for group in result["groups"]}
        assert set(by_key) == {"web", "text"}
        assert by_key["web"]["artifact_ids"] == [link]
        assert by_key["text"]["artifact_ids"] == [first_note, second_note]
        # the enrich step made the whole response ungrounded, as with an extract lead
        assert all(not group["grounded"] for group in result["groups"])

    def test_title_seeded_enrich_chain_reads_the_title_free(self, store, quiet_queue, monkeypatch):
        """The "by region" shape: field(title) -> enrich(author) -> enrich(region).

        The author is not in the note's body - a terse book note names the book,
        not its writer - so the grounded seed is the title (a free field read),
        and author and region are honest enrich hops. The title read costs zero
        model calls; only the two enrich steps do, deduped per distinct value.
        """
        # Bodies that never name the author: the title is the only handle on the book.
        odyssey = notes.create(
            body="A note about a long voyage home and a clever hero.", title="The Odyssey"
        )["artifact"]["id"]
        chip_war = notes.create(
            body="A note about semiconductors, TSMC, and ASML.", title="Chip War"
        )["artifact"]["id"]
        provider = _FakeProvider(
            [
                # enrich author, once per distinct title (sorted: Chip War, The Odyssey)
                {"value": "Chris Miller"},
                {"value": "Homer"},
                # enrich region, once per distinct author (sorted: Chris Miller, Homer)
                {"value": "North America"},
                {"value": "Europe"},
            ]
        )
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        spec = {
            "subset": {"kind": "ids", "value": f"{odyssey} {chip_war}"},
            "steps": [
                {"op": "field", "attribute": "title", "instruction": ""},
                {"op": "enrich", "attribute": "author", "instruction": "the author of the book"},
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

        # Two enrich steps, two distinct values each = four calls. The title read
        # (a field) added nothing: extract-per-artifact would have cost more and
        # still found no author in the body.
        assert provider.calls == 4
        by_key = {group["key"]: group for group in result["groups"]}
        assert set(by_key) == {"Europe", "North America"}
        assert by_key["Europe"]["artifact_ids"] == [odyssey]
        assert by_key["North America"]["artifact_ids"] == [chip_war]
        # region is world knowledge: the whole run is honestly ungrounded.
        assert all(not group["grounded"] for group in result["groups"])

    def test_filter_step_drops_the_items_it_judges_out(self, store, quiet_queue, monkeypatch):
        """A 'filter' step prunes the set before grouping, keeping only 'yes'.

        The chain reads each title, keeps only the ones judged to be books, then
        groups the survivors. The dropped item never reaches a group - not even
        the '' bucket - because a filter removes it from the working set. The
        filter is world knowledge, so the whole run is honestly ungrounded.
        """
        odyssey = notes.create(body="A note about a voyage.", title="The Odyssey")["artifact"]["id"]
        grocery = notes.create(body="milk, eggs, bread", title="Grocery list")["artifact"]["id"]
        chip_war = notes.create(body="A note about chips.", title="Chip War")["artifact"]["id"]
        provider = _FakeProvider(
            [
                # filter: is-a-book, once per distinct title (sorted: Chip War,
                # Grocery list, The Odyssey)
                {"value": "yes"},  # Chip War
                {"value": "no"},  # Grocery list -> dropped
                {"value": "yes"},  # The Odyssey
                # enrich: fiction or non-fiction, once per surviving distinct title
                # (sorted: Chip War, The Odyssey)
                {"value": "non-fiction"},  # Chip War
                {"value": "fiction"},  # The Odyssey
            ]
        )
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        spec = {
            "subset": {"kind": "ids", "value": f"{odyssey} {grocery} {chip_war}"},
            "steps": [
                {"op": "field", "attribute": "title", "instruction": ""},
                {
                    "op": "filter",
                    "attribute": "is a book",
                    "instruction": "Answer yes or no: is this title a book?",
                },
                {
                    "op": "enrich",
                    "attribute": "fiction or non-fiction",
                    "instruction": "fiction or non-fiction",
                },
            ],
            "group_by": "fiction or non-fiction",
            "bucketize": False,
        }

        result = pivot.run(spec)

        all_ids = {aid for group in result["groups"] for aid in group["artifact_ids"]}
        assert grocery not in all_ids  # dropped by the filter, in no group at all
        by_key = {group["key"]: group for group in result["groups"]}
        assert set(by_key) == {"fiction", "non-fiction"}
        assert by_key["fiction"]["artifact_ids"] == [odyssey]
        assert by_key["non-fiction"]["artifact_ids"] == [chip_war]
        # the run used world knowledge (filter + enrich), so it is ungrounded
        assert all(not group["grounded"] for group in result["groups"])

    def test_affirmative_reads_yes_and_drops_the_rest(self):
        assert pivot._affirmative("yes")
        assert pivot._affirmative("Yes, it is a book")
        assert pivot._affirmative("TRUE")
        assert not pivot._affirmative("no")
        assert not pivot._affirmative("")
        assert not pivot._affirmative("I do not know")


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
    def test_coerces_group_by_to_the_last_step_attribute(self, store, monkeypatch):
        # The model named a group_by ('author') that disagrees with its own last
        # step ('region'). group_by is only a label - run() groups on the last
        # step's values - so this is coerced, not rejected: the request runs, and
        # the grouping is by 'region' as the last step actually computes.
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

        spec = pivot.plan("organize my book notes by author region")
        assert spec["group_by"] == "region"

    def test_repairs_an_enrich_first_plan(self, store, monkeypatch):
        # A small model often starts the chain with 'enrich': it plans category
        # inference but never a step that reads the note, so nothing grounds the
        # grouping (rule 1). Rather than reject the request, plan() prepends the
        # one read every chain needs - an extract of the note's own tags/topics -
        # and the plan becomes runnable without another model call.
        provider = _FakeProvider(
            {
                "subset": {"kind": "tags", "value": ""},
                "steps": [
                    {
                        "op": "enrich",
                        "attribute": "category",
                        "instruction": "Classify the note's tags into general categories.",
                    }
                ],
                "group_by": "category",
                "bucketize": False,
                "bucketize_instruction": "",
            }
        )
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)

        spec = pivot.plan("group everything I have saved into categories")

        assert [step["op"] for step in spec["steps"]] == ["extract", "enrich"]
        assert spec["steps"][0]["attribute"] == "tags"
        # The grouping still happens at the enrich's attribute: the repair only
        # grounds the chain, it never changes what is being grouped.
        assert spec["group_by"] == "category"

    def test_repair_keeps_group_by_at_the_last_step(self, store, monkeypatch):
        # The repair prepends an extract, so the last step - and therefore the
        # grouping attribute - is unchanged even when the model named a group_by
        # that disagrees with its own chain.
        provider = _FakeProvider(
            {
                "subset": {"kind": "search", "value": "kitchen notes"},
                "steps": [
                    {
                        "op": "enrich",
                        "attribute": "space category",
                        "instruction": "From the size, infer the space category.",
                    }
                ],
                "group_by": "size",
                "bucketize": False,
                "bucketize_instruction": "",
            }
        )
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)

        spec = pivot.plan("group my kitchen notes by space")

        assert spec["group_by"] == "space category"
        assert spec["steps"][0]["op"] == "extract"

    def test_corrective_retry_on_a_validation_failure(self, store, monkeypatch):
        # A model that cannot hold the format gets one corrective pass: the first
        # reply fails validation, the second - told exactly what failed - succeeds.
        # The budget is bounded: exactly one extra call, never a loop.
        from pydantic import ValidationError

        valid = {
            "subset": {"kind": "search", "value": "book notes"},
            "steps": [{"op": "extract", "attribute": "author", "instruction": "the author"}],
            "group_by": "author",
            "bucketize": False,
            "bucketize_instruction": "",
        }
        bad = ValidationError.from_exception_data(
            "_PlannedSpec", [{"type": "missing", "loc": ("steps",), "input": None}]
        )
        first = ProviderError("wrong shape")
        first.__cause__ = bad  # the provider raises with `from exc`; mimic that chain
        provider = _FakeProvider([first, valid])
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)

        spec = pivot.plan("organize my book notes by author")

        assert spec["group_by"] == "author"
        assert provider.calls == 2

    def test_no_retry_on_a_transport_failure(self, store, monkeypatch):
        # Only a validation failure earns a corrective pass. An endpoint that is
        # down, a key that is rejected, or a host that is not a model is reported
        # immediately - retrying those is not a fix, it is a delay.
        provider = _FakeProvider([RuntimeError("endpoint down")])
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)

        with pytest.raises(pivot.PivotError):
            pivot.plan("organize my book notes by author")
        assert provider.calls == 1

    def test_rejects_an_empty_id_list(self, store, monkeypatch):
        # A model that reaches for 'ids' as a placeholder and leaves it empty has
        # planned nothing to group. 'Everything' is a search with an empty value,
        # not an empty id list, so this plan is rejected, not run.
        provider = _FakeProvider(
            {
                "subset": {"kind": "ids", "value": ""},
                "steps": [{"op": "extract", "attribute": "subject", "instruction": "the subject"}],
                "group_by": "subject",
                "bucketize": False,
                "bucketize_instruction": "",
            }
        )
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)

        with pytest.raises(pivot.PivotError):
            pivot.plan("group everything I have saved")
        assert provider.calls == 1

    def test_plan_coerces_a_mislabeled_field_to_enrich(self, store, monkeypatch):
        """A 'field' step on an attribute outside the registry is repaired to 'enrich'.

        A weak planner calls "fiction or non-fiction" a field because it sounds
        like a property, while correctly reading the title as a real field. An
        attribute that is not a column cannot be a field, so it can only be an
        inference: it is coerced to 'enrich' rather than rejected. The real field
        ('title') is left alone, so the fiction/non-fiction grouping runs as
        field(title) -> enrich(...) instead of failing on the mislabel.
        """
        provider = _FakeProvider(
            {
                "subset": {"kind": "search", "value": "book"},
                "steps": [
                    {"op": "field", "attribute": "title", "instruction": "Read the title."},
                    {
                        "op": "field",  # mislabeled: this is world knowledge, not a column
                        "attribute": "fiction or non-fiction",
                        "instruction": "whether the book is fiction or non-fiction",
                    },
                ],
                "group_by": "fiction or non-fiction",
                "bucketize": False,
                "bucketize_instruction": "",
            }
        )
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)

        spec = pivot.plan("organize my book notes by fiction vs non-fiction")

        # The real field stays a field; the mislabeled one becomes an enrich.
        assert spec["steps"][0] == {
            "op": "field",
            "attribute": "title",
            "instruction": "Read the title.",
        }
        assert spec["steps"][1]["op"] == "enrich"
        assert spec["steps"][1]["attribute"] == "fiction or non-fiction"
        assert spec["group_by"] == "fiction or non-fiction"

    def test_plan_uses_field_for_kind(self, store, monkeypatch):
        """A one-step 'field' plan on 'kind' is accepted as-is and groups by kind.

        The stub stands in for the live planner: this documents the intended
        behavior - a request to organize by kind plans a 'field' step, which
        leads the chain (a field is a grounded read), and group_by is the
        field's own attribute.
        """
        provider = _FakeProvider(
            {
                "subset": {"kind": "search", "value": ""},
                "steps": [
                    {
                        "op": "field",
                        "attribute": "kind",
                        "instruction": "Read the item's own kind from its record.",
                    },
                ],
                "group_by": "kind",
                "bucketize": False,
                "bucketize_instruction": "",
            }
        )
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)

        spec = pivot.plan("organize my saved things by kind")

        assert spec["steps"] == [
            {
                "op": "field",
                "attribute": "kind",
                "instruction": "Read the item's own kind from its record.",
            },
        ]
        assert spec["group_by"] == "kind"

    def test_plan_drops_a_trailing_filter_and_regroups(self, store, monkeypatch):
        """A filter cannot be the last step - it prunes, it does not key groups.

        The model ended the chain on a filter, so group_by would have been the
        filter's own attribute. The trailing filter is dropped and group_by falls
        back to the real grouping step before it, rather than refusing the plan.
        """
        provider = _FakeProvider(
            {
                "subset": {"kind": "search", "value": "book"},
                "steps": [
                    {"op": "field", "attribute": "title", "instruction": "Read the title."},
                    {
                        "op": "enrich",
                        "attribute": "genre",
                        "instruction": "the genre of the book",
                    },
                    {
                        "op": "filter",
                        "attribute": "is a book",
                        "instruction": "Answer yes or no: is this a book?",
                    },
                ],
                "group_by": "is a book",
                "bucketize": False,
                "bucketize_instruction": "",
            }
        )
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)

        spec = pivot.plan("group my book notes by genre")

        assert [s["op"] for s in spec["steps"]] == ["field", "enrich"]
        assert spec["group_by"] == "genre"

    def test_plan_rejects_a_filter_first_chain(self, store, monkeypatch):
        """A 'filter' works from a value it has not read yet if it leads: rejected."""
        provider = _FakeProvider(
            {
                "subset": {"kind": "search", "value": "book"},
                "steps": [
                    {
                        "op": "filter",
                        "attribute": "is a book",
                        "instruction": "Answer yes or no: is this a book?",
                    },
                ],
                "group_by": "is a book",
                "bucketize": False,
                "bucketize_instruction": "",
            }
        )
        monkeypatch.setattr(pivot, "get_provider", lambda: provider)

        with pytest.raises(pivot.PivotError, match="first step"):
            pivot.plan("keep only my books")
