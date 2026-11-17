from enqueue import config, session
from enqueue.api.app import create_app
from fastapi.testclient import TestClient


def test_session(store, monkeypatch):
    monkeypatch.setattr(config, "SESSION_ENFORCE", True)
    token = session.start()
    client = TestClient(create_app(), base_url="http://127.0.0.1:8787")
    assert client.get("/artifacts").status_code == 401
    assert client.get("/artifacts", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/health").status_code == 200

    c2 = TestClient(create_app(), base_url="http://127.0.0.1:8787")
    r = c2.get(f"/boot?t={token}", follow_redirects=False)
    assert r.status_code == 303
    assert "enq_session" in r.cookies
    assert c2.get("/artifacts").status_code == 200

    c3 = TestClient(create_app(), base_url="http://127.0.0.1:8787")
    assert c3.get("/boot?t=wrong").status_code == 401

    c4 = TestClient(create_app(), base_url="http://127.0.0.1:8787")
    r4 = c4.get(f"/boot?t={token}&to=//evil.example", follow_redirects=False)
    assert r4.status_code == 303
    assert r4.headers["location"] == "/"

    monkeypatch.setattr(config, "SESSION_ENFORCE", False)
    c5 = TestClient(create_app(), base_url="http://127.0.0.1:8787")
    assert c5.get("/artifacts").status_code == 200
