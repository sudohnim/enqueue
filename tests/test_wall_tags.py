"""Wall items carry their tags (K.6b).

The wall's Tags grouping is a client-side group-by, so every wall row must
arrive with its tag names. These tests pin that contract: a tagged artifact
shows its tags on the flat wall, an untagged one shows an empty list, and
chat rows (which cannot be tagged) carry an empty list too.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from enqueue import api, notes


def _client():
    return TestClient(api.app)


def test_wall_items_carry_their_tags(store, quiet_queue):
    client = _client()
    made = notes.create(body="# Tagged\n\nBody.")
    artifact_id = made["artifact"]["id"]
    client.post(f"/artifacts/{artifact_id}/tags", json={"name": "work"})
    client.post(f"/artifacts/{artifact_id}/tags", json={"name": "urgent"})

    wall = client.get("/artifacts?limit=100").json()["items"]
    row = next(r for r in wall if r["id"] == artifact_id)
    assert set(row["tags"]) == {"work", "urgent"}


def test_untagged_wall_items_have_an_empty_tag_list(store, quiet_queue):
    client = _client()
    made = notes.create(body="# Bare\n\nBody.")
    wall = client.get("/artifacts?limit=100").json()["items"]
    row = next(r for r in wall if r["id"] == made["artifact"]["id"])
    assert row["tags"] == []


def test_chat_rows_carry_no_tags(store, quiet_queue):
    from enqueue import chats

    client = _client()
    chats.create(scope_kind="everything", scope_id=None)
    wall = client.get("/artifacts?limit=100").json()["items"]
    chats_rows = [r for r in wall if r["kind"] == "chat"]
    assert chats_rows, "expected at least one chat row on the wall"
    assert all(r["tags"] == [] for r in chats_rows)
