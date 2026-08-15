"""The snapshot model and LWW merge (E2E.md Phase E3).

The convergence invariant is the load-bearing property: given the same set of
snapshots, every device picks the same winner and reaches byte-identical state
regardless of apply order. It is proved here with hypothesis.
"""

from __future__ import annotations


from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from enqueue import db
from enqueue import tags as tags_module
from enqueue.sync.snapshot import (
    apply_pulled_snapshot,
    apply_snapshot,
    deserialize,
    lww_key,
    read_artifact_snapshot,
    serialize,
    winner,
)


def _artifact(aid, updated_at="2024-01-01T00:00:00", body="body", device_id=None):
    row = {
        "id": aid,
        "kind": "note",
        "title": "Title",
        "body": body,
        "source_url": None,
        "content_hash": aid + "-hash",
        "mime": None,
        "filename": None,
        "created_at": "2024-01-01T00:00:00",
        "updated_at": updated_at,
        "local_only": 0,
        "status": "ok",
        "pinned": 0,
        "deleted_at": None,
        "pages": None,
        "title_explicit": 0,
    }
    if device_id is not None:
        row["_device_id"] = device_id
    return row


def _snap(aid, updated_at="2024-01-01T00:00:00", body="body", device_id=None):
    return {
        "artifact": _artifact(aid, updated_at, body, device_id),
        "annotations": [],
        "page_text": [],
        "versions": [],
    }


def _seed(conn, aid="a1", updated_at="2024-01-01T00:00:00", body="body"):
    conn.execute(
        "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
        " created_at, updated_at) VALUES (?, 'note', 'Title', ?, ?, 'ok',"
        " '2024-01-01T00:00:00', ?)",
        (aid, body, aid + "-hash", updated_at),
    )
    conn.execute(
        "INSERT INTO annotations (id, artifact_id, text, created_at)"
        " VALUES ('ann1', ?, 'a note', '2024-01-01T00:00:00')",
        (aid,),
    )
    conn.execute(
        "INSERT INTO page_text (artifact_id, page, text, extractor)"
        " VALUES (?, 1, 'page one', 'test')",
        (aid,),
    )
    conn.execute(
        "INSERT INTO artifact_versions (id, artifact_id, body, created_at)"
        " VALUES ('v1', ?, 'old body', '2024-01-01T00:00:00')",
        (aid,),
    )


class TestSnapshotRoundTrip:
    def test_read_builds_the_full_snapshot(self, store):
        conn = db.get_conn()
        try:
            _seed(conn)
            conn.commit()
            s = read_artifact_snapshot(conn, "a1")
        finally:
            conn.close()

        assert s is not None
        assert s["artifact"]["id"] == "a1"
        assert [a["id"] for a in s["annotations"]] == ["ann1"]
        assert [p["page"] for p in s["page_text"]] == [1]
        assert [v["id"] for v in s["versions"]] == ["v1"]

    def test_read_a_missing_artifact_is_none(self, store):
        conn = db.get_conn()
        try:
            assert read_artifact_snapshot(conn, "nope") is None
        finally:
            conn.close()

    def test_serialize_is_canonical_and_deterministic(self):
        s = _snap("a1", body="héllo")
        assert serialize(s) == serialize(s)
        # Canonical JSON: sorted keys, no spaces, UTF-8, so the bytes are exact.
        assert b'"artifact":{' in serialize(s)

    def test_deserialize_round_trips(self):
        s = _snap("a1", body="héllo", device_id="d1")
        assert deserialize(serialize(s)) == s


class TestLww:
    def test_lww_key_is_updated_at_then_device_id(self):
        updated, device = lww_key(_snap("a1", updated_at="2024-01-02", device_id="d1"))
        assert updated == "2024-01-02"
        assert device == "d1"
        # An unexported snapshot has no _device_id yet: empty string.
        updated, device = lww_key(_snap("a1", updated_at="2024-01-02"))
        assert updated == "2024-01-02"
        assert device == ""

    def test_winner_is_the_max_key_and_order_independent(self):
        snaps = [
            _snap("a1", updated_at="2024-01-01", device_id="d2"),
            _snap("a1", updated_at="2024-01-03", device_id="d1"),
            _snap("a1", updated_at="2024-01-02", device_id="d9"),
        ]
        assert winner(snaps)["artifact"]["updated_at"] == "2024-01-03"
        assert winner(list(reversed(snaps)))["artifact"]["updated_at"] == "2024-01-03"


