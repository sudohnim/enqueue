"""The per-artifact snapshot and last-writer-wins merge (the sync design (AGENTS.md)).

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

    Children are ordered exactly as the sync design (AGENTS.md) specifies: annotations by
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
        # Facets ride the artifact snapshot as a child so the summary reaches other
        # devices (the phone, which cannot generate its own). Ordered for byte-stable
        # canonical JSON.
        "facets": [
            dict(r)
            for r in conn.execute(
                "SELECT id, level, statement, model_version, body_version, trust, edited"
                " FROM facets WHERE artifact_id = ? ORDER BY level, statement, id",
                (artifact_id,),
            )
        ],
        # A saved link's preview (title, description, site, picture hash) rides the
        # snapshot too: the phone cannot fetch pages itself, so without this its
        # link cards and reader had no preview at all. The picture's bytes travel as
        # a blob (sync/client.py), fetched on demand by hash.
        "link_preview": _link_preview(conn, artifact_id),
        # Everything else a model wrote about the artifact rides along, so a library
        # is read by a model once, on one device, and every other desktop takes the
        # result instead of paying for it again (derived_layers). The phone ignores
        # these keys and never sends them, which is also how a desktop tells a phone's
        # snapshot from another desktop's (ingest/queue.py, await_peer).
        **derived_layers(conn, artifact_id, vaulted=bool(row["vaulted_at"])),
    }


def _hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def derived_layers(conn: Connection, artifact_id: str, vaulted: bool = False) -> dict:
    """The model-written layers beyond the summary lines, for the snapshot.

    `entities` (named things and their facts), `sections` (a long document's section
    summaries, in order), `section_cache` (each summary keyed by the hash of the
    section's text, which is what ingest/source.py looks up before calling a model),
    `chunk_contexts` (the line placing each passage in its document, keyed by the hash
    of the passage's text, since passage ids differ between devices) and
    `related_verdicts` (the judge's rulings on pairs that include this artifact).
    Everything is ordered so the canonical JSON is byte-stable. A vaulted artifact
    carries none of it: vaulting removed it (vaultops._seal_derived).
    """
    if vaulted:
        return {
            "entities": [],
            "sections": [],
            "section_cache": [],
            "chunk_contexts": [],
            "related_verdicts": [],
        }
    from ..ingest import source

    contexts = {
        r["attribute"]: {"hash": r["attribute"], "context": r["value"], "model": r["model"]}
        for r in conn.execute(
            "SELECT attribute, value, model_version AS model FROM derived_values"
            " WHERE scope = 'chunk_context' AND subject = ?",
            (artifact_id,),
        )
    }
    for r in conn.execute(
        "SELECT text, context, context_model FROM chunks"
        " WHERE artifact_id = ? AND context IS NOT NULL",
        (artifact_id,),
    ):
        key = _hash(r["text"])
        contexts.setdefault(
            key, {"hash": key, "context": r["context"], "model": r["context_model"]}
        )

    section_cache: list[dict] = []
    if conn.execute(
        "SELECT 1 FROM derived_values WHERE scope = 'section_summary' AND subject = ? LIMIT 1",
        (artifact_id,),
    ).fetchone():
        # Only the sections the document has now: an edited note leaves summaries of
        # its older sections behind in the cache, and they need not travel.
        current = {_hash(s) for s in source.sections(source.document_text(conn, artifact_id))}
        section_cache = [
            dict(r)
            for r in conn.execute(
                "SELECT attribute AS hash, value AS summary, model_version AS model"
                " FROM derived_values WHERE scope = 'section_summary' AND subject = ?"
                " ORDER BY attribute, model_version",
                (artifact_id,),
            )
            if r["hash"] in current
        ]

    return {
        "entities": [
            dict(r)
            for r in conn.execute(
                "SELECT id, entity, fact, model_version, body_version, trust FROM entities"
                " WHERE artifact_id = ? ORDER BY entity, fact, id",
                (artifact_id,),
            )
        ],
        "sections": [
            dict(r)
            for r in conn.execute(
                "SELECT id, ordinal, summary, model_version, body_version, created_at"
                " FROM sections WHERE artifact_id = ? ORDER BY ordinal, id",
                (artifact_id,),
            )
        ],
        "section_cache": section_cache,
        "chunk_contexts": [contexts[k] for k in sorted(contexts)],
        "related_verdicts": [
            dict(r)
            for r in conn.execute(
                "SELECT subject, attribute, value, model_version FROM derived_values"
                " WHERE scope = 'related_judge' AND source = 'model'"
                " AND (subject LIKE ? OR subject LIKE ?) ORDER BY subject",
                (f"{artifact_id}|%", f"%|{artifact_id}"),
            )
        ],
    }


_PREVIEW_COLUMNS = (
    "status",
    "title",
    "description",
    "site_name",
    "error",
    "image_hash",
    "image_mime",
    "fetched_at",
)


def _link_preview(conn: Connection, artifact_id: str) -> dict | None:
    row = conn.execute(
        f"SELECT {', '.join(_PREVIEW_COLUMNS)} FROM link_previews WHERE artifact_id = ?",
        (artifact_id,),
    ).fetchone()
    return dict(row) if row else None


def serialize(snapshot: dict) -> bytes:
    """The canonical JSON from the sync design (AGENTS.md). No other serialization is valid."""
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

    `_device_id` is stamped at push time (the sync design (AGENTS.md)); a snapshot that has
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

    # Facets replace only when the incoming snapshot actually carries them. A snapshot
    # with none must NOT wipe facets this device generated locally - the equal-key
    # children re-apply (schema repair) would otherwise delete them. This is why a
    # device that generates its own summaries keeps them, while the phone (which cannot)
    # receives them whenever a snapshot brings them along.
    incoming_facets = snapshot.get("facets") or []
    # A vaulted artifact is the exception: its snapshot carries only sealed lines
    # (often none), and the readable summary a device made before it was vaulted must
    # not stay behind (vaultops._seal_derived).
    vaulted = bool((snapshot.get("artifact") or {}).get("vaulted_at"))
    if incoming_facets or vaulted:
        conn.execute("DELETE FROM facets WHERE artifact_id = ?", (artifact_id,))
        for f in incoming_facets:
            conn.execute(
                "INSERT INTO facets"
                " (id, artifact_id, level, statement, model_version, body_version, trust, edited)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    f["id"],
                    artifact_id,
                    f["level"],
                    f["statement"],
                    f.get("model_version"),
                    f.get("body_version"),
                    f.get("trust", 0.5),
                    f.get("edited", 0),
                ),
            )

    # The link preview replaces only when the snapshot carries one, like facets: a
    # snapshot from the phone (which never has a preview of its own) must not wipe
    # the preview this desktop fetched.
    incoming_preview = snapshot.get("link_preview")
    if incoming_preview:
        conn.execute(
            "INSERT INTO link_previews (artifact_id, status, title, description, site_name,"
            " error, image_hash, image_mime, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(artifact_id) DO UPDATE SET status=excluded.status,"
            " title=excluded.title, description=excluded.description,"
            " site_name=excluded.site_name, error=excluded.error,"
            " image_hash=excluded.image_hash, image_mime=excluded.image_mime,"
            " fetched_at=excluded.fetched_at",
            (
                artifact_id,
                incoming_preview.get("status") or "ok",
                incoming_preview.get("title"),
                incoming_preview.get("description"),
                incoming_preview.get("site_name"),
                incoming_preview.get("error"),
                incoming_preview.get("image_hash"),
                incoming_preview.get("image_mime"),
                incoming_preview.get("fetched_at") or artifact["updated_at"],
            ),
        )

    _apply_derived_layers(conn, artifact_id, snapshot, vaulted)

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


def _apply_derived_layers(
    conn: Connection, artifact_id: str, snapshot: dict, vaulted: bool
) -> None:
    """Take what another device's model wrote (derived_layers), so this one need not.

    Like facets, a layer is replaced only when the snapshot carries it: a phone's
    snapshot has none of these keys and must not wipe what this desktop holds, and an
    empty list from a desktop that has not summarized yet must not either. A vaulted
    artifact is the exception, as for facets: nothing readable stays behind.
    Caches (section summaries, passage placements, verdicts) only ever gain rows.
    """
    if vaulted:
        conn.execute("DELETE FROM entities WHERE artifact_id = ?", (artifact_id,))
        conn.execute("DELETE FROM sections WHERE artifact_id = ?", (artifact_id,))
        conn.execute(
            "DELETE FROM derived_values WHERE subject = ?"
            " AND scope IN ('section_summary', 'chunk_context')",
            (artifact_id,),
        )
        return

    entities = snapshot.get("entities") or []
    if entities:
        conn.execute("DELETE FROM entities WHERE artifact_id = ?", (artifact_id,))
        conn.executemany(
            "INSERT INTO entities (id, artifact_id, entity, fact, model_version, body_version,"
            " trust) VALUES (?,?,?,?,?,?,?)",
            [
                (
                    e["id"],
                    artifact_id,
                    e["entity"],
                    e["fact"],
                    e["model_version"],
                    e.get("body_version"),
                    e.get("trust", 0.5),
                )
                for e in entities
            ],
        )

    sections = snapshot.get("sections") or []
    if sections:
        conn.execute("DELETE FROM sections WHERE artifact_id = ?", (artifact_id,))
        conn.executemany(
            "INSERT INTO sections (id, artifact_id, ordinal, summary, model_version,"
            " body_version, created_at) VALUES (?,?,?,?,?,?,?)",
            [
                (
                    s["id"],
                    artifact_id,
                    s["ordinal"],
                    s["summary"],
                    s["model_version"],
                    s.get("body_version"),
                    s.get("created_at") or snapshot["artifact"]["updated_at"],
                )
                for s in sections
            ],
        )

    now = snapshot["artifact"]["updated_at"]
    for s in snapshot.get("section_cache") or []:
        conn.execute(
            "INSERT OR IGNORE INTO derived_values (scope, subject, attribute, value, grounded,"
            " source, model_version, created_at)"
            " VALUES ('section_summary', ?, ?, ?, 1, 'model', ?, ?)",
            (artifact_id, s["hash"], s["summary"], s["model"], now),
        )

    contexts = {c["hash"]: c for c in snapshot.get("chunk_contexts") or []}
    if contexts:
        for c in contexts.values():
            conn.execute(
                "INSERT OR IGNORE INTO derived_values (scope, subject, attribute, value,"
                " grounded, source, model_version, created_at)"
                " VALUES ('chunk_context', ?, ?, ?, 1, 'model', ?, ?)",
                (artifact_id, c["hash"], c["context"], c["model"], now),
            )
        # Passages this device already holds take their placement now; ingest
        # re-indexes them (ingest/queue.py notices the keyword row is out of date).
        for r in conn.execute(
            "SELECT id, text FROM chunks WHERE artifact_id = ? AND context IS NULL",
            (artifact_id,),
        ).fetchall():
            c = contexts.get(_hash(r["text"]))
            if c:
                conn.execute(
                    "UPDATE chunks SET context = ?, context_model = ? WHERE id = ?",
                    (c["context"], c["model"], r["id"]),
                )

    for v in snapshot.get("related_verdicts") or []:
        conn.execute(
            "DELETE FROM derived_values WHERE scope = 'related_judge' AND subject = ?",
            (v["subject"],),
        )
        conn.execute(
            "INSERT INTO derived_values (scope, subject, attribute, value, grounded, source,"
            " model_version, created_at) VALUES ('related_judge', ?, ?, ?, 1, 'model', ?, ?)",
            (v["subject"], v["attribute"], v["value"], v["model_version"], now),
        )
