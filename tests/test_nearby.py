from fastapi.testclient import TestClient

from enqueue.api.app import create_app
from enqueue.retrieve.passage_links import near_text


def test_nearby(store, quiet_queue):
    from enqueue import notes

    a = notes.create("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu")[
        "artifact"
    ]["id"]
    client = TestClient(create_app(), base_url="http://127.0.0.1:8787")
    r = client.post(
        f"/artifacts/{a}/nearby",
        json={"text": "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"},
    )
    assert r.status_code == 200
    # short text returns empty
    r2 = client.post(f"/artifacts/{a}/nearby", json={"text": "one two three"})
    assert r2.json()["nearby"] == []
    assert near_text(a, "one two") == []
