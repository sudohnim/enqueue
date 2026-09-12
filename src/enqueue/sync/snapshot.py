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
import uuid
from sqlite3 import Connection

from . import device_id


def read_artifact_snapshot(conn: Connection, artifact_id: str) -> dict | None:
    """Build one artifact's snapshot, or None when the artifact does not exist.

    Children are ordered exactly as E2E.md Section 1 specifies: annotations by
    `created_at, id`, page_text by `page`, versions by `created_at, id`.
    Tags are ordered by name (canonical form).
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
        "tags": [
            r["name"]
            for r in conn.execute(
                "SELECT t.name FROM tags t JOIN artifact_tags at ON at.tag_id = t.id"
                " WHERE at.artifact_id = ? ORDER BY t.name",
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


def _apply_snapshot_children(
    conn: Connection, artifact_id: str, snapshot: dict, artifact: dict
) -> None:
    """Apply snapshot children (annotations, page_text, versions, tags)."""
    conn.execute("DELETE FROM annotations WHERE artifact_id = ?", (artifact_id,))
    conn.execute("DELETE FROM page_text WHERE artifact_id = ?", (artifact_id,))
    conn.execute("DELETE FROM artifact_versions WHERE artifact_id = ?", (artifact_id,))
    conn.execute("DELETE FROM artifact_tags WHERE artifact_id = ?", (artifact_id,))

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
    from ..tags import normalize as normalize_tag

    for raw_name in snapshot.get("tags", []):
        # Canonicalize on the way in: a peer still on the old rules may ship a tag
        # with interior whitespace, but the local invariant is that tags.name never
        # holds any. Fold it here so the split-free `#name` query language holds
        # regardless of which device authored the snapshot.
        try:
            tag_name = normalize_tag(raw_name)
        except ValueError:
            continue  # a whitespace-only tag name folds to nothing; drop it
        # Upsert tag - generate UUID for the tag id
        tag_id = str(uuid.uuid4())
        conn.execute(
            "INSERT OR IGNORE INTO tags (id, name, created_at) VALUES (?,?,?)",
            (tag_id, tag_name, artifact["created_at"]),
        )
        # If tag already existed, get its id
        tag_row = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()
        if tag_row:
            tag_id = tag_row["id"]
        # Link artifact to tag
        conn.execute(
            "INSERT OR IGNORE INTO artifact_tags (artifact_id, tag_id, created_at) VALUES (?,?,?)",
            (artifact_id, tag_id, artifact["created_at"]),
        )


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
        "SELECT updated_at, _device_id, purged_at FROM artifacts WHERE id = ?", (artifact_id,)
    ).fetchone()
    if local_row is not None:
        # A tombstone is terminal: once an artifact is purged locally, no non-purge
        # snapshot (e.g. a stale edit made on a device that had not seen the purge yet)
        # may revive it, regardless of timestamps. A purge always wins and stays won.
        if local_row["purged_at"] and not artifact.get("purged_at"):
            return
        local_key = (local_row["updated_at"], local_row["_device_id"] or device_id())
        if local_key >= lww_key(snapshot):
            # Still need to apply children (tags, annotations, etc.) even if
            # artifact row is not updated, in case children were added/removed
            # without changing the artifact's updated_at (e.g., tags added).
            _apply_snapshot_children(conn, artifact_id, snapshot, artifact)
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

    _apply_snapshot_children(conn, artifact_id, snapshot, artifact)


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


# --------------------------------------------------------------------------- chats
# A conversation syncs as one snapshot - the `chats` row plus its ordered messages,
# their citations, and its topics - resolved by the same (updated_at, _device_id)
# last-writer-wins the artifact path uses. The message log is carried whole and
# replaced whole on apply: whole-snapshot LWW, so a conversation actively extended on
# two devices at once can lose the losing device's turns (the known edge, acceptable
# while a thread lives on one device at a time).


def read_chat_snapshot(conn: Connection, chat_id: str) -> dict | None:
    """Build one conversation's snapshot, or None when it does not exist.

    Children are ordered deterministically so the canonical JSON is byte-stable:
    messages by `ordinal, id`, citations by `message_id, rank`, topics by
    `created_at, id`.
    """
    row = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
    if row is None:
        return None
    return {
        "chat": dict(row),
        "messages": [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM chat_messages WHERE chat_id = ? ORDER BY ordinal, id",
                (chat_id,),
            )
        ],
        "citations": [
            dict(r)
            for r in conn.execute(
                "SELECT c.* FROM chat_citations c"
                " JOIN chat_messages m ON m.id = c.message_id"
                " WHERE m.chat_id = ? ORDER BY c.message_id, c.rank",
                (chat_id,),
            )
        ],
        "topics": [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM chat_topics WHERE chat_id = ? ORDER BY created_at, id",
                (chat_id,),
            )
        ],
    }


def chat_lww_key(snapshot: dict) -> tuple[str, str]:
    """The LWW key for a chat snapshot: `(updated_at, _device_id)`. Higher wins."""
    return (
        snapshot["chat"]["updated_at"],
        snapshot["chat"].get("_device_id") or "",
    )


def apply_chat_snapshot(conn: Connection, snapshot: dict) -> None:
    """Upsert a conversation and replace its children, idempotently, under LWW.

    No-op when the local chat's key is already >= the incoming one, so a stale
    pull never clobbers a newer local turn. A tombstone is terminal: once a chat
    is deleted locally, a non-delete snapshot cannot revive it.
    """
    chat = snapshot["chat"]
    chat_id = chat["id"]

    local = conn.execute(
        "SELECT updated_at, _device_id, deleted_at FROM chats WHERE id = ?", (chat_id,)
    ).fetchone()
    if local is not None:
        if local["deleted_at"] and not chat.get("deleted_at"):
            return  # a delete always wins and stays won
        local_key = (local["updated_at"], local["_device_id"] or device_id())
        if local_key >= chat_lww_key(snapshot):
            return

    cols = list(chat.keys())
    marks = ",".join("?" * len(cols))
    sets = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    conn.execute(
        f"INSERT INTO chats ({','.join(cols)}) VALUES ({marks})"
        f" ON CONFLICT(id) DO UPDATE SET {sets}",
        [chat[c] for c in cols],
    )

    # Children are replaced wholesale (citations first: they reference messages).
    conn.execute(
        "DELETE FROM chat_citations WHERE message_id IN"
        " (SELECT id FROM chat_messages WHERE chat_id = ?)",
        (chat_id,),
    )
    conn.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
    conn.execute("DELETE FROM chat_topics WHERE chat_id = ?", (chat_id,))
    for m in snapshot.get("messages", []):
        mc = list(m.keys())
        conn.execute(
            f"INSERT INTO chat_messages ({','.join(mc)}) VALUES ({','.join('?' * len(mc))})",
            [m[c] for c in mc],
        )
    for c in snapshot.get("citations", []):
        conn.execute(
            "INSERT INTO chat_citations (message_id, artifact_id, rank) VALUES (?,?,?)",
            (c["message_id"], c["artifact_id"], c["rank"]),
        )
    for t in snapshot.get("topics", []):
        tc = list(t.keys())
        conn.execute(
            f"INSERT INTO chat_topics ({','.join(tc)}) VALUES ({','.join('?' * len(tc))})",
            [t[c] for c in tc],
        )
