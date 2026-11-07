"""The browser extension saves through the origin guard only with its connect code."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from enqueue import extension, keyring

EXT = "chrome-extension://abcdefghijklmnop"


@pytest.fixture
def client(store, quiet_queue, monkeypatch):
    kept: dict[str, str] = {}
    monkeypatch.setattr(keyring, "_get", lambda service, strict=False: kept.get(service))
    monkeypatch.setattr(
        keyring, "_set", lambda service, value, noun="key": kept.update({service: value})
    )
    from enqueue.api.app import create_app

    return TestClient(create_app())


def _save(client, origin=EXT, key=None, path="/capture/link"):
    headers = {"Origin": origin}
    if key:
        headers["X-Enqueue-Key"] = key
    return client.post(path, json={"url": "https://example.com/a", "body": "x"}, headers=headers)


def test_an_extension_without_the_code_is_refused(client):
    assert _save(client).status_code == 403
    extension.new_code()
    assert _save(client, key="enq-wrong").status_code == 403


def test_an_extension_with_the_code_saves(client):
    code = client.post("/extension/code").json()["code"]

    assert _save(client, key=code).status_code == 201
    assert _save(client, key=code, path="/notes").status_code == 201
    assert client.get("/extension").json() == {"connected": True}


def test_the_code_opens_only_the_capture_routes(client):
    code = extension.new_code()

    assert _save(client, key=code, path="/trash").status_code == 403
    assert (
        client.patch(
            "/settings", json={"changes": {}}, headers={"Origin": EXT, "X-Enqueue-Key": code}
        ).status_code
        == 403
    )


def test_a_website_with_the_code_is_still_refused(client):
    code = extension.new_code()

    assert _save(client, origin="https://evil.example", key=code).status_code == 403


def test_only_the_engines_own_page_gets_a_code(client):
    assert client.post("/extension/code", headers={"Origin": EXT}).status_code == 403
    assert (
        client.post("/extension/code", headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
