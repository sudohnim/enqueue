"""Sync: the relay transport and the snapshot/LWW core.

The sync unit is one canonical encrypted snapshot per artifact (E2E.md). This
package holds the device identity, the snapshot model and LWW merge (built in
SYNC.4 per E2E.md Phase E3), and later the relay client and crypto.
"""

from __future__ import annotations

import uuid

from .. import config


def device_id() -> str:
    """This device's identity, per E2E.md Section 1.

    A UUID4 generated once and stored at `DATA_DIR/device_id`, never derived
    from hardware. It names this device's write namespace on the relay and
    breaks LWW ties. Idempotent: the first call creates it, later calls read it
    back.
    """
    path = config.DATA_DIR / "device_id"
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    new = str(uuid.uuid4())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    return new
