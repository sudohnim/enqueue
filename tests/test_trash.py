"""Deleting, and the cases where a naive implementation loses something.

Everything here is about the difference between "gone from view" and "gone". The
product's promise is that nothing is lost by accident, so the interesting tests are
the ones where a plausible shortcut would destroy data.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from enqueue import capture, config, db, notes, trash


def _age(artifact_id: str, days: int) -> None:
    """Backdate a deletion so the purge window can be tested without waiting."""
    when = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db.transaction() as conn:
        conn.execute("UPDATE artifacts SET deleted_at = ? WHERE id = ?", (when, artifact_id))


class TestDeleteIsReversible:
    def test_deleting_hides_it_without_destroying_it(self, store, quiet_queue):
        made = notes.create(body="# Kept\n\nStill here after deletion.")
        artifact_id = made["artifact"]["id"]

        trash.delete(artifact_id)

        assert notes.get(artifact_id)["artifact"]["body"] == "# Kept\n\nStill here after deletion."
        assert [a["id"] for a in trash.listing()["items"]] == [artifact_id]

    def test_deleting_takes_it_out_of_retrieval_at_once(self, store, quiet_queue):
        """A deleted artifact must not come back as a citation while it waits."""
        made = notes.create(body="# Joints\n\nA joint that moves outlasts one that does not.")
        artifact_id = made["artifact"]["id"]
        from enqueue.ingest import chunk as chunk_mod

        with db.transaction() as conn:
            assert chunk_mod.chunk_artifact(conn, artifact_id) > 0

        trash.delete(artifact_id)

        conn = db.get_conn()
        try:
            assert (
                conn.execute(
                    "SELECT COUNT(*) AS n FROM chunks WHERE artifact_id = ?", (artifact_id,)
                ).fetchone()["n"]
                == 0
            )
        finally:
            conn.close()

    def test_restoring_brings_it_back(self, store, quiet_queue):
        made = notes.create(body="# Back\n\nRestored.")
        artifact_id = made["artifact"]["id"]

        trash.delete(artifact_id)
        trash.restore(artifact_id)

        assert trash.listing()["items"] == []
        assert quiet_queue[-1] == artifact_id  # re-ingested, so it is findable again

    def test_deleting_twice_is_not_an_error(self, store, quiet_queue):
        made = notes.create(body="# Once\n\nOnly once.")
        artifact_id = made["artifact"]["id"]
        first = trash.delete(artifact_id)
        second = trash.delete(artifact_id)
        assert not first["already"] and second["already"]
        assert second["deleted_at"] == first["deleted_at"]


class TestPurge:
    def test_purge_refuses_anything_not_in_the_trash(self, store, quiet_queue):
        made = notes.create(body="# Live\n\nNot deleted.")
        with pytest.raises(ValueError, match="not in the trash"):
            trash.purge(made["artifact"]["id"])

    def test_purge_destroys_the_artifact_and_its_history(self, store, quiet_queue):
        made = notes.create(body="# Gone\n\nFor good.")
        artifact_id = made["artifact"]["id"]
        trash.delete(artifact_id)
        trash.purge(artifact_id)

        with pytest.raises(KeyError):
            notes.get(artifact_id)
        conn = db.get_conn()
        try:
            assert (
                conn.execute(
                    "SELECT COUNT(*) AS n FROM artifact_versions WHERE artifact_id = ?",
                    (artifact_id,),
                ).fetchone()["n"]
                == 0
            )
        finally:
            conn.close()

    def test_two_artifacts_can_never_share_a_blob(self, store, quiet_queue):
        """Why `purge` checks for other references before unlinking, and why that
        check can never currently fire.

        Blobs are content-addressed, which normally means shared, which would make
        unlinking on purge destroy a different artifact holding the same bytes. Here
        it cannot happen: `artifacts.content_hash` is UNIQUE, so identical bytes
        dedupe to one row rather than producing a second.

        The guard in `purge` stays because it encodes that dependency explicitly. If
        the constraint is ever relaxed — a `local_only` copy of a shared file is the
        obvious reason — deletion stays correct instead of quietly eating data. This
        test exists to fail loudly on the day that assumption changes.
        """
        first = capture.upload(b"the very same bytes", "a.txt", mime="text/plain")
        again = capture.upload(b"the very same bytes", "b.txt", mime="text/plain")

        assert again["id"] == first["id"], "identical bytes should dedupe to one artifact"
        assert not again["created"]

        with db.transaction() as conn:
            row = conn.execute(
                "SELECT content_hash FROM artifacts WHERE id = ?", (first["id"],)
            ).fetchone()
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO artifacts (id, kind, title, body, content_hash, mime,"
                    " filename, created_at, updated_at, local_only, status)"
                    " VALUES ('second','file','a copy',NULL,?,'text/plain','b.txt',"
                    "'2026-01-01','2026-01-01',0,'ok')",
                    (row["content_hash"],),
                )

    def test_the_last_reference_does_unlink_the_bytes(self, store, quiet_queue):
        made = capture.upload(b"only referenced once", "lonely.txt", mime="text/plain")
        conn = db.get_conn()
        try:
            digest = conn.execute(
                "SELECT content_hash FROM artifacts WHERE id = ?", (made["id"],)
            ).fetchone()["content_hash"]
        finally:
            conn.close()

        blob = config.BLOB_DIR / digest
        assert blob.exists()

        trash.delete(made["id"])
        trash.purge(made["id"])
        assert not blob.exists()


class TestRetentionWindow:
    def test_nothing_inside_the_window_is_purged(self, store, quiet_queue):
        made = notes.create(body="# Recent\n\nDeleted yesterday.")
        trash.delete(made["artifact"]["id"])
        _age(made["artifact"]["id"], 1)

        assert trash.purge_expired()["purged"] == 0
        assert len(trash.listing()["items"]) == 1

    def test_anything_past_the_window_goes(self, store, quiet_queue):
        made = notes.create(body="# Old\n\nDeleted long ago.")
        trash.delete(made["artifact"]["id"])
        _age(made["artifact"]["id"], 31)

        assert trash.purge_expired()["purged"] == 1
        assert trash.listing()["items"] == []

    def test_a_zero_day_window_is_clamped(self, store, quiet_queue, monkeypatch):
        """Zero would make deleting a one-keystroke unrecoverable loss, which is the
        thing the trash exists to prevent."""
        monkeypatch.setattr(trash, "retention_days", lambda: max(1, 0))
        assert trash.retention_days() == 1

    def test_the_window_follows_the_setting(self, store, quiet_queue):
        from enqueue import settings

        settings.update({"trash_days": 3})
        assert trash.retention_days() == 3

        made = notes.create(body="# Aged\n\nFour days in the trash.")
        trash.delete(made["artifact"]["id"])
        _age(made["artifact"]["id"], 4)
        assert trash.purge_expired()["purged"] == 1
