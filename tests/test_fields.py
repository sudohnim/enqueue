"""The `field` op: attributes read straight off an artifact's row.

Phase F. `fields.FIELDS` maps a field name to a resolver that turns one
artifact row into its label - pure, model-free, and total. The tests prove
each resolver reads the row it claims to read, that a missing url yields the
"not determined" label instead of crashing, and that `derive.field` serves a
user override first and never calls a model.

The provider stub here is the inverse of the one the model primitives use:
any call to it is a test failure, because a `field` read must never touch a
model.
"""

from __future__ import annotations


import pytest

from enqueue import capture, db, derive, fields, notes


class _FakeProvider:
    """A provider that must never be called: a field read is a SQL read."""

    name = "fake"
    model = "fake-model"

    def complete(self, system, user, response_model, context=None, max_retries=None):
        raise AssertionError("a field read must never call a model")


def _note(body: str) -> str:
    return notes.create(body=body)["artifact"]["id"]


class TestResolvers:
    def test_resolvers(self):
        """Each field reads the row it claims to read, label and all."""
        rows = {
            "kind": {
                "kind": "pdf",
                "source_url": None,
                "created_at": "2025-03-14T09:00:00+00:00",
            },
            "source": {
                "kind": "link",
                "source_url": "https://example.com/some/page",
                "created_at": "2025-03-14T09:00:00+00:00",
            },
            "captured": {
                "kind": "note",
                "source_url": None,
                "created_at": "2025-03-14T09:00:00+00:00",
            },
        }

        assert fields.FIELDS["kind"].resolve(rows["kind"]) == "pdf"
        assert fields.FIELDS["source"].resolve(rows["source"]) == "example.com"
        assert fields.FIELDS["captured"].resolve(rows["captured"]) == "2025-03"
        assert fields.FIELDS["title"].resolve({"title": "Chip War"}) == "Chip War"

    def test_title_reads_the_column_never_infers(self):
        """`title` reads the stored title verbatim - it is a field (a fact on the
        row), never an inference about the named work. A missing title reads ""."""
        assert fields.FIELDS["title"].resolve({"title": "The Odyssey"}) == "The Odyssey"
        assert fields.FIELDS["title"].resolve({"title": None}) == ""

    def test_no_url_is_the_not_determined_label(self):
        """A row without a url reads "" - the "not determined" bucket, never a crash."""
        row = {"kind": "note", "source_url": None, "created_at": "2025-03-14T09:00:00+00:00"}

        assert fields.FIELDS["source"].resolve(row) == ""


class TestField:
    def test_field_reads_the_row(self, store, quiet_queue, monkeypatch):
        """derive.field reads the artifact's own row, with zero model calls."""
        artifact_id = _note("A field note about the estuary.")
        monkeypatch.setattr(derive, "get_provider", lambda: _FakeProvider())

        result = derive.field(artifact_id, "kind")

        assert result == {"value": "note", "grounded": True, "source": "field"}

    def test_source_and_captured_read_through_derive_field(self, store, quiet_queue, monkeypatch):
        """A link's host and month resolve through the same row read."""
        made = capture.link("https://example.com/some/page")
        monkeypatch.setattr(derive, "get_provider", lambda: _FakeProvider())

        conn = db.get_conn()
        try:
            created_at = conn.execute(
                "SELECT created_at FROM artifacts WHERE id = ?", (made["id"],)
            ).fetchone()["created_at"]
        finally:
            conn.close()

        assert derive.field(made["id"], "source") == {
            "value": "example.com",
            "grounded": True,
            "source": "field",
        }
        assert derive.field(made["id"], "captured")["value"] == created_at[:7]

    def test_user_override_wins(self, store, quiet_queue, monkeypatch):
        """A user correction beats the stored row, exactly as it beats a model row."""
        artifact_id = _note("A field note about the estuary.")
        monkeypatch.setattr(derive, "get_provider", lambda: _FakeProvider())

        derive.override("artifact", artifact_id, "kind", "pdf")
        result = derive.field(artifact_id, "kind")

        assert result == {"value": "pdf", "grounded": True, "source": "field"}

    def test_unknown_field_raises_keyerror(self, store, quiet_queue, monkeypatch):
        """A name outside the registry is refused, not guessed (the belt)."""
        artifact_id = _note("A field note about the estuary.")
        monkeypatch.setattr(derive, "get_provider", lambda: _FakeProvider())

        with pytest.raises(KeyError):
            derive.field(artifact_id, "flavor")

    def test_missing_row_reads_empty_not_raises(self, store, quiet_queue, monkeypatch):
        """A stale id (artifact gone after the subset resolved) reads "", never raises.

        One dangling index id must not crash a whole pivot run - it lands in the
        "not determined" bucket like any other empty value.
        """
        monkeypatch.setattr(derive, "get_provider", lambda: _FakeProvider())

        result = derive.field("does-not-exist", "kind")

        assert result == {"value": "", "grounded": True, "source": "field"}
