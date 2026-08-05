"""The wall tag filter: `?tags=work` narrows the /artifacts listing.

A tag filter applies to artifacts only; conversations cannot be tagged, so a
filtered wall excludes the chats limb entirely - a filtered wall is an
artifact wall. Without a filter, the wall is exactly what it was before.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from enqueue import api, chats, notes, tags


def _wall(**params):
    return api.list_artifacts(**params)


class TestWallTagFilter:
    def test_filter_returns_only_tagged_artifacts_and_no_chats(self, store, quiet_queue):
        tagged = notes.create(body="# Work\n\nBody.")["artifact"]["id"]
        untagged = notes.create(body="# Plain\n\nBody.")["artifact"]["id"]
        chat = chats.create()["chat"]["id"]
        tags.add(tagged, "work")

        wall = _wall(tags="work")
        assert [i["id"] for i in wall["items"]] == [tagged]
        assert all(i["kind"] != "chat" for i in wall["items"])
        assert wall["total"] == 1
        assert untagged not in [i["id"] for i in wall["items"]]
        assert chat not in [i["id"] for i in wall["items"]]

    def test_no_filter_is_unchanged_and_still_includes_chats(self, store, quiet_queue):
        note = notes.create(body="# Work\n\nBody.")["artifact"]["id"]
        chat = chats.create()["chat"]["id"]
        tags.add(note, "work")

        wall = _wall()
        assert {i["id"] for i in wall["items"]} == {note, chat}
        assert wall["total"] == 2

    def test_and_semantics_across_names(self, store, quiet_queue):
        both = notes.create(body="# Both\n\nBody.")["artifact"]["id"]
        only_work = notes.create(body="# One\n\nBody.")["artifact"]["id"]
        tags.add(both, "work")
        tags.add(both, "urgent")
        tags.add(only_work, "work")

        wall = _wall(tags="work,urgent")
        assert [i["id"] for i in wall["items"]] == [both]
        assert wall["total"] == 1

    def test_names_are_normalized(self, store, quiet_queue):
        tagged = notes.create(body="# Case\n\nBody.")["artifact"]["id"]
        tags.add(tagged, "Work")

        wall = _wall(tags="  work ")
        assert [i["id"] for i in wall["items"]] == [tagged]

    def test_unknown_tag_yields_an_empty_wall(self, store, quiet_queue):
        notes.create(body="# Plain\n\nBody.")
        wall = _wall(tags="ghost")
        assert wall["items"] == []
        assert wall["total"] == 0

    def test_filter_via_the_http_route(self, store, quiet_queue):
        client = TestClient(api.app)
        tagged = notes.create(body="# Work\n\nBody.")["artifact"]["id"]
        tags.add(tagged, "work")

        wall = client.get("/artifacts", params={"tags": "work"}).json()
        assert [i["id"] for i in wall["items"]] == [tagged]
        assert wall["total"] == 1
