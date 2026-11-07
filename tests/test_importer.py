"""Importing notes from other apps: one reader for folders and zips of Markdown and HTML."""

from __future__ import annotations

import json
import zipfile

import pytest

from enqueue import db, importer

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
NID = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def src(tmp_path):
    """The store keeps the library in tmp_path, so each test imports from a folder in it."""
    (tmp_path / "src").mkdir()
    return tmp_path / "src"


@pytest.fixture
def library(store, quiet_queue, monkeypatch):
    from enqueue.ingest import queue

    monkeypatch.setattr(queue, "submit_background", lambda aid: None)
    importer._state.clear()
    yield


def _notes() -> dict[str, dict]:
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT a.id, a.title, a.body, a.created_at, a.updated_at,"
            " (SELECT group_concat(t.name, ',') FROM artifact_tags x JOIN tags t"
            "  ON t.id = x.tag_id WHERE x.artifact_id = a.id) AS tags"
            " FROM artifacts a WHERE a.kind = 'note'"
        ).fetchall()
    finally:
        conn.close()
    return {
        r["title"]: dict(r, tags=sorted((r["tags"] or "").split(",")) if r["tags"] else [])
        for r in rows
    }


def _captures() -> list[tuple[str, str, bool]]:
    conn = db.get_conn()
    try:
        return sorted(
            (r["kind"], r["filename"], r["embedded_at"] is not None)
            for r in conn.execute(
                "SELECT kind, filename, embedded_at FROM artifacts WHERE kind != 'note'"
            )
        )
    finally:
        conn.close()


def _zip(path, files: dict[str, bytes | str]):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


def test_an_obsidian_vault_keeps_titles_tags_dates_and_pictures(library, src):
    vault = src / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "app.json").write_text("{}")
    (vault / "attachments").mkdir()
    (vault / "attachments" / "willow.png").write_bytes(PNG)
    (vault / "Sub").mkdir()
    (vault / "Willow.md").write_text(
        "---\ntitle: The willow\ntags: [trees, resilience]\ncreated: 2023-04-05\n---\n"
        "A willow bends in the storm. #idea\n\n![[willow.png|300]]\n\n```\n#notatag\n```\n"
    )
    (vault / "Sub" / "No heading.md").write_text("Just text about [[Willow]].\n")

    report = importer.run(vault)

    assert report["notes"] == 2 and report["files"] == 0
    willow = _notes()["The willow"]
    assert willow["tags"] == ["idea", "resilience", "trees"]
    assert willow["created_at"].startswith("2023-04-05")
    assert "](/artifacts/" in willow["body"] and "![[willow.png" not in willow["body"]
    assert "No heading" in _notes()
    assert _captures() == [("image", "willow.png", True)]


def test_a_notion_export_drops_page_ids_and_database_tables(library, src):
    page = f"Reading list {NID}"
    archive = _zip(
        src / "Export.zip",
        {
            f"{page}.md": f"# Reading list\n\nBooks to read.\n\n![](Reading%20list%20{NID}/cover.png)\n",
            f"{page}/cover.png": PNG,
            f"{page}/Range {NID}.md": "# Range\n\nGeneralists win in wicked domains.\n",
            f"Books {NID}.csv": "Name,Tags\nRange,books\n",
            f"Books {NID}_all.csv": "Name,Tags\nRange,books\n",
            "paper.pdf": b"%PDF-1.4 fake",
        },
    )

    report = importer.run(archive)

    assert set(_notes()) == {"Reading list", "Range"}
    assert report["notes"] == 2 and report["files"] == 1
    assert _captures() == [("image", "cover.png", True), ("pdf", "paper.pdf", False)]


def test_a_notion_export_split_into_zips_inside_the_zip(library, src):
    inner = _zip(src / "Part-1.zip", {f"Page {NID}.md": "Some words here.\n"})
    outer = _zip(src / "Export.zip", {"Part-1.zip": inner.read_bytes()})

    importer.run(outer)

    assert set(_notes()) == {"Page"}


