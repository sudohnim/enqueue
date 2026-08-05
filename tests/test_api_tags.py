"""The tag API surface: add, remove, and the two read shapes.

A tag is never required and never asked for at capture time. These tests hit
the same HTTP boundary the UI does, and confirm the tag shows up exactly
where the product says it will: on the artifact detail, in the tag cloud,
and nowhere on the capture path.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from enqueue import notes
from enqueue.api import app


def _tagged_artifact(client, name="A note") -> str:
    made = notes.create(body=f"# {name}\n\nBody.")
    artifact_id = made["artifact"]["id"]
    resp = client.post(f"/artifacts/{artifact_id}/tags", json={"name": "work"})
    assert resp.status_code == 201
    return artifact_id


class TestAddAndRead:
    def test_add_then_artifact_detail_shows_it(self, store, quiet_queue):
        client = TestClient(app)
        artifact_id = _tagged_artifact(client)

        detail = client.get(f"/artifacts/{artifact_id}").json()
        assert detail["tags"] == ["work"]

    def test_add_then_cloud_shows_it_with_count_one(self, store, quiet_queue):
        client = TestClient(app)
        _tagged_artifact(client)

        cloud = client.get("/tags").json()
        assert cloud == {"tags": [{"name": "work", "count": 1}]}

    def test_untagged_artifact_has_an_empty_list(self, store, quiet_queue):
        client = TestClient(app)
        made = notes.create(body="# Plain\n\nNo tags.")
        detail = client.get(f"/artifacts/{made['artifact']['id']}").json()
        assert detail["tags"] == []

    def test_add_normalizes_through_the_api(self, store, quiet_queue):
        client = TestClient(app)
        made = notes.create(body="# Case\n\nBody.")
        resp = client.post(f"/artifacts/{made['artifact']['id']}/tags", json={"name": "  Work "})
        assert resp.status_code == 201
        assert resp.json()["name"] == "work"


class TestRemove:
    def test_delete_removes_it_everywhere(self, store, quiet_queue):
        client = TestClient(app)
        artifact_id = _tagged_artifact(client)

        resp = client.delete(f"/artifacts/{artifact_id}/tags/work")
        assert resp.status_code == 200
        assert resp.json()["removed"] is True

        detail = client.get(f"/artifacts/{artifact_id}").json()
        assert detail["tags"] == []
        assert client.get("/tags").json() == {"tags": []}


class TestErrors:
    def test_add_to_a_missing_artifact_is_404(self, store, quiet_queue):
        client = TestClient(app)
        resp = client.post("/artifacts/ghost/tags", json={"name": "work"})
        assert resp.status_code == 404

    def test_add_an_empty_name_is_400(self, store, quiet_queue):
        client = TestClient(app)
        made = notes.create(body="# Empty\n\nBody.")
        resp = client.post(f"/artifacts/{made['artifact']['id']}/tags", json={"name": "  "})
        assert resp.status_code == 400
