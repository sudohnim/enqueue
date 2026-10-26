"""Whether a host is on the public internet: what a link preview may reach.

Shared by the plain fetch (preview._refuse_private) and the WebKit reader
(webkit_page.py), which runs in its own process and imports nothing heavier."""

from __future__ import annotations

import ipaddress
import socket


def is_public(host: str, port: int | None = None) -> bool:
    """False when the host resolves to any loopback, private, link-local or otherwise
    non-global address. An unknown name counts as public: it fails on its own."""
    try:
        infos = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return True
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            return False
    return True
