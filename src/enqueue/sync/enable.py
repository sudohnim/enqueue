"""Turning sync on, once this Mac has a relay password (its own relay's, or the device
token Enqueue sync gives it after a sign-in).

The password is the last step of setting sync up, so this also does what the setup was
waiting on: put the library's keyring on the relay for the phone (MOB2.10), start the
sync worker (the one started at boot found no relay yet), and push the whole library
the first time (BACKFILL.2).
"""

from __future__ import annotations

import threading

from .. import keyring, keyring_file, settings
from .client import push_keyring


def enable(secret: str, relay_url: str | None = None) -> None:
    """Store the password (Keychain) and the relay address, then start syncing.

    Raises ValueError for a password that cannot be one and RuntimeError when the
    Keychain refuses it, before anything else has changed.
    """
    keyring.sync_secret_set(secret)
    if relay_url:
        settings.update({"sync_relay_url": relay_url})
    push_keyring()
    try:
        from .worker import start

        start()
    except Exception as exc:  # noqa: BLE001 - sync is additive; never fail setup over it
        print(f"[engine] could not start the sync worker after secret set: {exc}")
    # Only with the key loaded (keyring unlocked), and only once.
    if keyring_file.load_dek_from_keychain() is not None and not settings.get("sync_backfill_done"):

        def _bg():
            from .client import push_all

            count = push_all()
            print(f"[sync] auto-backfill pushed {count} artifacts", flush=True)

        threading.Thread(target=_bg, daemon=True).start()
        settings.update({"sync_backfill_done": True})
