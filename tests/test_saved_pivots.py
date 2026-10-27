"""Saved groupings: storage over the saved_pivots table.

A saved grouping is the spec (the arrangement recipe), not a frozen result, so
these tests prove the spec round-trips exactly through JSON and that the list is
newest-first and spec-free. No model call happens here - it is plain storage.
"""

from __future__ import annotations

import pytest

from enqueue import notes, pivots_saved, trash

_SPEC = {
    "subset": {"kind": "ids", "value": "a b"},
    "steps": [{"op": "extract", "attribute": "author", "instruction": "the author"}],
    "group_by": "author",
    "bucketize": False,
    "bucketize_instruction": "",
}


def test_save_then_get_round_trips_the_spec(store):
    pivot_id = pivots_saved.save("By author", _SPEC)
    got = pivots_saved.get(pivot_id)

    assert got["name"] == "By author"
    assert got["spec"] == _SPEC  # exact, through JSON


def test_listing_is_newest_first_and_spec_free(store):
    first = pivots_saved.save("older", _SPEC)
    second = pivots_saved.save("newer", _SPEC)

    rows = pivots_saved.listing()
    assert [row["id"] for row in rows[:2]] == [second, first]
    assert "spec" not in rows[0] and "spec_json" not in rows[0]
    assert "result_json" not in rows[0]
    # Never built: no size to show yet.
    assert rows[0]["groups"] is None and rows[0]["items"] is None


def test_listing_sizes_a_built_view_without_its_trashed_artifacts(store, quiet_queue):
    kept = notes.create("a note that stays in the view, long enough to keep")["artifact"]["id"]
    binned = notes.create("a note that is trashed after the view was built")["artifact"]["id"]
    pivot_id = pivots_saved.save("sized", _SPEC)
    pivots_saved.set_result(
        pivot_id,
        {
            "groups": [
                {"key": "a", "artifact_ids": [kept, binned]},
                {"key": "b", "artifact_ids": [kept]},
            ]
        },
    )
    trash.delete(binned)

    row = next(r for r in pivots_saved.listing() if r["id"] == pivot_id)
    assert (row["groups"], row["items"]) == (2, 1)


def test_delete_removes_it(store):
    pivot_id = pivots_saved.save("gone soon", _SPEC)
    pivots_saved.delete(pivot_id)

    assert all(row["id"] != pivot_id for row in pivots_saved.listing())
    with pytest.raises(KeyError):
        pivots_saved.get(pivot_id)


def test_save_requires_a_name(store):
    with pytest.raises(ValueError):
        pivots_saved.save("   ", _SPEC)


def test_api_save_list_get_run_delete(store):
    from fastapi.testclient import TestClient

    from enqueue import api

    client = TestClient(api.app)

    # An empty-ids spec runs with zero model calls (nothing to extract), so the
    # round trip through the API needs no provider stub.
    empty = {**_SPEC, "subset": {"kind": "ids", "value": ""}}
    pivot_id = client.post("/pivots", json={"name": "By author", "spec": empty}).json()["id"]

    listed = client.get("/pivots").json()["items"]
    assert any(row["id"] == pivot_id and row["name"] == "By author" for row in listed)

    fetched = client.get(f"/pivots/{pivot_id}").json()
    assert fetched["spec"] == empty

    ran = client.post("/pivot/run", json={"spec": fetched["spec"]})
    assert ran.status_code == 200
    assert ran.json()["groups"] == []

    assert client.delete(f"/pivots/{pivot_id}").status_code == 200
    assert client.get(f"/pivots/{pivot_id}").status_code == 404


def test_api_save_without_name_is_400(store):
    from fastapi.testclient import TestClient

    from enqueue import api

    client = TestClient(api.app)
    resp = client.post("/pivots", json={"name": "  ", "spec": _SPEC})
    assert resp.status_code == 400


def test_artifact_detail_loads_all_specs_in_one_query(store, monkeypatch):
    """P.2e: view membership on GET /artifacts/{id} is one query, not one per view."""
    from enqueue import api, db, notes
    from fastapi.testclient import TestClient

    note = notes.create(body="# Rooftops\n\nA city feeds itself from its rooftops.")
    aid = note["artifact"]["id"]

    # A couple of saved views: one that includes the artifact, one that does
    # not, and one that explicitly excludes it (exclusion beats inclusion).
    keep_a = pivots_saved.save("Keeps a", {**_SPEC, "included_ids": [aid]})
    pivots_saved.save("Keeps b", {**_SPEC, "included_ids": ["other-id"]})
    pivots_saved.save("Excludes a", {**_SPEC, "included_ids": [aid], "excluded_ids": [aid]})

    statements: list[str] = []
    real = db.get_conn

    def traced(*args, **kwargs):
        conn = real(*args, **kwargs)
        conn.set_trace_callback(lambda sql: statements.append(sql))
        return conn

    monkeypatch.setattr(db, "get_conn", traced)

    with TestClient(api.app) as client:
        detail = client.get(f"/artifacts/{aid}").json()

    assert detail["views"] == [{"id": keep_a, "name": "Keeps a"}], detail["views"]
    pivots_sql = [s for s in statements if "saved_pivots" in s and s.lstrip().startswith("SELECT")]
    assert len(pivots_sql) == 1, f"expected one saved_pivots SELECT, saw: {pivots_sql}"


