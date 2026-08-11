"""Link previews: what is read out of a page, and what is never referenced.

Parsing is pure and tested directly. The one network-shaped rule that matters is
tested by its absence: no remote asset URL is ever stored, so nothing the app
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

ARTICLE = """
<html><head>
  <title>Lumo's not a kitten anymore | Proton</title>
  <meta property="og:title" content="Lumo's not a kitten anymore">
  <meta property="og:description" content="The Lumo mascot has grown up.">
</head><body>
<nav>Home Mail Drive VPN</nav>
<main><article>
<h1>Lumo's not a kitten anymore</h1>
<p>When we launched Lumo a year ago, our ambition was to create an experience
that was private, approachable, and easy to use.</p>
<p>We designed Lumo to match these virtues - a trusted and independent mascot
that protects your personal conversations.</p>
<p>The product has evolved rapidly since then, and with today's release of
Lumo 2.0, it is now more capable, intelligent, and versatile than ever.</p>
<p>Rather than redesigning the character from scratch, we chose to evolve it
so it reflects where Lumo is today: more capable, more sophisticated.</p>
<p>And just like the product itself, this evolution is only the beginning.</p>
</article></main>
<footer>Copyright Proton 2026</footer>
</body></html>
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
        assert row is not None
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
        its script in the same context as the app. A picture is not worth that."""
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


class TestArticleBody:
    def test_extract_body_keeps_the_article_not_the_nav(self):
        body = preview._extract_body(ARTICLE, "https://proton.me/blog/lumo-2-design")
        assert "kitten" in body
        assert "mascot" in body
        assert "Home" not in body
        assert len(body) >= preview.BODY_MIN_CHARS

    def test_extract_body_refuses_a_script_shell(self):
        body = preview._extract_body(
            "<html><head><title>X</title></head><body><div id='root'></div></body></html>",
            "https://a.co/p",
        )
        assert body == ""

    def test_a_fetched_article_stores_its_body(self, store, quiet_queue, monkeypatch):
        """The real fetch path: page comes back, body is kept, preview fields stored."""
        made = capture.link("https://proton.me/blog/lumo-2-design")
        monkeypatch.setattr(preview, "_read_capped", lambda url: ("text/html", ARTICLE))

        preview.fetch(made["id"])

        assert preview.has_body(made["id"]) is True
        assert preview.needs_fetch(made["id"]) is False

    def test_a_bodyless_page_still_indexes_by_preview(self, store, quiet_queue, monkeypatch):
        """A page that defeats extraction stays findable by its metadata."""
        made = capture.link("https://a.co/landing")
        shell = (
            "<html><head><title>Landing</title>"
            "<meta property='og:description' content='A page that says nothing.'></head>"
            "<body><div id='root'></div></body></html>"
        )
        monkeypatch.setattr(preview, "_read_capped", lambda url: ("text/html", shell))

        preview.fetch(made["id"])

        assert preview.has_body(made["id"]) is False
        assert preview.text_for_index(made["id"]) == "Landing\n\nA page that says nothing."

    def test_a_link_with_a_body_chunks_from_the_article(self, store, quiet_queue, monkeypatch):
        made = capture.link("https://proton.me/blog/lumo-2-design")
        monkeypatch.setattr(preview, "_read_capped", lambda url: ("text/html", ARTICLE))
        preview.fetch(made["id"])

        from enqueue.ingest import chunk as chunk_mod

        with db.transaction() as conn:
            assert chunk_mod.chunk_artifact(conn, made["id"]) > 0
            texts = [
                r["text"]
                for r in conn.execute(
                    "SELECT text FROM chunks WHERE artifact_id = ?", (made["id"],)
                ).fetchall()
            ]
        assert any("mascot" in t for t in texts)

    def test_needs_fetch(self, store, quiet_queue):
        made = capture.link("https://example.com/x")

        # No preview yet: fetching would add something.
        assert preview.needs_fetch(made["id"]) is True

        # A failed preview is not worth retrying automatically.
        preview._store(made["id"], {"status": "failed", "error": "the publisher answered 403"})
        assert preview.needs_fetch(made["id"]) is False

        # A successful preview without a body is an old link that can heal itself.
        preview._store(
            made["id"],
            {
                "status": "ok",
                "title": "Antifragility",
                "description": "Things that gain from disorder.",
                "site_name": "Example",
            },
        )
        assert preview.needs_fetch(made["id"]) is True

        # Once the body is there, fetching again adds nothing.
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO page_text (artifact_id, page, text, extractor) VALUES (?,0,?,'trafilatura')",
                (made["id"], "x" * 300),
            )
        assert preview.needs_fetch(made["id"]) is False
