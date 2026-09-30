"""What may be sent to which model.

Marking an artifact local-only is a promise that its text never leaves the machine
(AGENTS.md, Provider layer). Ingest keeps it by routing a local-only artifact to the
local model (`get_provider(local_only=True)`). Every other call that puts artifact text
in a prompt - chat answers, the gray-zone judge, model re-ranking, attribute
extraction - reads several artifacts at once with one model, so it filters instead:
`shareable` drops local-only artifacts from what a remote model is shown.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from . import db

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def is_remote(provider) -> bool:
    """Whether a call to this provider leaves the machine (its endpoint is not loopback)."""
    host = urlsplit(getattr(provider, "base_url", "") or "").hostname or ""
    return host.lower() not in LOOPBACK


def local_only_ids(artifact_ids) -> set[str]:
    """The artifacts among `artifact_ids` that are marked local-only."""
    ids = list(dict.fromkeys(a for a in artifact_ids if a))
    if not ids:
        return set()
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id FROM artifacts WHERE local_only = 1"
            " AND id IN (SELECT value FROM json_each(?))",
            (json.dumps(ids),),
        ).fetchall()
    finally:
        conn.close()
    return {r["id"] for r in rows}


def is_local_only(artifact_id: str | None) -> bool:
    return bool(artifact_id) and artifact_id in local_only_ids([artifact_id])


def shareable(items: list[dict], provider, key: str = "artifact_id") -> list[dict]:
    """`items` without the local-only artifacts' entries, when `provider` is remote."""
    if not items or not is_remote(provider):
        return items
    private = local_only_ids(i.get(key) for i in items)
    return [i for i in items if i.get(key) not in private]
