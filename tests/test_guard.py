"""Other websites cannot reach the engine (api/guard.py).

A page in the person's browser can send requests to 127.0.0.1:8787, and with DNS
rebinding read the replies too. Before the guard, a request carrying a foreign Host
could list the library and write notes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from enqueue import config
from enqueue.api.app import create_app

ENGINE = f"http://127.0.0.1:{config.API_PORT}"


@pytest.fixture
def client(store, quiet_queue, monkeypatch):
    # The production host set, not the test one conftest adds.
    monkeypatch.setattr(config, "ALLOWED_HOSTS", frozenset({"127.0.0.1", "localhost", "::1"}))
    return TestClient(create_app(), base_url=ENGINE)


def test_the_engines_own_pages_and_the_cli_are_served(client):
    assert client.get("/artifacts").status_code == 200
    assert client.post("/notes", json={"body": "from the cli"}).status_code == 201
    own = {"Origin": ENGINE}
    assert client.post("/notes", json={"body": "from the wall"}, headers=own).status_code == 201
    loopback = {"Host": f"localhost:{config.API_PORT}"}
    assert client.get("/artifacts", headers=loopback).status_code == 200


@pytest.mark.parametrize("host", ["evil.example:8787", "evil.example", "127.0.0.1.evil.example"])
def test_a_rebound_hostname_is_refused(client, host):
    assert client.get("/artifacts", headers={"Host": host}).status_code == 421
    assert client.get("/settings", headers={"Host": host}).status_code == 421
    assert client.post("/notes", json={"body": "x"}, headers={"Host": host}).status_code == 421


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "http://localhost:3000", "http://127.0.0.1", "null"]
)
def test_a_cross_site_write_is_refused(client, origin):
    r = client.post("/notes", json={"body": "planted"}, headers={"Origin": origin})
    assert r.status_code == 403
    assert client.get("/artifacts").json()  # reading is unaffected (the reply stays unreadable)
    assert all(a.get("title") != "planted" for a in _items(client))


def _items(client):
    body = client.get("/artifacts").json()
    return body.get("items", body) if isinstance(body, dict) else body
