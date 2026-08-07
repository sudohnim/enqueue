"""Saved groupings: storage over the saved_pivots table.

A saved grouping is the spec (the arrangement recipe), not a frozen result, so
these tests prove the spec round-trips exactly through JSON and that the list is
newest-first and spec-free. No model call happens here - it is plain storage.
"""

from __future__ import annotations

import pytest

from enqueue import pivots_saved

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
