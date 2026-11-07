"""The macOS Share extension's inbox is filed into the library (share_inbox.py)."""

from __future__ import annotations

import json

import pytest

from enqueue import db, share_inbox


@pytest.fixture
def inbox(store, quiet_queue, tmp_path, monkeypatch):
    folder = tmp_path / "Inbox"
    folder.mkdir()
    monkeypatch.setenv("ENQ_SHARE_INBOX", str(folder))
    return folder


def _share(inbox, name, **share):
    (inbox / f"{name}.json").write_text(json.dumps({"v": 1, **share}))


def _rows():
    conn = db.get_conn()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT a.kind, a.title, a.source_url, a.body, a.filename,"
                " (SELECT group_concat(text, '|') FROM annotations n WHERE n.artifact_id = a.id)"
                " AS notes FROM artifacts a ORDER BY a.kind"
            )
        ]
    finally:
        conn.close()


def test_a_shared_page_becomes_a_link_with_its_title_and_note(inbox):
    _share(
        inbox, "a", items=[{"url": "https://example.com/willow"}], title="A willow", note="Bends."
    )

    assert share_inbox.drain() == 1

    (row,) = _rows()
    assert (row["kind"], row["title"], row["notes"]) == ("link", "A willow", "Bends.")
    assert list(inbox.iterdir()) == []


def test_shared_words_become_a_note_and_files_are_kept(inbox):
    (inbox / "f1.pdf").write_bytes(b"%PDF-1.4 fake")
    _share(
        inbox,
        "b",
        items=[{"text": "Small batches ship faster."}, {"file": "f1.pdf", "name": "paper.pdf"}],
    )

    share_inbox.drain()

    kinds = {r["kind"]: r for r in _rows()}
    assert kinds["note"]["body"] == "Small batches ship faster."
    assert kinds["pdf"]["filename"] == "paper.pdf"
    assert sorted(p.name for p in inbox.iterdir()) == []


def test_a_share_still_being_written_waits(inbox):
    (inbox / "c.part").write_text("{")

    assert share_inbox.drain() == 0 and (inbox / "c.part").exists()


def test_a_broken_share_is_set_aside_not_retried(inbox):
    (inbox / "d.json").write_text("not json")

    assert share_inbox.drain() == 0
    assert (inbox / "failed" / "d.json").exists() and not (inbox / "d.json").exists()
