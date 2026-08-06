"""The pivot HTTP surface: plan, run, and the user correction.

Phase P5. The client turns a request into a spec (POST /pivot/plan), runs it
(POST /pivot/run) and gets each group's cards without a second round trip, and
fixes a wrong value (POST /derived/override) so the re-run shows the corrected
value. These tests hit the same HTTP boundary the UI does.

The provider is stubbed the way the existing tests stub it (see
tests/test_lens_cache.py): each module's `get_provider` binding is replaced
with one returning a fake provider, so no real model call ever happens. `plan`
patches `pivot.get_provider` and the run path patches `derive.get_provider`,
because each module binds the function at import time.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from enqueue import derive, notes, pivot
from enqueue.api import app


class _FakeProvider:
    """A scripted provider: one reply per call, or the same reply each time.

    Exposes `name` and `model` like the real provider, and `complete()` builds
    the requested response model from the scripted dict, so the planner's spec
    model and the derive `_One` model work through the same stub.
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


def _extract_spec(ids: list[str], attribute: str = "author") -> dict:
    """A one-step extract spec, the shape the planner returns."""
    return {
        "subset": {"kind": "ids", "value": " ".join(ids)},
        "steps": [
            {
                "op": "extract",
                "attribute": attribute,
                "instruction": f"the {attribute} of the book the note is about",
            },
        ],
        "group_by": attribute,
        "bucketize": False,
        "bucketize_instruction": "",
    }


def _two_step_spec(ids: list[str]) -> dict:
    """An extract-then-enrich spec, the shape the UI's move control targets.

    The group key is the enrich step's attribute, so a correction on that
    attribute is what moves a card in a two-step pivot.
    """
    return {
        "subset": {"kind": "ids", "value": " ".join(ids)},
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
        "bucketize_instruction": "",
    }


class TestPlanThenRun:
    def test_plan_then_run_returns_hydrated_groups(self, store, quiet_queue, monkeypatch):
        first = _note("A note about One Hundred Years of Solitude by Gabriel Garcia Marquez.")
        second = _note("A note about Love in the Time of Cholera by Gabriel Garcia Marquez.")
        third = _note("A note about The Stranger by Albert Camus.")

        # The planner: one call that turns the request into a runnable spec.
        plan_provider = _FakeProvider(
            {
                "subset": {"kind": "ids", "value": f"{first} {second} {third}"},
                "steps": [
                    {
                        "op": "extract",
                        "attribute": "author",
                        "instruction": "the author of the book the note is about",
                    },
                ],
                "group_by": "author",
                "bucketize": False,
                "bucketize_instruction": "",
            }
        )
        monkeypatch.setattr(pivot, "get_provider", lambda: plan_provider)

        # The run path: one extract per artifact, in subset order.
        run_provider = _FakeProvider(
            [
                {"value": "Gabriel Garcia Marquez"},  # extract: first
                {"value": "Gabriel Garcia Marquez"},  # extract: second
                {"value": "Albert Camus"},  # extract: third
            ]
        )
        monkeypatch.setattr(derive, "get_provider", lambda: run_provider)

        client = TestClient(app)

        planned = client.post("/pivot/plan", json={"request": "organize my book notes by author"})
        assert planned.status_code == 200
        spec = planned.json()["spec"]
        assert spec["group_by"] == "author"
        assert spec["subset"]["kind"] == "ids"
        assert [step["op"] for step in spec["steps"]] == ["extract"]

        resp = client.post("/pivot/run", json={"spec": spec})
        assert resp.status_code == 200
        result = resp.json()
        assert result["group_by"] == "author"
        assert result["truncated"] is False

        by_key = {group["key"]: group for group in result["groups"]}
        assert set(by_key) == {"Gabriel Garcia Marquez", "Albert Camus"}
        assert by_key["Gabriel Garcia Marquez"]["artifact_ids"] == [first, second]
        assert by_key["Albert Camus"]["artifact_ids"] == [third]
        # groups are ordered by size, largest first
        sizes = [len(group["artifact_ids"]) for group in result["groups"]]
        assert sizes == sorted(sizes, reverse=True)

        # Each group's cards are hydrated wall items, no second round trip.
        for group in result["groups"]:
            for item in group["items"]:
                for field in (
                    "id",
                    "kind",
                    "title",
                    "excerpt",
                    "created_at",
                    "updated_at",
                    "pinned",
                ):
                    assert field in item, field
                assert item["kind"] == "note"

        # No enrich ran, so the grouping is fully grounded.
        assert all(group["grounded"] for group in result["groups"])
        # The plan and the run each made exactly their scripted calls.
        assert plan_provider.calls == 1
        assert run_provider.calls == 3


