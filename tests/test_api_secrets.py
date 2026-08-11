"""The `/secrets` endpoint: credential scan hits, documented in AGENTS.md.

The route used to be stacked on `get_greeting` (`@app.get("/secrets")` above
`@app.get("/greeting")`), so `GET /secrets` returned the greeting instead of
the scan hits. These tests pin the real shapes of both endpoints so the
shadowing cannot come back.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from enqueue import notes
from enqueue.api import app


class TestSecretsEndpoint:
    def test_empty_library_reports_no_hits(self, store, quiet_queue):
        client = TestClient(app)
        body = client.get("/secrets").json()
        assert body == {"count": 0, "hits": []}

    def test_scanned_hit_shows_in_the_report(self, store, quiet_queue):
        client = TestClient(app)
        made = notes.create(
            body="push to https://example.com with token ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        )
        artifact_id = made["artifact"]["id"]

        body = client.get("/secrets").json()
        assert body["count"] >= 1
        hit = next(h for h in body["hits"] if h["id"] == artifact_id)
        assert hit["title"] == made["artifact"]["title"]
        assert hit["kind"] == "github_token"
        assert hit["line"] == 1
        # The secret value itself never leaves the server.
        assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in hit["excerpt"]

    def test_greeting_still_returns_a_greeting(self, store, quiet_queue):
        client = TestClient(app)
        body = client.get("/greeting").json()
        assert body["text"]
        assert body["part"] in ("morning", "afternoon", "evening", "night")
        assert body["generated"] is False
