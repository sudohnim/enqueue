import io

from fastapi.testclient import TestClient

from enqueue.api.app import create_app


def test_blob_route(store, quiet_queue):
    client = TestClient(create_app(), base_url="http://127.0.0.1:8787")
    files = {"file": ("a.html", io.BytesIO(b"<h1>x</h1>"), "text/html")}
    r = client.post("/capture/upload", files=files)
    aid = r.json()["id"]
    r2 = client.get(f"/artifacts/{aid}/blob")
    assert r2.headers["Content-Disposition"].startswith("attachment")
    assert r2.headers.get("X-Content-Type-Options") == "nosniff"

    files2 = {"file": ("a.png", io.BytesIO(b"\x89PNG\r\n"), "image/png")}
    r3 = client.post("/capture/upload", files=files2)
    aid2 = r3.json()["id"]
    r4 = client.get(f"/artifacts/{aid2}/blob")
    assert r4.headers["Content-Disposition"].startswith("inline")