class TestOverrideWins:
    def test_override_wins_after_an_enrich_step(self, store, quiet_queue, monkeypatch):
        """The UI's move control on an enriched group, end to end.

        The correction is written scope='artifact' on the group_by attribute -
        exactly what museum.html sends - and the re-run must land the card in
        the corrected group even though that attribute comes from an enrich
        step, whose cache is keyed per value, not per artifact (rule 2: the
        director beats the curator).
        """
        first = _note("A note about One Hundred Years of Solitude by Gabriel Garcia Marquez.")
        second = _note("A note about The Stranger by Albert Camus.")
        spec = _two_step_spec([first, second])

        provider = _FakeProvider(
            [
                {"value": "Gabriel Garcia Marquez"},  # extract: first
                {"value": "Albert Camus"},  # extract: second
                # enrich runs once per DISTINCT value, in sorted order:
                # Albert Camus before Gabriel Garcia Marquez
                {"value": "Europe"},  # enrich: Albert Camus
                {"value": "South America"},  # enrich: Gabriel Garcia Marquez
            ]
        )
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        client = TestClient(app)

        first_run = client.post("/pivot/run", json={"spec": spec}).json()
        by_key = {group["key"]: group for group in first_run["groups"]}
        assert by_key["South America"]["artifact_ids"] == [first]
        assert by_key["Europe"]["artifact_ids"] == [second]

        # The reader decides the first note belongs in Europe after all.
        corrected = client.post(
            "/derived/override",
            json={
                "scope": "artifact",
                "subject": first,
                "attribute": "region",
                "value": "Europe",
            },
        )
        assert corrected.status_code == 200

        calls_before = provider.calls
        re_run = client.post("/pivot/run", json={"spec": spec}).json()
        by_key = {group["key"]: group for group in re_run["groups"]}
        assert set(by_key) == {"Europe"}
        assert by_key["Europe"]["artifact_ids"] == [first, second]
        # everything served from the caches: zero new model calls
        assert provider.calls == calls_before

    def test_override_then_rerun_shows_the_corrected_value(self, store, quiet_queue, monkeypatch):
        first = _note("A note about One Hundred Years of Solitude by Gabriel Garcia Marquez.")
        second = _note("A note about The Stranger by Albert Camus.")
        spec = _extract_spec([first, second])

        provider = _FakeProvider(
            [
                {"value": "Gabriel Garcia Marquez"},  # extract: first
                {"value": "Albert Camus"},  # extract: second
            ]
        )
        monkeypatch.setattr(derive, "get_provider", lambda: provider)

        client = TestClient(app)

        first_run = client.post("/pivot/run", json={"spec": spec}).json()
        by_key = {group["key"]: group for group in first_run["groups"]}
        assert by_key["Gabriel Garcia Marquez"]["artifact_ids"] == [first]
        assert by_key["Albert Camus"]["artifact_ids"] == [second]

        # The misfiled note: the reader decides the first note is by Camus, not
        # Garcia Marquez. The correction is stored per (scope, subject,
        # attribute) with source='user', which always wins on read (rule 2: the
        # director beats the curator).
        corrected = client.post(
            "/derived/override",
            json={
                "scope": "artifact",
                "subject": first,
                "attribute": "author",
                "value": "Albert Camus",
            },
        )
        assert corrected.status_code == 200
        row = corrected.json()
        assert row["value"] == "Albert Camus"
        assert row["source"] == "user"
        assert row["model_version"] == ""
        assert row["grounded"] is True  # carried over from the model row

        calls_before = provider.calls
        re_run = client.post("/pivot/run", json={"spec": spec}).json()
        by_key = {group["key"]: group for group in re_run["groups"]}
        assert set(by_key) == {"Albert Camus"}
        assert by_key["Albert Camus"]["artifact_ids"] == [first, second]

        # The re-run served every extract from the cache (a user row for the
        # corrected note, a model row for the other): zero new model calls.
        assert provider.calls == calls_before
