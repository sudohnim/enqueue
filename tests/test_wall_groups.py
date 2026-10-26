"""The wall's Type and Tags shelves cover the whole library, not the newest page."""

from fastapi.testclient import TestClient

from enqueue import capture, notes, tags
from enqueue.api.app import create_app


def test_shelves_count_everything_and_page_on_their_own(store, quiet_queue):
    for i in range(30):
        notes.create(body=f"note {i}")
    links = [capture.link(f"https://example.com/{i}")["id"] for i in range(3)]
    tags.add(links[0], "reading")
    client = TestClient(create_app())

    kinds = {g["key"]: g for g in client.get("/artifacts/groups?by=kind").json()["groups"]}
    assert kinds["note"]["count"] == 30 and len(kinds["note"]["items"]) == 12
    assert kinds["link"]["count"] == 3

    rest = client.get("/artifacts?kind=note&offset=12&limit=48").json()
    assert rest["total"] == 30 and len(rest["items"]) == 18 and not rest["more"]

    by_tag = {g["key"]: g for g in client.get("/artifacts/groups?by=tags").json()["groups"]}
    assert by_tag["reading"]["count"] == 1
    assert by_tag[""]["count"] == 32  # Untagged
    assert client.get("/artifacts/groups?by=size").status_code == 400
