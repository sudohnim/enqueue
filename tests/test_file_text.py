"""A captured text file reads as words, never as its markup."""

from __future__ import annotations

from fastapi.testclient import TestClient

from enqueue import capture


def test_readable_shapes():
    html = capture.readable("<p>Order: 12<br>Name: Ada</p>", "text/html")
    assert html["format"] == "markdown" and "<p" not in html["text"] and "Ada" in html["text"]
    assert capture.readable("-----BEGIN PGP PUBLIC KEY BLOCK-----", "text/plain")["format"] == (
        "sealed"
    )
    table = capture.readable("a,b\n1,2\n", "text/csv")["text"].splitlines()
    assert table[:3] == ["| a | b |", "| --- | --- |", "| 1 | 2 |"]
    assert capture.readable('{"a":1}', "application/json")["text"] == '{\n  "a": 1\n}'


def test_a_file_ingest_has_not_read_still_shows_its_words(store, quiet_queue):
    from enqueue.api.app import create_app

    made = capture.upload(b"<p>Order: 12</p>", "order.html", "text/html")
    got = TestClient(create_app()).get(f"/artifacts/{made['id']}/text").json()
    assert got["format"] == "markdown" and got["text"].strip() == "Order: 12"
