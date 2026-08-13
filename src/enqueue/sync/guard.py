"""The plaintext-prototype safety guard (SYNC.3b).

The unencrypted prototype exists only to prove convergence and the live transport
on a localhost/LAN relay. This guard makes it impossible for that prototype to
quietly graduate to a real or hosted relay: while `SYNC_PLAINTEXT_PROTOTYPE` is
True, the sync client refuses any relay URL whose host is not loopback or a
private-LAN address.

The flag flips to `False` only in SYNC.9, after encryption is in.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

# SYNC.9: encryption is in (SYNC.8), so a non-local relay is now allowed.
# The flag flips back to True only if a future change removes the encrypt/decrypt
# wrap from the sync boundary.
SYNC_PLAINTEXT_PROTOTYPE = False

_LOOPBACK = ipaddress.ip_network("127.0.0.0/8")
_PRIVATE_IPV4 = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]


def _is_local_host(host: str) -> bool:
    if host in ("localhost", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # A hostname that is not literally "localhost" cannot be proven local, so
        # the guard treats it as remote and refuses it. Conservative on purpose.
        return False
    if ip in _LOOPBACK:
        return True
    if ip.version == 4:
        return any(ip in net for net in _PRIVATE_IPV4)
    # Only ::1 (loopback) counts as local for IPv6. Link-local and unique-local
    # addresses are ambiguous, so they stay refused.
    return False


def assert_local_relay(url: str) -> None:
    """Refuse a non-local relay URL while the plaintext prototype is on.

    Raises `RuntimeError` (and therefore uploads nothing) when the flag is set
    and `url`'s host is not loopback or a private-LAN address. No-op when the
    flag is off or the URL is empty (sync not configured).
    """
    if not SYNC_PLAINTEXT_PROTOTYPE:
        return
    if not url:
        return
    host = urlparse(url).hostname or ""
    if _is_local_host(host):
        return
    raise RuntimeError(
        f"the sync client refuses {url!r}: the plaintext prototype is on and the "
        "host is not loopback or a private-LAN address. Sync must not run against "
        "a real relay until encryption (SYNC.9) is in."
    )
