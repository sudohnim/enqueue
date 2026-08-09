"""Export: plain files that survive the library itself.

The escape hatch is only real if the output is readable when the database is
gone, so the test that matters here deletes the database and then reads.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from enqueue import capture, db, export, notes, trash

NOW = "2026-07-31T00:00:00+00:00"


def _link_artifact(conn, title: str, url: str, body: str) -> str:
    artifact_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO artifacts (id, kind, title, body, source_url, content_hash,"
        " created_at, updated_at, local_only, status)"
        " VALUES (?, 'link', ?, NULL, ?, ?, ?, ?, 0, 'ok')",
        (artifact_id, title, url, hashlib.sha256(url.encode()).hexdigest(), NOW, NOW),
    )
    conn.execute(
        "INSERT INTO page_text (artifact_id, page, text, extractor)"
        " VALUES (?, 0, ?, 'trafilatura')",
        (artifact_id, body),
    )
    return artifact_id


def _build_library() -> dict:
    """Four artifacts, one annotation. Returns the ids."""
    note = notes.create("# Joints\n\nA joint that moves outlasts one that does not.")
    note2 = notes.create("Plain note")
    upload = capture.upload(b"%PDF-1.4 fake bytes", "report.pdf", "application/pdf")
    with db.transaction() as conn:
        link = _link_artifact(
            conn,
            "The commons",
            "https://example.org/commons",
            "The commons is what we share, and sharing is the point.",
        )
    notes.annotate(upload["id"], "The keeper is elected quarterly.")
    return {
        "note": note["artifact"]["id"],
        "note2": note2["artifact"]["id"],
        "upload": upload["id"],
        "link": link,
    }


class TestExport:
    def test_writes_everything_and_is_idempotent(self, store, quiet_queue):
        _build_library()
        out = store / "export"

        first = export.export(out)
        assert first["artifacts"] == 4
        assert (out / "README.md").exists()
        assert (out / "manifest.json").exists()
        assert len(list((out / "artifacts").iterdir())) == 4

        # the capture's bytes are copied next to the markdown
        copies = list((out / "files").iterdir())
        assert len(copies) == 1
        assert copies[0].read_bytes() == b"%PDF-1.4 fake bytes"

        mtimes = {p.relative_to(out): p.stat().st_mtime_ns for p in out.rglob("*") if p.is_file()}

        # a second run changes nothing at all: not a byte on disk
        second = export.export(out)
        assert second["written"] == []
        after = {p.relative_to(out): p.stat().st_mtime_ns for p in out.rglob("*") if p.is_file()}
        assert after == mtimes

    def test_verify_tracks_new_artifacts(self, store, quiet_queue):
        _build_library()
        out = store / "export"
        export.export(out)

        assert export.verify(out)["ok"] is True

        # saving something new without re-exporting makes the output incomplete
        fresh = notes.create("Saved after the export")
        check = export.verify(out)
        assert check["ok"] is False
        assert check["missing"] == [fresh["artifact"]["id"]]

        # re-exporting repairs the mirror
        export.export(out)
        assert export.verify(out)["ok"] is True

    def test_export_prunes_removed_artifacts(self, store, quiet_queue):
        built = _build_library()
        out = store / "export"
        export.export(out)
        assert len(list((out / "artifacts").iterdir())) == 4

        # a purged artifact leaves the library, so its file must leave the output
        trash.delete(built["note2"])
        trash.purge(built["note2"])
        redo = export.export(out)
        assert len(redo["pruned"]) == 1
        manifest = json.loads((out / "manifest.json").read_text())["artifacts"]
        assert built["note2"] not in manifest
        assert len(list((out / "artifacts").iterdir())) == 3
        assert export.verify(out)["ok"] is True

    def test_export_survives_database_deletion(self, store, quiet_queue):
        _build_library()
        out = store / "export"
        export.export(out)

        # The whole library goes away. The files must still be there and readable.
        db.reset_migration_state()
        db.migrate()

        assert (out / "README.md").exists()
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert len(manifest["artifacts"]) == 4
        for entry in manifest["artifacts"].values():
            text = (out / entry["file"]).read_text(encoding="utf-8")
            assert entry["title"] in text
            assert "Saved: " in text
            assert text.endswith("\n")
            if entry.get("copy"):
                assert (out / entry["copy"]).read_bytes() == b"%PDF-1.4 fake bytes"

        # completeness is vacuous over an empty library, but the files must exist
        check = export.verify(out)
        assert check["ok"] is True
