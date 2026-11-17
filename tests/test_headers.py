from fastapi.testclient import TestClient

from enqueue.api.app import create_app


def test_headers(store):
    client = TestClient(create_app(), base_url="http://127.0.0.1:8787")
    r = client.get("/")
    for name in (
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Cross-Origin-Resource-Policy",
        "X-Frame-Options",
    ):
        assert r.headers.get(name) is not None
    assert "frame-ancestors 'none'" in r.headers.get("Content-Security-Policy", "")
    r2 = client.get("/health")
    assert r2.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Content-Security-Policy" not in r2.headers


def test_cross_site(store):
    client = TestClient(create_app(), base_url="http://127.0.0.1:8787")
    r = client.get("/health", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r2 = client.get("/health", headers={"Sec-Fetch-Site": "same-origin"})
    assert r2.status_code == 200
    r3 = client.get("/health")
    assert r3.status_code == 200
    r4 = client.get("/account/google/callback", headers={"Sec-Fetch-Site": "cross-site"})
    assert r4.status_code != 403
