"""Notes: documents you own.

A note is not a capture. Its body is markdown, it is edited in place, and every
version is kept. That distinction is the reason this module exists separately from
`capture.py`, and getting it wrong is what the rebuild is for.

Editing updates `artifacts.body` and appends to `artifact_versions`. The artifact
holds the present, the version log holds the past, and nothing written is destroyed.
"""

from __future__ import annotations

import hashlib
import re
import uuid

from . import config, db
from .ingest import queue as ingest_queue
from .sync.client import push_artifact
from .ingest import secrets

UNTITLED = "Untitled"


def title_from_body(body: str) -> str:
    """First heading, else first non-empty line, else Untitled.

    Titles matter more than they look: they are prepended at index time, so a note
    whose only mention of a name is its title is otherwise unfindable by that name.
    """
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        heading = re.match(r"^#{1,6}\s+(.*)$", line)
        text = heading.group(1).strip() if heading else line
        text = re.sub(r"[*_`]", "", text).strip()
        if text:
            return text[:120]
    return UNTITLED


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def create(body: str = "", title: str | None = None, local_only: bool = False) -> dict:
    """Create a note. An empty note is legitimate: capture costs nothing."""
    artifact_id = str(uuid.uuid4())
    now = db.now()
    if title and title.strip():
        resolved = title.strip()
        explicit = True
    else:
        resolved = title_from_body(body).strip() or UNTITLED
        explicit = False

    # The hash is only a dedupe key, and two notes written at different moments are
    # different artifacts even with identical text. Salting with the id keeps the
    # UNIQUE constraint meaningful for captures without making notes collide.
    digest = _hash(f"note:{artifact_id}")

    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, title_explicit, body, content_hash,"
            " created_at, updated_at, local_only, status) VALUES (?,'note',?,?,?,?,?,?,?,'ok')",
            (artifact_id, resolved, int(explicit), body, digest, now, now, int(local_only)),
        )
        if body:
            _append_version(conn, artifact_id, body, now)
            _record_secrets(conn, artifact_id, body)

    if body:
        ingest_queue.submit(artifact_id)
    from .sync.client import push_artifact

    push_artifact(artifact_id)
    return get(artifact_id)


def _append_version(conn, artifact_id: str, body: str, when: str) -> str:
    version_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO artifact_versions (id, artifact_id, body, created_at) VALUES (?,?,?,?)",
        (version_id, artifact_id, body, when),
    )
    return version_id


def _record_secrets(conn, artifact_id: str, text: str) -> list[str]:
    """Scan before anything reaches a model. Returns the kinds found."""
    conn.execute("DELETE FROM secret_hits WHERE artifact_id = ?", (artifact_id,))
    hits = secrets.scan(text)
    for hit in hits:
        conn.execute(
            "INSERT INTO secret_hits (id, artifact_id, kind, line, excerpt) VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), artifact_id, hit.kind, hit.line, hit.excerpt),
        )
    conn.execute(
        "UPDATE artifacts SET status = ? WHERE id = ?",
        ("text_only" if hits else "ok", artifact_id),
    )
    return [h.kind for h in hits]


