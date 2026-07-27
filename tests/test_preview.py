"""Link previews: what is read out of a page, and what is never referenced.

Parsing is pure and tested directly. The one network-shaped rule that matters is
tested by its absence: no remote asset URL is ever stored, so nothing the museum
renders can call home.
"""

from __future__ import annotations

import pytest

from enqueue import capture, db, preview

PAGE = """
<html><head>
  <title>Fallback title</title>
  <meta property="og:title" content="  Antifragility   ">
  <meta property="og:description" content="Things that gain from disorder.">
  <meta property="og:site_name" content="Example">
  <meta property="og:image" content="https://cdn.example.com/tracker.png">
</head><body><p>ignored</p></body></html>
"""


class TestParse:
    def test_prefers_open_graph_over_the_title_tag(self):
        fields = preview.parse(PAGE, "https://example.com/x")
        assert fields["title"] == "Antifragility"
        assert fields["description"] == "Things that gain from disorder."
        assert fields["site_name"] == "Example"

    def test_falls_back_to_the_title_tag(self):
        fields = preview.parse(
            "<html><head><title>Just this</title></head></html>", "https://a.co/"
        )
        assert fields["title"] == "Just this"
        assert fields["site_name"] == "a.co"

    def test_never_keeps_a_remote_asset(self):
        """An og:image left as a URL would fetch from the publisher on every single
        view, forever. That is worse than the one request the default avoids."""
        fields = preview.parse(PAGE, "https://example.com/x")
        assert "cdn.example.com" not in repr(fields)

    def test_a_page_saying_nothing_about_itself(self):
        fields = preview.parse("<html><body>hi</body></html>", "https://www.a.co/p")
        assert fields["title"] is None
        assert fields["site_name"] == "a.co"


class TestFetchGuards:
    def test_only_a_link_has_a_page(self, store, quiet_queue):
        made = capture.upload(b"%PDF-1.4 not really", "paper.pdf", mime="application/pdf")
        with pytest.raises(ValueError, match="only a saved link"):
            preview.fetch(made["id"])

    def test_a_local_only_link_is_never_fetched(self, store, quiet_queue):
        made = capture.link("https://example.com/private", local_only=True)
        with pytest.raises(ValueError, match="local only"):
            preview.fetch(made["id"])

    def test_an_unknown_artifact_is_a_key_error(self, store):
        with pytest.raises(KeyError):
            preview.fetch("nope")


class TestIndexing:
    def test_a_previewed_link_becomes_chunkable_text(self, store, quiet_queue):
        made = capture.link("https://example.com/x")
        preview._store(
            made["id"],
            {
                "status": "ok",
                "title": "Antifragility",
                "description": "Things that gain from disorder.",
                "site_name": "Example",
            },
        )

        from enqueue.ingest import chunk as chunk_mod

        with db.transaction() as conn:
            assert chunk_mod.chunk_artifact(conn, made["id"]) > 0
            text = conn.execute(
                "SELECT text FROM chunks WHERE artifact_id = ?", (made["id"],)
            ).fetchone()["text"]
        assert "Antifragility" in text

    def test_a_failed_preview_leaves_nothing_to_index(self, store, quiet_queue):
        made = capture.link("https://example.com/x")
        preview._store(made["id"], {"status": "failed", "error": "the publisher answered 403"})
        assert preview.text_for_index(made["id"]) == ""
