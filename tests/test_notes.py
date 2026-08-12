"""The note title model (NOTE.0/NOTE.3): explicit titles survive body edits.

A note's title is derived from its first line by default, but a title the person
edits by hand is explicit (artifacts.title_explicit) and must survive later
body-only saves. An empty title clears the flag and reverts to the derivation.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from enqueue import notes
from enqueue.api import app


def _note(body: str = "# First line\n\nBody.") -> str:
    return notes.create(body=body)["artifact"]["id"]


class TestExplicitTitleSurvivesBodyEdits:
    def test_body_only_edit_keeps_an_explicit_title(self, store, quiet_queue):
        artifact_id = _note()
        notes.edit(artifact_id, "# First line\n\nBody.", title="Hand title")

        notes.edit(artifact_id, "# First line\n\nEdited body.")

        detail = notes.get(artifact_id)["artifact"]
        assert detail["title"] == "Hand title"
        assert detail["title_explicit"] == 1

    def test_title_only_edit_persists_without_touching_the_body(self, store, quiet_queue):
        artifact_id = _note(body="First line")
        notes.edit(artifact_id, "First line", title="Renamed")

        detail = notes.get(artifact_id)["artifact"]
        assert detail["title"] == "Renamed"
        assert detail["body"] == "First line"
        # A title-only edit is not a new body state: no version is appended.
        assert len(notes.get(artifact_id)["versions"]) == 1

    def test_clearing_an_explicit_title_reverts_to_derived(self, store, quiet_queue):
        artifact_id = _note()
        notes.edit(artifact_id, "# First line\n\nBody.", title="Hand title")

        notes.edit(artifact_id, "# First line\n\nBody.", title="")

        detail = notes.get(artifact_id)["artifact"]
        assert detail["title"] == "First line"
        assert detail["title_explicit"] == 0


class TestDerivedTitleDefault:
    def test_body_only_edit_still_derives_when_never_explicit(self, store, quiet_queue):
        artifact_id = _note()
        notes.edit(artifact_id, "New first line\n\nBody.")

        detail = notes.get(artifact_id)["artifact"]
        assert detail["title"] == "New first line"
        assert detail["title_explicit"] == 0


class TestTitleThroughTheApi:
    def test_rename_persists_and_survives_a_body_only_edit(self, store, quiet_queue):
        client = TestClient(app)
        artifact_id = _note()

        renamed = client.patch(
            f"/artifacts/{artifact_id}/body",
            json={"body": "A note body", "title": "Explicit"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["artifact"]["title"] == "Explicit"
        assert renamed.json()["artifact"]["title_explicit"] == 1

        reloaded = client.get(f"/artifacts/{artifact_id}").json()
        assert reloaded["artifact"]["title"] == "Explicit"

        kept = client.patch(
            f"/artifacts/{artifact_id}/body",
            json={"body": "A note body, edited"},
        )
        assert kept.json()["artifact"]["title"] == "Explicit"
        assert kept.json()["artifact"]["title_explicit"] == 1

    def test_empty_title_via_the_api_clears_back_to_derived(self, store, quiet_queue):
        client = TestClient(app)
        artifact_id = _note()
        client.patch(
            f"/artifacts/{artifact_id}/body",
            json={"body": "A note body", "title": "Explicit"},
        )

        cleared = client.patch(
            f"/artifacts/{artifact_id}/body",
            json={"body": "A note body", "title": ""},
        )
        assert cleared.status_code == 200
        assert cleared.json()["artifact"]["title"] == "A note body"
        assert cleared.json()["artifact"]["title_explicit"] == 0