def test_a_bear_backup_reads_textbundles(library, src):
    info = {"net.shinyfrog.bear": {"creationDate": "2022-01-02T03:04:05Z"}}
    archive = _zip(
        src / "Bear.bear2bk",
        {
            "Idea.textbundle/text.md": "# Idea\n\nA thought. #deep work# and #later\n\n![](assets/x.jpg)\n",
            "Idea.textbundle/assets/x.jpg": PNG,
            "Idea.textbundle/info.json": json.dumps(info),
        },
    )

    importer.run(archive)

    idea = _notes()["Idea"]
    assert idea["tags"] == ["deepwork", "later"]
    assert idea["created_at"].startswith("2022-01-02T03:04:05")
    assert _captures() == [("image", "x.jpg", True)]


def test_a_standard_notes_backup_brings_notes_and_their_tags(library, src):
    backup = {
        "version": "004",
        "items": [
            {
                "uuid": "n1",
                "content_type": "Note",
                "created_at": "2021-06-01T10:00:00.000Z",
                "updated_at": "2021-06-02T10:00:00.000Z",
                "content": {"title": "Batch size", "text": "Small batches ship faster."},
            },
            {
                "uuid": "n2",
                "content_type": "Note",
                "content": {"title": "Gone", "text": "x", "trashed": True},
            },
            {
                "uuid": "t1",
                "content_type": "Tag",
                "content": {
                    "title": "Work",
                    "references": [{"uuid": "n1", "content_type": "Note"}],
                },
            },
        ],
    }
    archive = _zip(
        src / "Standard Notes Backup.zip",
        {
            "Standard Notes Backup and Import File.txt": json.dumps(backup),
            "Items/Note/Batch size.txt": "Small batches ship faster.",
        },
    )

    report = importer.run(archive)

    assert report["notes"] == 1
    note = _notes()["Batch size"]
    assert note["tags"] == ["work"] and note["updated_at"].startswith("2021-06-02")


def test_an_encrypted_standard_notes_backup_says_so(library, src):
    f = src / "backup.txt"
    f.write_text(json.dumps({"items": [{"content_type": "Note", "content": "004:abc"}]}))

    with pytest.raises(ValueError, match="encrypted"):
        importer.run(src)


def test_a_fabric_export_turns_notepads_into_notes(library, src):
    (src / "Plans assets").mkdir()
    (src / "Plans assets" / "map.png").write_bytes(PNG)
    (src / "Plans.html").write_text(
        "<html><head><title>x</title></head><body><h1>Plans</h1><p>Go <b>north</b>.</p>"
        '<ul><li>tent<ul><li>poles</li></ul></li><li>map</li></ul><img src="Plans assets/map.png">'
        "</body></html>"
    )
    (src / "report.pdf").write_bytes(b"%PDF-1.4 fake")

    importer.run(src)

    body = _notes()["Plans"]["body"]
    assert "Go **north**." in body
    assert "- tent\n  - poles\n- map" in body
    assert _captures() == [("image", "map.png", True), ("pdf", "report.pdf", False)]


def test_importing_again_adds_nothing(library, src):
    (src / "A.md").write_text("# A\n\nSome text.\n")
    importer.run(src)

    report = importer.run(src)

    assert report["notes"] == 0 and len(_notes()) == 1


def test_a_zip_that_climbs_out_of_itself_is_refused(library, src):
    archive = _zip(src / "evil.zip", {"../../escape.md": "# x\n\ny\n"})

    with pytest.raises(ValueError, match="outside itself"):
        importer.run(archive)


def test_html_becomes_the_markdown_the_editor_writes():
    md = importer.html_to_md(
        "<h2>Head</h2><p>A <a href='https://x.y'>link</a> and <code>code</code>.</p>"
        "<blockquote><p>quoted</p></blockquote><pre>line 1\nline 2</pre>"
        "<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table>"
        "<ol><li>one</li><li><input type=checkbox checked>two</li></ol>"
    )
    assert md == (
        "## Head\n\nA [link](https://x.y) and `code`.\n\n> quoted\n\n```\nline 1\nline 2\n```"
        "\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n1. one\n2. [x] two\n"
    )
