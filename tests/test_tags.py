"""Tags: optional labels attached to an artifact after it exists.

The one rule of the feature: never ask for a tag at capture time, and never
make one required. Everything here tests the opposite direction - a tag is
a later act on an artifact that is already saved.
"""

from __future__ import annotations

import pytest

from enqueue import notes, tags, trash


def _note(body: str) -> str:
    return notes.create(body=body)["artifact"]["id"]


class TestAdd:
    def test_adding_then_listing(self, store, quiet_queue):
        artifact_id = _note("# Work\n\nA note.")
        tags.add(artifact_id, "work")
        assert tags.for_artifact(artifact_id) == ["work"]

    def test_adding_the_same_tag_twice_is_idempotent(self, store, quiet_queue):
        artifact_id = _note("# Twice\n\nA note.")
        tags.add(artifact_id, "work")
        tags.add(artifact_id, "work")
        assert tags.for_artifact(artifact_id) == ["work"]

    def test_add_normalizes_the_name(self, store, quiet_queue):
        artifact_id = _note("# Case\n\nA note.")
        tags.add(artifact_id, "  Work ")
        assert tags.for_artifact(artifact_id) == ["work"]

    def test_add_missing_artifact_raises_key_error(self, store, quiet_queue):
        with pytest.raises(KeyError):
            tags.add("no-such-artifact", "work")

    def test_add_empty_name_raises_value_error(self, store, quiet_queue):
        artifact_id = _note("# Empty\n\nA note.")
        with pytest.raises(ValueError):
            tags.add(artifact_id, "   ")


class TestRemove:
    def test_remove_drops_the_link_and_the_orphan_tag(self, store, quiet_queue):
        artifact_id = _note("# Gone\n\nA note.")
        tags.add(artifact_id, "work")
        tags.remove(artifact_id, "work")

        assert tags.for_artifact(artifact_id) == []
        assert tags.cloud() == []

    def test_remove_a_tag_still_used_elsewhere_keeps_the_tag(self, store, quiet_queue):
        first = _note("# First\n\nA note.")
        second = _note("# Second\n\nAnother note.")
        tags.add(first, "work")
        tags.add(second, "work")

        tags.remove(first, "work")

        assert tags.for_artifact(second) == ["work"]
        assert tags.cloud() == [{"name": "work", "count": 1}]


class TestCloud:
    def test_cloud_counts_most_used_first(self, store, quiet_queue):
        first = _note("# First\n\nA note.")
        second = _note("# Second\n\nAnother note.")
        third = _note("# Third\n\nYet another.")
        tags.add(first, "work")
        tags.add(second, "work")
        tags.add(second, "urgent")
        tags.add(third, "urgent")

        assert tags.cloud() == [
            {"name": "urgent", "count": 2},
            {"name": "work", "count": 2},
        ]


class TestPurge:
    def test_purging_keeps_the_shared_tag_and_drops_orphans(self, store, quiet_queue):
        gone = _note("# Gone\n\nA note.")
        kept = _note("# Kept\n\nAnother note.")
        tags.add(gone, "work")
        tags.add(kept, "work")
        tags.add(gone, "solo")

        trash.delete(gone)
        trash.purge(gone)

        assert tags.cloud() == [{"name": "work", "count": 1}]
        assert tags.for_artifact(kept) == ["work"]


class TestIdsWithAll:
    def test_all_means_all(self, store, quiet_queue):
        both = _note("# Both\n\nA note.")
        only_a = _note("# A\n\nA note.")
        only_b = _note("# B\n\nA note.")
        for artifact_id in (both, only_a):
            tags.add(artifact_id, "a")
        for artifact_id in (both, only_b):
            tags.add(artifact_id, "b")

        assert tags.ids_with_all(["a", "b"]) == {both}
        assert tags.ids_with_all(["a"]) == {both, only_a}
        assert tags.ids_with_all([]) == set()

    def test_names_are_matched_canonically(self, store, quiet_queue):
        artifact_id = _note("# Case\n\nA note.")
        tags.add(artifact_id, "Work")

        assert tags.ids_with_all(["work"]) == {artifact_id}
        assert tags.ids_with_all(["Work"]) == set()