class TestApply:
    def test_apply_upserts_and_replaces_children(self, store):
        conn = db.get_conn()
        try:
            _seed(conn)
            conn.commit()
            incoming = _snap("a1", updated_at="2024-01-02", body="new body")
            incoming["annotations"] = [
                {
                    "id": "ann2",
                    "artifact_id": "a1",
                    "supersedes_id": None,
                    "text": "new note",
                    "created_at": "2024-01-02",
                }
            ]
            with db.transaction() as tx:
                apply_snapshot(tx, incoming)

            row = conn.execute("SELECT body, updated_at FROM artifacts WHERE id='a1'").fetchone()
            assert row["body"] == "new body"
            assert row["updated_at"] == "2024-01-02"
            # Children replaced, not appended.
            assert [
                r["id"] for r in conn.execute("SELECT id FROM annotations WHERE artifact_id='a1'")
            ] == ["ann2"]
            assert (
                conn.execute(
                    "SELECT COUNT(*) AS n FROM artifact_versions WHERE artifact_id='a1'"
                ).fetchone()["n"]
                == 0
            )
        finally:
            conn.close()

    def test_apply_is_idempotent(self, store):
        conn = db.get_conn()
        try:
            incoming = _snap("a1", updated_at="2024-01-02", body="new body")
            with db.transaction() as tx:
                apply_snapshot(tx, incoming)
            first = conn.execute("SELECT * FROM artifacts WHERE id='a1'").fetchone()
            with db.transaction() as tx:
                apply_snapshot(tx, incoming)
            second = conn.execute("SELECT * FROM artifacts WHERE id='a1'").fetchone()
            assert dict(first) == dict(second)
        finally:
            conn.close()

    def test_apply_ignores_an_older_snapshot(self, store):
        conn = db.get_conn()
        try:
            _seed(conn, updated_at="2024-01-10", body="local body")
            conn.commit()
            stale = _snap("a1", updated_at="2024-01-01", body="stale body", device_id="d1")
            with db.transaction() as tx:
                apply_snapshot(tx, stale)
            row = conn.execute("SELECT body FROM artifacts WHERE id='a1'").fetchone()
            assert row["body"] == "local body"
        finally:
            conn.close()

    def test_a_losing_local_edit_is_retained_as_a_version(self, store):
        """DEC-A (SYNC.6): two offline edits resolve to the newer, and the losing
        edit stays in the version history, recoverable, never silently gone."""
        conn = db.get_conn()
        try:
            # Device A's local edit: body "A's edit" plus its version row.
            conn.execute(
                "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
                " created_at, updated_at) VALUES"
                " ('a1', 'note', 'T', 'A''s edit', 'h', 'ok', '2024-01-01', '2024-01-02')"
            )
            conn.execute(
                "INSERT INTO artifact_versions (id, artifact_id, body, created_at)"
                " VALUES ('vA', 'a1', 'A''s edit', '2024-01-02')"
            )
            conn.commit()

            # Device B's conflicting snapshot, newer by lww_key.
            incoming = _snap("a1", updated_at="2024-01-03", body="B's edit", device_id="d2")
            incoming["versions"] = [
                {"id": "v0", "artifact_id": "a1", "body": "original", "created_at": "2024-01-01"},
                {"id": "vB", "artifact_id": "a1", "body": "B's edit", "created_at": "2024-01-03"},
            ]

            with db.transaction() as tx:
                apply_pulled_snapshot(tx, incoming)

            row = conn.execute("SELECT body FROM artifacts WHERE id='a1'").fetchone()
            assert row["body"] == "B's edit"  # the newer edit wins
            bodies = [
                r["body"]
                for r in conn.execute(
                    "SELECT body FROM artifact_versions WHERE artifact_id='a1'"
                    " ORDER BY created_at, id"
                )
            ]
            assert "A's edit" in bodies  # the loser is retained and recoverable
        finally:
            conn.close()


