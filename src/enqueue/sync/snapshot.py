"""The per-artifact snapshot and last-writer-wins merge (E2E.md Phase E3).

The sync unit is one canonical snapshot per artifact: the `artifacts` row plus
its child rows (`annotations`, `page_text`, `artifact_versions`), serialized as
canonical JSON. Conflicts resolve by LWW on the tuple `(updated_at, device_id)`,
compared lexicographically, higher wins. Exhibits are dropped (migration 0019);
saved-pivot sync is out of scope, so there is no exhibit snapshot here.

The convergence invariant: given the same set of snapshots, every device picks
the same winner and reaches byte-identical local state, regardless of apply
order. It is proved by the property test in `tests/test_sync.py`.
"""

from __future__ import annotations

import json
from sqlite3 import Connection

from . import device_id


def read_artifact_snapshot(conn: Connection, artifact_id: str) -> dict | None:
    """Build one artifact's snapshot, or None when the artifact does not exist.

    Children are ordered exactly as E2E.md Section 1 specifies: annotations by
    `created_at, id`, page_text by `page`, versions by `created_at, id`.
    """
    row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    if row is None:
        return None
    return {
        "artifact": dict(row),
        "annotations": [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM annotations WHERE artifact_id = ? ORDER BY created_at, id",
                (artifact_id,),
            )
        ],
        "page_text": [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM page_text WHERE artifact_id = ? ORDER BY page",
                (artifact_id,),
            )
        ],
        "versions": [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM artifact_versions WHERE artifact_id = ?" " ORDER BY created_at, id",
                (artifact_id,),
            )
        ],
    }


def serialize(snapshot: dict) -> bytes:
    """The canonical JSON from E2E.md Section 1. No other serialization is valid."""
    return json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def deserialize(raw: bytes) -> dict:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        # A half-written or corrupt snapshot is "not yet arrived", never
        # corruption. The caller (read_object) treats any parse failure that way.
        raise ValueError(f"not a canonical snapshot: {exc}") from exc


def lww_key(snapshot: dict) -> tuple[str, str]:
    """The LWW key: `(updated_at, device_id)`. Higher tuple wins.

    `_device_id` is stamped at push time (E2E.md Phase E4); a snapshot that has
    not been exported yet carries None (or the empty string) for it.
    """
    return (
        snapshot["artifact"]["updated_at"],
        snapshot["artifact"].get("_device_id") or "",
    )


def winner(snapshots: list[dict]) -> dict:
    """The snapshot with the maximum lww_key. Deterministic and total."""
    return max(snapshots, key=lww_key)


def apply_snapshot(conn: Connection, snapshot: dict) -> None:
    """Upsert the artifact row and replace its children, idempotently.

    No-op when the local artifact's lww_key is already >= the incoming one, so a
    stale pull never overwrites a newer local edit. The local key's device id is
    this device's own id (`device_id()`); the incoming key carries the pushing
    device's stamped `_device_id`. Idempotent: applying the same snapshot twice
    leaves the DB byte-identical. Caller wraps this in one transaction.
    """
    artifact = snapshot["artifact"]
    artifact_id = artifact["id"]

    local_row = conn.execute(
        "SELECT updated_at, _device_id FROM artifacts WHERE id = ?", (artifact_id,)
    ).fetchone()
    if local_row is not None:
        local_key = (local_row["updated_at"], local_row["_device_id"] or device_id())
        if local_key >= lww_key(snapshot):
            return

    # Upsert the artifact row in place (no delete, so the derived tables'
    # foreign keys to artifacts(id) stay valid). `_device_id` is a real column
    # (migration 0023), so it is written with the row.
    cols = list(artifact.keys())
    marks = ",".join("?" * len(cols))
    sets = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    conn.execute(
        f"INSERT INTO artifacts ({','.join(cols)}) VALUES ({marks})"
        f" ON CONFLICT(id) DO UPDATE SET {sets}",
        [artifact[c] for c in cols],
    )

    conn.execute("DELETE FROM annotations WHERE artifact_id = ?", (artifact_id,))
    conn.execute("DELETE FROM page_text WHERE artifact_id = ?", (artifact_id,))
    conn.execute("DELETE FROM artifact_versions WHERE artifact_id = ?", (artifact_id,))

    for a in snapshot.get("annotations", []):
        conn.execute(
            "INSERT INTO annotations (id, artifact_id, supersedes_id, text, created_at)"
            " VALUES (?,?,?,?,?)",
            (a["id"], artifact_id, a.get("supersedes_id"), a["text"], a["created_at"]),
        )
    for p in snapshot.get("page_text", []):
        conn.execute(
            "INSERT INTO page_text (artifact_id, page, text, extractor) VALUES (?,?,?,?)",
            (artifact_id, p["page"], p["text"], p["extractor"]),
        )
    for v in snapshot.get("versions", []):
        conn.execute(
            "INSERT INTO artifact_versions (id, artifact_id, body, created_at)" " VALUES (?,?,?,?)",
            (v["id"], artifact_id, v["body"], v["created_at"]),
        )


def apply_pulled_snapshot(conn: Connection, snapshot: dict) -> None:
    """Apply a pulled snapshot, retaining a losing local edit (DEC-A).

    When the incoming snapshot wins and the local body differs, the local edit's
    version rows are merged into the snapshot's versions before applying, so the
    lost edit stays recoverable from the version history - never silently gone.
    """
    artifact_id = snapshot["artifact"]["id"]
    local = read_artifact_snapshot(conn, artifact_id)
    if local is not None and lww_key(local) < lww_key(snapshot):
        local_versions = {v["id"]: v for v in local.get("versions", [])}
        incoming_versions = {v["id"]: v for v in snapshot.get("versions", [])}
        merged = {**local_versions, **incoming_versions}
        snapshot["versions"] = sorted(merged.values(), key=lambda v: (v["created_at"], v["id"]))
    apply_snapshot(conn, snapshot)