def edit(artifact_id: str, body: str, title: str | None = None) -> dict:
    """Rewrite a note's body. Rejects captures.

    Appends the new body to the version log *before* updating the artifact, so a
    crash between the two leaves a spare copy rather than a hole.

    The title follows NOTE.0's model: a non-empty title is explicit and survives
    later body-only edits; an empty title clears the flag and reverts to the live
    first-line derivation; no title at all keeps an explicit title or derives.

    A vaulted note is edited in place while the vault is unlocked: the new body,
    title, and version row are sealed with the vault key before they touch disk, and
    the note is never re-indexed or secret-scanned. Editing therefore keeps the vault's
    guarantee - no plaintext at rest, out of the search index - instead of forcing a
    remove-edit-re-vault round trip. The returned dict carries the plaintext the caller
    just wrote, matching how the reader decrypts for an unlocked viewer.
    """
    now = db.now()

    with db.transaction() as conn:
        row = conn.execute(
            "SELECT kind, title, body, title_explicit, vaulted_at FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        if row["kind"] != "note":
            raise ValueError(
                f"{row['kind']} artifacts have no editable body; they came from the world. "
                "Attach an annotation instead."
            )

        vaulted = bool(row["vaulted_at"])
        key = None
        if vaulted:
            from . import vault, vaultops

            if not vault.is_unlocked():
                # A locked vault has no key to re-seal with; refuse rather than write
                # plaintext. The reader could only have shown this note while unlocked,
                # so this is the auto-lock-mid-edit case.
                raise ValueError("Unlock the vault to edit this note.")
            key = vault.key()
            # The stored body/title are ciphertext; compare and resolve against the
            # plaintext, exactly as an unlocked reader sees it.
            cur_body = vaultops._open(key, row["body"]) or ""
            cur_title = vaultops._open(key, row["title"])
        else:
            cur_body = row["body"]
            cur_title = row["title"]

        if title is not None and title.strip():
            resolved = title.strip()
            explicit = 1
        elif title is not None:
            resolved = title_from_body(body)
            explicit = 0
        elif row["title_explicit"]:
            resolved = cur_title
            explicit = 1
        else:
            resolved = title_from_body(body)
            explicit = 0

        body_changed = cur_body != body
        if not body_changed and cur_title == resolved and row["title_explicit"] == explicit:
            return _edit_result(artifact_id, vaulted, cur_body, cur_title)  # no change, no version

        # Seal what lands on disk when vaulted; store plaintext otherwise.
        stored_body = vaultops._seal(key, body) if vaulted else body
        stored_title = vaultops._seal(key, resolved) if vaulted else resolved

        if body_changed:
            _append_version(conn, artifact_id, stored_body, now)
        conn.execute(
            "UPDATE artifacts SET body = ?, title = ?, title_explicit = ?, updated_at = ?"
            " WHERE id = ?",
            (stored_body, stored_title, explicit, now, artifact_id),
        )
        # A vaulted note is deliberately out of the index and the secret log; only a
        # normal note is scanned and re-faceted.
        if not vaulted:
            _record_secrets(conn, artifact_id, body)

    if not vaulted:
        ingest_queue.submit(artifact_id)
    from .sync.client import push_artifact

    push_artifact(artifact_id)
    return _edit_result(artifact_id, vaulted, body, resolved)


def _edit_result(artifact_id: str, vaulted: bool, body: str, title: str | None) -> dict:
    """`get()` returns the stored row, which is ciphertext for a vaulted note. Hand the
    caller the plaintext it just wrote so the editor renders it, not the sealed base64."""
    out = get(artifact_id)
    if vaulted:
        out["artifact"]["body"] = body
        out["artifact"]["title"] = title
    return out


def annotate(artifact_id: str, text: str, supersedes_id: str | None = None) -> dict:
    """Commentary on a captured artifact. Append-only, because it comments on
    something immutable and there is no current state to resolve."""
    text = text.strip()
    if not text:
        raise ValueError("an annotation needs text")

    entry_id = str(uuid.uuid4())
    with db.transaction() as conn:
        row = conn.execute("SELECT kind FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        if row["kind"] == "note":
            raise ValueError("a note has a body; write into it rather than annotating it")
        if supersedes_id:
            prior = conn.execute(
                "SELECT 1 FROM annotations WHERE id = ? AND artifact_id = ?",
                (supersedes_id, artifact_id),
            ).fetchone()
            if prior is None:
                raise ValueError("supersedes_id is not an annotation on this artifact")

        now = db.now()
        conn.execute(
            "INSERT INTO annotations (id, artifact_id, supersedes_id, text, created_at)"
            " VALUES (?,?,?,?,?)",
            (entry_id, artifact_id, supersedes_id, text, now),
        )
        # Writing about a thing is touching it. The wall is ordered by last touch, so
        # leaving this out meant a note added from the capture overlay landed on an
        # artifact that then stayed exactly where it was, days down the wall. The note
        # was saved and the person had no way to tell.
        conn.execute("UPDATE artifacts SET updated_at = ? WHERE id = ?", (now, artifact_id))

    # An annotation is index-source text (R.2a): the artifact must be findable by
    # what was written about it, so its chunks have to rebuild. Same fire-and-forget
    # discipline as editing a note body.
    ingest_queue.submit(artifact_id)
    push_artifact(artifact_id)

    return {"id": entry_id, "supersedes_id": supersedes_id}


def get(artifact_id: str) -> dict:
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        # A purged artifact is a tombstone (the row is kept only so the delete can sync);
        # to every reader it is gone, same as if the row did not exist.
        if row is None or row["purged_at"]:
            raise KeyError(artifact_id)

        versions = conn.execute(
            "SELECT id, created_at FROM artifact_versions WHERE artifact_id = ?"
            " ORDER BY created_at DESC",
            (artifact_id,),
        ).fetchall()

        entries = conn.execute(
            "SELECT id, supersedes_id, text, created_at FROM annotations"
            " WHERE artifact_id = ? ORDER BY created_at",
            (artifact_id,),
        ).fetchall()
        superseded = {e["supersedes_id"] for e in entries if e["supersedes_id"]}

        facets = conn.execute(
            "SELECT id, level, statement, trust FROM facets WHERE artifact_id = ?"
            " ORDER BY level, statement",
            (artifact_id,),
        ).fetchall()
        skip = conn.execute(
            "SELECT reason FROM facet_skips WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        # "Generating" means a summary is pending in the background - not only the ones
        # a transient failure left owed in facet_retry, but every eligible artifact that
        # simply has not reached the (serial, slow-on-a-local-model) worker yet. So it is
        # true when the artifact has enough text to earn a summary, has none, and is not
        # permanently skipped (facet_skips) - which also covers the whole startup backfill.
        owed = conn.execute(
            "SELECT 1 FROM facet_retry WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        page_words = conn.execute(
            "SELECT COALESCE(SUM(LENGTH(text) - LENGTH(REPLACE(text, ' ', '')) + 1), 0) AS n"
            " FROM page_text WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()["n"]
        words = len((row["body"] or "").split()) + page_words
        eligible = words >= config.MIN_WORDS_FOR_FACETS
        hits = conn.execute(
            "SELECT kind, line, excerpt FROM secret_hits WHERE artifact_id = ?", (artifact_id,)
        ).fetchall()

        return {
            "artifact": dict(row),
            "versions": [dict(v) for v in versions],
            "annotations": [dict(e) | {"current": e["id"] not in superseded} for e in entries],
            "facets": [dict(f) for f in facets],
            "facet_skip_reason": skip["reason"] if skip else None,
            "summary_generating": (not facets) and (skip is None) and (bool(owed) or eligible),
            "secrets": [dict(h) for h in hits],
        }
    finally:
        conn.close()


def version_body(artifact_id: str, version_id: str) -> str | None:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT body FROM artifact_versions WHERE id = ? AND artifact_id = ?",
            (version_id, artifact_id),
        ).fetchone()
        return row["body"] if row else None
    finally:
        conn.close()