def test_result_cache_round_trips(store):
    """The materialized result cache: set_result stores the group structure and get
    reads it back."""

    pivot_id = pivots_saved.save("Cached view", _SPEC)
    assert pivots_saved.get(pivot_id)["result"] is None  # nothing run yet

    structure = {
        "truncated": False,
        "group_by": "author",
        "groups": [{"key": "x", "artifact_ids": ["a"]}],
    }
    pivots_saved.set_result(pivot_id, structure)
    got = pivots_saved.get(pivot_id)
    assert got["result"] == structure
    assert got["result_at"]  # a timestamp was stamped


def test_set_result_on_missing_view_is_a_noop(store):
    # A view deleted between a run and the cache write must not raise.
    pivots_saved.set_result("ghost-id", {"groups": []})


def test_locked_remove_and_add_edit_the_result_without_recompute(store):
    """A locked view's membership is edited in the materialized result directly: remove
    drops an id (pruning empty groups), add inserts under a group key. No spec re-run."""
    pid = pivots_saved.save("Locked", _SPEC)
    # Materialize a two-group result by hand (as an open would).
    pivots_saved.set_result(
        pid,
        {
            "group_by": {"attribute": "kind"},
            "truncated": False,
            "groups": [
                {"key": "note", "artifact_ids": ["a", "b"]},
                {"key": "link", "artifact_ids": ["c"]},
            ],
        },
    )

    # Remove one: it leaves its group, and a group emptied by removal is pruned.
    res = pivots_saved.remove_from_result(pid, ["c"])
    keys = {g["key"]: g["artifact_ids"] for g in res["groups"]}
    assert "link" not in keys and keys["note"] == ["a", "b"]

    # Add to an existing group by key; adding again is a no-op.
    res = pivots_saved.add_to_result(pid, "d", "note")
    assert res["groups"][0]["artifact_ids"] == ["a", "b", "d"]
    res = pivots_saved.add_to_result(pid, "d", "note")
    assert res["groups"][0]["artifact_ids"] == ["a", "b", "d"]

    # Add under a new key creates the group.
    res = pivots_saved.add_to_result(pid, "e", "pdf")
    assert {"key": "pdf", "artifact_ids": ["e"]} in res["groups"]


def test_locked_edit_on_unmaterialized_view_returns_none(store):
    pid = pivots_saved.save("Never opened", _SPEC)
    assert pivots_saved.remove_from_result(pid, ["x"]) is None
    assert pivots_saved.add_to_result(pid, "x", "note") is None


def _two_groups(pid):
    pivots_saved.set_result(
        pid,
        {
            "group_by": "fiction vs non-fiction",
            "truncated": False,
            "groups": [
                {"key": "fiction", "artifact_ids": ["a", "b"]},
                {"key": "non-fiction", "artifact_ids": ["c"]},
            ],
        },
    )


def test_a_removed_card_is_recorded_and_restores_to_the_group_it_left(store):
    """Removing used to live only in the frozen groups: the Removed shelf could not show
    it, Restore had nothing to undo, and a Rebuild brought the card back."""
    pid = pivots_saved.save("Books", _SPEC)
    _two_groups(pid)

    pivots_saved.remove_from_result(pid, ["c"])
    saved = pivots_saved.get(pid)
    assert saved["spec"]["excluded_ids"] == ["c"]  # the shelf and a Rebuild see it
    assert saved["result"]["removed"] == {"c": "non-fiction"}
    assert [g["key"] for g in saved["result"]["groups"]] == ["fiction"]

    res = pivots_saved.restore_to_result(pid, ["c"])
    keys = {g["key"]: g["artifact_ids"] for g in res["groups"]}
    assert keys == {"fiction": ["a", "b"], "non-fiction": ["c"]}
    saved = pivots_saved.get(pid)
    assert saved["spec"]["excluded_ids"] == [] and saved["result"]["removed"] == {}


def test_an_exclusion_with_no_recorded_group_is_placed_by_the_caller(store):
    # An exclusion made before removals were recorded: only the spec knows about it.
    pid = pivots_saved.save("Books", {**_SPEC, "excluded_ids": ["z"]})
    _two_groups(pid)

    res = pivots_saved.restore_to_result(pid, ["z"], place=lambda aid: "fiction")
    assert res["groups"][0]["artifact_ids"] == ["a", "b", "z"]
    assert pivots_saved.get(pid)["spec"]["excluded_ids"] == []

    # With nothing to place it by, it lands in "" (shown as Not determined).
    pid2 = pivots_saved.save("Books 2", {**_SPEC, "excluded_ids": ["z"]})
    _two_groups(pid2)
    res = pivots_saved.restore_to_result(pid2, ["z"])
    assert {"key": "", "artifact_ids": ["z"]} in res["groups"]


