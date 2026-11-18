import time

from fastapi.testclient import TestClient

from enqueue.api.app import create_app
from enqueue.index import embed as embed_mod


def test_warm(store, monkeypatch):
    called = {"n": 0}

    def fake(q):
        called["n"] += 1
        return [0.0]

    monkeypatch.setattr(embed_mod, "embed_query", fake)
    client = TestClient(create_app(), base_url="http://127.0.0.1:8787")
    r = client.post("/search/warm")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    for _ in range(50):
        if called["n"] >= 1:
            break
        time.sleep(0.02)
    assert called["n"] >= 1
