"""Link previews only fetch public pages (preview._refuse_private).

Saving a link fetches it automatically. Before the guard, a link to the router, a
service on this machine or the engine itself was fetched from inside the network and
its text stored as the link's body.
"""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from enqueue import capture, preview


class _Page(BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self):  # noqa: N802 - http.server's name
        type(self).hits += 1
        body = b"<html><head><title>Router admin</title></head><body>secret</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_site():
    _Page.hits = 0
    server = HTTPServer(("127.0.0.1", 0), _Page)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def test_a_saved_link_to_this_machine_is_never_fetched(store, quiet_queue, local_site):
    aid = capture.link(local_site)["id"]

    result = preview.fetch(aid)

    assert _Page.hits == 0
    assert result["status"] == "failed"
    assert "private network" in result["error"]


def _resolving(monkeypatch, address: str):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kw: [(family, socket.SOCK_STREAM, 6, "", (address, port))],
    )


@pytest.mark.parametrize(
    "address",
    ["10.0.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "::1", "::ffff:127.0.0.1"],
)
def test_private_and_special_addresses_are_refused(monkeypatch, address):
    _resolving(monkeypatch, address)
    with pytest.raises(preview.PrivateAddress):
        preview._refuse_private(httpx.Request("GET", "https://sneaky.example/"))


def test_a_public_address_is_allowed(monkeypatch):
    _resolving(monkeypatch, "93.184.216.34")
    preview._refuse_private(httpx.Request("GET", "https://example.com/"))
