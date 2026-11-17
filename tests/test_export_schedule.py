"""C6: the daily plain copy keeps a readable mirror in a chosen folder."""

from __future__ import annotations

import json

from enqueue import backup, db, export, notes, settings


def _set_dir(parent):
    settings.update({"export_dir": str(parent)})
    assert settings.get("export_dir") == str(parent)


def _mtimes(root):
    return {p.relative_to(root): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


def test_export_daily_writes_a_note_and_changes_nothing_on_a_second_run(store, quiet_queue):
    parent = store / "drive"
    parent.mkdir()
    _set_dir(parent)
    notes.create("# Willow\n\nA will bends; an oak breaks.")

    backup.export_daily()

    root = parent / "Enqueue"
    files = list((root / "artifacts").iterdir())
    assert len(files) == 1
    assert "Willow" in files[0].read_text(encoding="utf-8")
    assert (root / "README.md").exists()
    manifest = json.loads((root / export.MANIFEST).read_text(encoding="utf-8"))
    assert len(manifest["artifacts"]) == 1

    before = _mtimes(root)
    backup.export_daily()
    assert _mtimes(root) == before


def test_export_daily_leaves_vaulted_items_out(store, quiet_queue):
    parent = store / "drive"
    parent.mkdir()
    _set_dir(parent)
    notes.create("# Plain\n\nKept.")
    hidden = notes.create("# Hidden\n\nSealed.")["artifact"]["id"]
    with db.transaction() as conn:
        conn.execute("UPDATE artifacts SET vaulted_at = ? WHERE id = ?", (db.now(), hidden))

    backup.export_daily()

    root = parent / "Enqueue"
    text = "".join(p.read_text(encoding="utf-8") for p in (root / "artifacts").iterdir())
    assert "Plain" in text
    assert "Hidden" not in text


def test_export_daily_leaves_local_only_items_out(store, quiet_queue):
    parent = store / "drive"
    parent.mkdir()
    _set_dir(parent)
    notes.create("# Shared\n\nKept.")
    notes.create("# Private\n\nOnly here.", local_only=True)

    backup.export_daily()

    root = parent / "Enqueue"
    text = "".join(p.read_text(encoding="utf-8") for p in (root / "artifacts").iterdir())
    assert "Shared" in text
    assert "Private" not in text
    manifest = json.loads((root / export.MANIFEST).read_text(encoding="utf-8"))
    assert "Private" not in (e["title"] for e in manifest["artifacts"].values())


def test_export_daily_skips_a_missing_folder(store, quiet_queue):
    _set_dir(store / "gone")
    backup.export_daily()
    assert not (store / "gone").exists()