class TestConvergence:
    """E2E.md's load-bearing invariant: any apply order yields the winner's rows."""

    @given(
        st.lists(
            st.tuples(
                st.text(min_size=1, max_size=8),  # updated_at
                st.text(min_size=1, max_size=4),  # device_id
                st.text(min_size=1, max_size=20),  # body
            ),
            min_size=1,
            max_size=8,
            unique_by=lambda t: (t[0], t[1]),  # distinct lww keys
        )
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_any_order_converges_to_the_winner(self, store, triples):
        conn = db.get_conn()
        try:
            snaps = [
                {
                    "artifact": _artifact("a1", updated_at=ts, body=body, device_id=dv),
                    "annotations": [],
                    "page_text": [],
                    "versions": [],
                }
                for ts, dv, body in triples
            ]
            best = winner(snaps)

            def apply_all(order):
                with db.transaction() as tx:
                    tx.execute("DELETE FROM artifacts WHERE id='a1'")
                    tx.execute("DELETE FROM annotations WHERE artifact_id='a1'")
                    tx.execute("DELETE FROM page_text WHERE artifact_id='a1'")
                    tx.execute("DELETE FROM artifact_versions WHERE artifact_id='a1'")
                    for s in order:
                        apply_snapshot(tx, s)

            apply_all(snaps)
            expected = conn.execute("SELECT body FROM artifacts WHERE id='a1'").fetchone()["body"]
            assert expected == best["artifact"]["body"]

            # A reversed order must converge to the same winner.
            apply_all(list(reversed(snaps)))
            again = conn.execute("SELECT body FROM artifacts WHERE id='a1'").fetchone()["body"]
            assert again == best["artifact"]["body"]
        finally:
            conn.close()


def test_tags_round_trip_through_snapshot(store):
    """Tags are included in the snapshot and reapplied on the other side (MOB2.1)."""
    import uuid as uuid_lib

    conn = db.get_conn()
    try:
        now = db.now()
        artifact_id = str(uuid_lib.uuid4())
        tag1 = "work"
        tag2 = "personal"

        # Create artifact with tags
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status, "
            "created_at, updated_at) VALUES (?, 'note', 'T', 'body', 'h', 'ok', ?, ?)",
            (artifact_id, now, now),
        )
        conn.execute(
            "INSERT INTO tags (id, name, created_at) VALUES (?, ?, ?)",
            (str(uuid_lib.uuid4()), tag1, now),
        )
        conn.execute(
            "INSERT INTO tags (id, name, created_at) VALUES (?, ?, ?)",
            (str(uuid_lib.uuid4()), tag2, now),
        )
        conn.execute(
            "INSERT INTO artifact_tags (artifact_id, tag_id, created_at) "
            "SELECT ?, id, ? FROM tags WHERE name IN (?, ?)",
            (artifact_id, now, tag1, tag2),
        )
        conn.commit()

        # Read snapshot
        snap = read_artifact_snapshot(conn, artifact_id)
        assert snap is not None
        assert set(snap["tags"]) == {tag1, tag2}
        print(f"DEBUG: snapshot tags = {snap['tags']}")

        # Clear tags and reapply snapshot
        conn.execute("DELETE FROM artifact_tags WHERE artifact_id = ?", (artifact_id,))
        conn.execute("DELETE FROM tags WHERE name IN (?, ?)", (tag1, tag2))
        conn.commit()
        print("DEBUG: cleared tags")

        # Apply snapshot - should recreate tags
        with db.transaction() as tx:
            apply_snapshot(tx, snap)
        print("DEBUG: apply_snapshot done")

        # Verify tags are restored
        tags = tags_module.for_artifact(artifact_id)
        print(f"DEBUG: restored tags = {tags}")
        assert set(tags) == {tag1, tag2}
    finally:
        conn.close()
