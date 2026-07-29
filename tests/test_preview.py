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

    def test_the_image_url_is_resolved_but_never_stored(self, store, quiet_queue):
        """The invariant is about what is *kept*, not what is read.

        `parse` hands back the picture's address so the fetcher can download it. What
        must never happen is that address surviving into the database, because an
        `<img>` pointing at the publisher would fetch from them on every view of the
        card, forever - worse than the single request the no-fetch default avoids,
        and silent. What is stored is a content hash of bytes we hold.
        """
        fields = preview.parse(PAGE, "https://example.com/x")
        assert fields["image_url"] == "https://cdn.example.com/tracker.png"

        made = capture.link("https://example.com/x")
        stored = dict(fields)
        stored.pop("image_url")
        preview._store(made["id"], {"status": "ok", **stored})

        row = preview.get(made["id"])
        assert "cdn.example.com" not in repr(row)
        assert row["image_hash"] is None

    def test_a_relative_image_path_is_resolved_against_the_page(self):
        """og:image is routinely site-relative. Left alone it would resolve against
        the engine's own origin and fetch from us instead of from the publisher."""
        page = '<html><head><meta property="og:image" content="/img/card.png"></head></html>'
        fields = preview.parse(page, "https://example.com/posts/one")
        assert fields["image_url"] == "https://example.com/img/card.png"

    def test_svg_is_refused_as_a_preview_picture(self):
        """A preview is served back from the engine's own origin, so an SVG would run
        its script in the same context as the museum. A picture is not worth that."""
        assert "image/svg+xml" not in preview.IMAGE_MIMES

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