def test_a_rebuild_keeps_where_removed_cards_came_from(store):
    pid = pivots_saved.save("Books", _SPEC)
    _two_groups(pid)
    pivots_saved.remove_from_result(pid, ["c"])

    # A Rebuild writes a fresh result (without the excluded card, and without a map).
    pivots_saved.set_result(
        pid,
        {
            "group_by": "x",
            "truncated": False,
            "groups": [{"key": "fiction", "artifact_ids": ["a", "b"]}],
        },
    )
    assert pivots_saved.get(pid)["result"]["removed"] == {"c": "non-fiction"}
    res = pivots_saved.restore_to_result(pid, ["c"])
    assert {"key": "non-fiction", "artifact_ids": ["c"]} in res["groups"]


def test_adding_a_removed_card_back_ends_its_exclusion(store):
    pid = pivots_saved.save("Books", _SPEC)
    _two_groups(pid)
    pivots_saved.remove_from_result(pid, ["c"])

    pivots_saved.add_to_result(pid, "c", "fiction")
    saved = pivots_saved.get(pid)
    assert saved["spec"]["excluded_ids"] == [] and saved["result"]["removed"] == {}


def test_restore_on_an_unmaterialized_view_returns_none(store):
    pid = pivots_saved.save("Never opened", _SPEC)
    assert pivots_saved.restore_to_result(pid, ["x"]) is None


class TestManualViews:
    """A view arranged by hand: the person's headers and order, no recipe, no model."""

    def test_a_layout_keeps_headers_and_order_as_given(self, store):
        pid = pivots_saved.save_manual("Reading")
        saved = pivots_saved.get(pid)
        assert pivots_saved.is_manual(saved["spec"]) and saved["result"]["groups"] == []

        pivots_saved.set_layout(
            pid,
            [
                {"key": "  To read ", "artifact_ids": ["c", "a"]},
                {"key": "Empty shelf", "artifact_ids": []},
                {"key": "Done", "artifact_ids": ["b"]},
            ],
        )
        groups = pivots_saved.get(pid)["result"]["groups"]
        assert [(g["key"], g["artifact_ids"]) for g in groups] == [
            ("To read", ["c", "a"]),  # trimmed, and c stays before a
            ("Empty shelf", []),  # a header not filled yet is still a header
            ("Done", ["b"]),
        ]

    def test_an_artifact_sits_under_one_header_only(self, store):
        pid = pivots_saved.save_manual("Reading")
        result = pivots_saved.set_layout(
            pid,
            [
                {"key": "A", "artifact_ids": ["x", "y", "x"]},
                {"key": "B", "artifact_ids": ["y", "z"]},
            ],
        )
        assert [g["artifact_ids"] for g in result["groups"]] == [["x", "y"], ["z"]]

    def test_two_headers_cannot_share_a_name(self, store):
        pid = pivots_saved.save_manual("Reading")
        with pytest.raises(ValueError, match="both called"):
            pivots_saved.set_layout(
                pid, [{"key": "Later", "artifact_ids": []}, {"key": "later ", "artifact_ids": []}]
            )

    def test_a_recipe_view_has_no_layout_to_set(self, store):
        pid = pivots_saved.save("By the assistant", _SPEC)
        with pytest.raises(ValueError, match="arranged by hand"):
            pivots_saved.set_layout(pid, [])
        with pytest.raises(KeyError):
            pivots_saved.set_layout("ghost", [])

    def test_it_can_start_from_another_views_groups(self, store):
        pid = pivots_saved.save_manual(
            "Books (by hand)", [{"key": "fiction", "artifact_ids": ["a", "b"]}]
        )
        assert pivots_saved.get(pid)["result"]["groups"] == [
            {"key": "fiction", "artifact_ids": ["a", "b"]}
        ]

    def test_removing_the_last_card_keeps_the_header(self, store):
        pid = pivots_saved.save_manual("Reading", [{"key": "To read", "artifact_ids": ["a"]}])
        result = pivots_saved.remove_from_result(pid, ["a"])
        assert [(g["key"], g["artifact_ids"]) for g in result["groups"]] == [("To read", [])]

    def test_the_listing_knows_a_hand_arranged_view(self, store):
        pivots_saved.save_manual("Reading", [{"key": "To read", "artifact_ids": ["a"]}])
        pivots_saved.save("By the assistant", _SPEC)
        kinds = {v["name"]: v["manual"] for v in pivots_saved.listing()}
        assert kinds == {"Reading": True, "By the assistant": False}
