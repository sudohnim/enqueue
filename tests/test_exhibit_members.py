"""Exhibit membership: add an artifact to a collection by hand.

K.5: the drawer's "Add to grouping" posts one artifact into an existing exhibit.
These tests prove the write path - idempotent add, eject and re-admit, the quick
create with a seed artifact - and the error contract (404 unknown exhibit,
400 unknown artifact). No model call happens here; it is plain storage.
"""

from __future__ import annotations

import pytest


def _client():
    from fastapi.testclient import TestClient

    from enqueue import api

    return TestClient(api.app)


def _seed_artifact(title="A note"):
    from enqueue import notes

    return notes.create(body=f"# {title}\n\nSome body text for the note.")["artifact"]["id"]


def test_quick_create_seeds_first_member(store, quiet_queue):
    client = _client()
    artifact_id = _seed_artifact()

    resp = client.post("/exhibits/quick", json={"name": "Hand made", "artifact_id": artifact_id})
    assert resp.status_code == 201
    exhibit_id = resp.json()["id"]

    got = client.get(f"/exhibits/{exhibit_id}").json()
    assert got["exhibit"]["name"] == "Hand made"
    members = got["members"]
    assert len(members) == 1
    assert members[0]["artifact_id"] == artifact_id
    assert members[0]["placard"] == "A note"
    assert members[0]["rank"] == 0


def test_quick_create_without_seed_makes_empty_exhibit(store):
    client = _client()
    resp = client.post("/exhibits/quick", json={"name": "Empty"})
    assert resp.status_code == 201
    got = client.get(f"/exhibits/{resp.json()['id']}").json()
    assert got["members"] == []


def test_add_member_is_idempotent(store, quiet_queue):
    client = _client()
    artifact_id = _seed_artifact()
    exhibit_id = client.post("/exhibits/quick", json={"name": "Room"}).json()["id"]

    first = client.post(f"/exhibits/{exhibit_id}/members", json={"artifact_id": artifact_id})
    assert first.status_code == 201
    assert first.json()["added"]  # True: it became a member

    again = client.post(f"/exhibits/{exhibit_id}/members", json={"artifact_id": artifact_id})
    assert again.status_code == 201
    assert not again.json()["added"]  # False: already a member, no-op

    members = client.get(f"/exhibits/{exhibit_id}").json()["members"]
    assert [m["artifact_id"] for m in members] == [artifact_id]


def test_members_rank_after_existing_rows(store, quiet_queue):
    client = _client()
    one = _seed_artifact("One")
    two = _seed_artifact("Two")
    exhibit_id = client.post("/exhibits/quick", json={"name": "Room", "artifact_id": one}).json()[
        "id"
    ]

    client.post(f"/exhibits/{exhibit_id}/members", json={"artifact_id": two})

    members = client.get(f"/exhibits/{exhibit_id}").json()["members"]
    assert [m["rank"] for m in members] == [0, 1]


def test_eject_removes_then_readmits(store, quiet_queue):
    client = _client()
    artifact_id = _seed_artifact()
    exhibit_id = client.post(
        "/exhibits/quick", json={"name": "Room", "artifact_id": artifact_id}
    ).json()["id"]

    assert client.delete(f"/exhibits/{exhibit_id}/members/{artifact_id}").status_code == 200
    assert client.get(f"/exhibits/{exhibit_id}").json()["members"] == []

    # Re-adding re-admits the ejected member under a fresh rank.
    readded = client.post(f"/exhibits/{exhibit_id}/members", json={"artifact_id": artifact_id})
    assert readded.json()["added"]
    members = client.get(f"/exhibits/{exhibit_id}").json()["members"]
    assert [m["artifact_id"] for m in members] == [artifact_id]


def test_artifact_exhibits_lists_non_ejected_memberships(store, quiet_queue):
    client = _client()
    artifact_id = _seed_artifact()
    first = client.post(
        "/exhibits/quick", json={"name": "First", "artifact_id": artifact_id}
    ).json()["id"]
    second = client.post(
        "/exhibits/quick", json={"name": "Second", "artifact_id": artifact_id}
    ).json()["id"]

    listed = client.get(f"/artifacts/{artifact_id}/exhibits").json()["items"]
    assert {e["id"] for e in listed} == {first, second}

    client.delete(f"/exhibits/{first}/members/{artifact_id}")
    listed = client.get(f"/artifacts/{artifact_id}/exhibits").json()["items"]
    assert [e["id"] for e in listed] == [second]


def test_errors(store, quiet_queue):
    client = _client()
    artifact_id = _seed_artifact()
    exhibit_id = client.post("/exhibits/quick", json={"name": "Room"}).json()["id"]

    # Unknown exhibit is 404 for both add and eject.
    assert (
        client.post("/exhibits/nope/members", json={"artifact_id": artifact_id}).status_code == 404
    )
    assert client.delete(f"/exhibits/nope/members/{artifact_id}").status_code == 404

    # Unknown artifact is 400 on add.
    resp = client.post(f"/exhibits/{exhibit_id}/members", json={"artifact_id": "nope"})
    assert resp.status_code == 400

    # Empty name on quick create is 400, and unknown seed artifact too.
    assert client.post("/exhibits/quick", json={"name": "  "}).status_code == 400
    assert (
        client.post("/exhibits/quick", json={"name": "X", "artifact_id": "nope"}).status_code == 400
    )


def test_add_member_requires_artifact_id(store):
    client = _client()
    exhibit_id = client.post("/exhibits/quick", json={"name": "Room"}).json()["id"]
    resp = client.post(f"/exhibits/{exhibit_id}/members", json={})
    assert resp.status_code == 422  # pydantic rejects the missing field


def test_rename_updates_name_and_through_line(store, quiet_queue):
    client = _client()
    exhibit_id = client.post("/exhibits/quick", json={"name": "Old"}).json()["id"]

    resp = client.patch(f"/exhibits/{exhibit_id}", json={"name": "  New  "})
    assert resp.status_code == 200
    assert resp.json()["exhibit"]["name"] == "New"  # trimmed
    assert resp.json()["exhibit"]["theme"] == "Old"  # theme is immutable

    client.patch(f"/exhibits/{exhibit_id}", json={"through_line": "A line"})
    got = client.get(f"/exhibits/{exhibit_id}").json()["exhibit"]
    assert got["name"] == "New"
    assert got["through_line"] == "A line"


def test_rename_rejects_empty_and_unknown(store, quiet_queue):
    client = _client()
    exhibit_id = client.post("/exhibits/quick", json={"name": "Old"}).json()["id"]

    assert client.patch(f"/exhibits/{exhibit_id}", json={"name": "   "}).status_code == 400
    assert client.patch("/exhibits/ghost", json={"name": "X"}).status_code == 404
    # An empty patch body is allowed: nothing changes.
    resp = client.patch(f"/exhibits/{exhibit_id}", json={})
    assert resp.status_code == 200
    assert resp.json()["exhibit"]["name"] == "Old"


@pytest.mark.parametrize("name", ["Hello world", "  Trimmed name  ", "Unicode: caf\xe9"])
def test_quick_create_names_are_trimmed_and_kept(store, name):
    client = _client()
    resp = client.post("/exhibits/quick", json={"name": name})
    assert resp.status_code == 201
    got = client.get(f"/exhibits/{resp.json()['id']}").json()
    assert got["exhibit"]["name"] == name.strip()
