//! The mobile sync client (MOB.3): pull the encrypted library from the relay, decrypt
//! it, and keep a local SQLite read copy - so the phone holds the synced artifacts
//! offline. It reimplements the desktop's Phase SYNC in Rust (there is no Python on
//! the device), reusing the same crypto (MOB.3a) and the same snapshot + LWW model
//! (E2E.md Phase E3).

use std::io::Read;

use rusqlite::{Connection, OptionalExtension};
use serde_json::Value;

/// libsodium `crypto_pwhash` MODERATE preset (DEC-D5), matching `src/enqueue/crypto.py`.
/// memlimit is 256 MiB expressed in KiB; opslimit is the iteration count.
#[allow(dead_code)]
const ARGON2_M_COST: u32 = 256 * 1024;
#[allow(dead_code)]
const ARGON2_T_COST: u32 = 3;
#[allow(dead_code)]
const ARGON2_P_COST: u32 = 1;

#[allow(dead_code)]
const DEK_LEN: usize = 32;
#[allow(dead_code)]
const NONCE_LEN: usize = 24; // XSalsa20-Poly1305 secretbox nonce
#[allow(dead_code)]
const TAG_LEN: usize = 16; // Poly1305 tag

/// Argon2id key derivation, byte-for-byte the desktop's `crypto.derive_kek`.
#[allow(dead_code)]
pub fn derive_kek(secret: &str, salt: &[u8]) -> Result<[u8; DEK_LEN], String> {
    use argon2::{Algorithm, Argon2, Params, Version};
    let params = Params::new(ARGON2_M_COST, ARGON2_T_COST, ARGON2_P_COST, Some(DEK_LEN))
        .map_err(|e| format!("argon2 params: {e}"))?;
    let argon = Argon2::new(Algorithm::Argon2id, Version::V0x13, params);
    let mut out = [0u8; DEK_LEN];
    argon
        .hash_password_into(secret.as_bytes(), salt, &mut out)
        .map_err(|e| format!("argon2: {e}"))?;
    Ok(out)
}

/// XSalsa20-Poly1305 secretbox decrypt - PyNaCl `nacl.secret.SecretBox` (NOT XChaCha:
/// the shipped code uses `crypto_secretbox`, whose wire format is nonce(24) || ct ||
/// tag(16)).
#[allow(dead_code)]
fn secretbox_decrypt(key: &[u8; DEK_LEN], ciphertext: &[u8]) -> Result<Vec<u8>, String> {
    use xsalsa20poly1305::aead::{Aead, KeyInit};
    use xsalsa20poly1305::{Nonce, XSalsa20Poly1305};
    if ciphertext.len() < NONCE_LEN + TAG_LEN {
        return Err("ciphertext too short".into());
    }
    let (nonce, rest) = ciphertext.split_at(NONCE_LEN);
    let cipher = XSalsa20Poly1305::new_from_slice(key).map_err(|e| format!("key: {e}"))?;
    cipher
        .decrypt(Nonce::from_slice(nonce), rest)
        .map_err(|_| "decrypt failed".into())
}

/// XSalsa20-Poly1305 secretbox encrypt (the inverse of `secretbox_decrypt`), for the
/// capture push path (MOB.7): fresh nonce prepended, same wire format as the desktop.
#[allow(dead_code)]
#[allow(dead_code)]
pub fn secretbox_encrypt(key: &[u8; DEK_LEN], plaintext: &[u8]) -> Result<Vec<u8>, String> {
    use xsalsa20poly1305::aead::{Aead, KeyInit};
    use xsalsa20poly1305::{Nonce, XSalsa20Poly1305};
    let mut nonce = [0u8; NONCE_LEN];
    getrandom::getrandom(&mut nonce).map_err(|e| format!("nonce: {e}"))?;
    let cipher = XSalsa20Poly1305::new_from_slice(key).map_err(|e| format!("key: {e}"))?;
    let ct = cipher
        .encrypt(Nonce::from_slice(&nonce), plaintext)
        .map_err(|_| "encrypt failed".to_string())?;
    let mut out = nonce.to_vec();
    out.extend_from_slice(&ct);
    Ok(out)
}

/// Unwrap a DEK wrapped with a KEK (inverse of `secretbox_encrypt`).
/// Uses the same XSalsa20-Poly1305 secretbox decrypt.
#[allow(dead_code)]
#[allow(dead_code)]
pub fn unwrap(wrapped: &[u8], kek: &[u8; DEK_LEN]) -> Result<Vec<u8>, String> {
    secretbox_decrypt(kek, wrapped)
}

/// The mobile device's UUID4, generated once and stored in the app data dir (E2E.md
/// Section 1: a device id is a UUID, never from hardware).
#[allow(dead_code)]
pub fn device_id(dir: &std::path::Path) -> String {
    let path = dir.join("device_id");
    if let Ok(existing) = std::fs::read_to_string(&path) {
        let existing = existing.trim().to_string();
        if !existing.is_empty() {
            return existing;
        }
    }
    let id = uuid::Uuid::new_v4().to_string();
    let _ = std::fs::write(&path, &id);
    id
}

/// Read one artifact's snapshot from the local SQLite (the read copy), for the capture
/// push (MOB.7). Mirrors `read_artifact_snapshot`.
#[allow(dead_code)]
pub fn build_snapshot(conn: &Connection, artifact_id: &str) -> Result<Option<Value>, String> {
    let artifact: Option<Value> = conn
        .query_row(
            "SELECT id,kind,title,body,source_url,content_hash,mime,filename,created_at,
                    updated_at,local_only,status,pinned,deleted_at,pages,title_explicit,_device_id,purged_at,vaulted_at
             FROM artifacts WHERE id = ?1",
            [artifact_id],
            |r| {
                Ok(serde_json::json!({
                    "id": r.get::<_, String>(0)?,
                    "kind": r.get::<_, String>(1)?,
                    "title": r.get::<_, String>(2)?,
                    "body": r.get::<_, Option<String>>(3)?,
                    "source_url": r.get::<_, Option<String>>(4)?,
                    "content_hash": r.get::<_, Option<String>>(5)?,
                    "mime": r.get::<_, Option<String>>(6)?,
                    "filename": r.get::<_, Option<String>>(7)?,
                    "created_at": r.get::<_, String>(8)?,
                    "updated_at": r.get::<_, String>(9)?,
                    "local_only": r.get::<_, i64>(10)?,
                    "status": r.get::<_, String>(11)?,
                    "pinned": r.get::<_, i64>(12)?,
                    "deleted_at": r.get::<_, Option<String>>(13)?,
                    "pages": r.get::<_, Option<i64>>(14)?,
                    "title_explicit": r.get::<_, i64>(15)?,
                    "_device_id": r.get::<_, Option<String>>(16)?,
                    "purged_at": r.get::<_, Option<String>>(17)?,
                    "vaulted_at": r.get::<_, Option<String>>(18)?,
                }))
            },
        )
        .optional()
        .map_err(|e| e.to_string())?;
    let Some(artifact) = artifact else {
        return Ok(None);
    };
    let mut anns = Vec::new();
    let mut stmt = conn
        .prepare("SELECT id,artifact_id,supersedes_id,text,created_at FROM annotations WHERE artifact_id = ?1 ORDER BY created_at, id")
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([artifact_id], |r| {
            Ok(serde_json::json!({
                "id": r.get::<_, String>(0)?,
                "artifact_id": r.get::<_, String>(1)?,
                "supersedes_id": r.get::<_, Option<String>>(2)?,
                "text": r.get::<_, String>(3)?,
                "created_at": r.get::<_, String>(4)?,
            }))
        })
        .map_err(|e| e.to_string())?;
    for row in rows {
        anns.push(row.map_err(|e| e.to_string())?);
    }
    // Tags live in the artifact's tags_json column on mobile (there is no tags table
    // here). They MUST ride the snapshot: the desktop's apply DELETEs an artifact's
    // tags then re-inserts from snapshot["tags"], so omitting them (as this did before)
    // made every mobile push WIPE that artifact's desktop tags. Carrying them also makes
    // a tag added on the phone propagate to the desktop.
    let tags: Value = conn
        .query_row(
            "SELECT tags_json FROM artifacts WHERE id = ?1",
            [artifact_id],
            |r| r.get::<_, Option<String>>(0),
        )
        .optional()
        .map_err(|e| e.to_string())?
        .flatten()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .filter(|v| v.is_array())
        .unwrap_or_else(|| Value::Array(vec![]));

    // Facets stored locally (synced from desktop, or hand-edited here).
    let mut facets = Vec::new();
    let mut fstmt = conn
        .prepare(
            "SELECT id,level,statement,model_version,body_version,trust,edited \
             FROM facets WHERE artifact_id = ?1 ORDER BY level, statement, id",
        )
        .map_err(|e| e.to_string())?;
    let frows = fstmt
        .query_map([artifact_id], |r| {
            Ok(serde_json::json!({
                "id": r.get::<_, String>(0)?,
                "level": r.get::<_, Option<i64>>(1)?,
                "statement": r.get::<_, Option<String>>(2)?,
                "model_version": r.get::<_, Option<String>>(3)?,
                "body_version": r.get::<_, Option<String>>(4)?,
                "trust": r.get::<_, Option<f64>>(5)?,
                "edited": r.get::<_, i64>(6)?,
            }))
        })
        .map_err(|e| e.to_string())?;
    for row in frows {
        facets.push(row.map_err(|e| e.to_string())?);
    }

    Ok(Some(serde_json::json!({
        "artifact": artifact,
        "annotations": anns,
        "tags": tags,
        "page_text": [],
        "versions": [],
        // Facets ride the snapshot so a facet edited on the phone reaches the desktop.
        // Full columns, so the desktop stores them faithfully.
        "facets": facets,
    })))
}

/// Push one snapshot to the relay (MOB.7): serialize, encrypt, PUT under this device's
/// namespace. The relay upserts by name (MOBFIX.5), so a re-PUT of an edited or deleted
/// snapshot overwrites in place and returns 201; a 409 (older relay) is still tolerated.
#[allow(dead_code)]
/// PUT an encrypted object to the relay, retrying transient transport failures.
///
/// A phone's network flaps (cellular <-> wifi handoff, IPv6/IPv4 races), so a
/// single attempt often dies on a DNS lookup or an aborted TLS handshake while a
/// retry a moment later succeeds - that flakiness was why a captured image could
/// stay stuck `pending` even though the relay was reachable. 201 = stored, 409 =
/// already present (both success); any other HTTP status is a real rejection and is
/// NOT retried. Backoff grows with the attempt.
fn put_object_with_retry(url: &str, secret: &str, body: &[u8], label: &str) -> Result<(), String> {
    const ATTEMPTS: usize = 3;
    let mut last = String::new();
    for attempt in 1..=ATTEMPTS {
        match ureq::put(url)
            .set("Authorization", &format!("Bearer {secret}"))
            .set("Content-Type", "application/octet-stream")
            .send_bytes(body)
        {
            Ok(resp) => {
                let status = resp.status();
                if status == 201 || status == 409 {
                    return Ok(());
                }
                eprintln!("[sync] {label} rejected: {status}");
                return Err(format!("push rejected: {status}"));
            }
            Err(e) => {
                last = e.to_string();
                eprintln!("[sync] {label} transport error (attempt {attempt}/{ATTEMPTS}): {last}");
                if attempt < ATTEMPTS {
                    std::thread::sleep(std::time::Duration::from_millis(400 * attempt as u64));
                }
            }
        }
    }
    Err(format!("push transport error after {ATTEMPTS} attempts: {last}"))
}

pub fn push_snapshot(
    relay_url: &str,
    secret: &str,
    dek: &[u8; DEK_LEN],
    device: &str,
    snapshot: &Value,
) -> Result<(), String> {
    let bytes = serde_json::to_vec(snapshot).map_err(|e| e.to_string())?;
    let ciphertext = secretbox_encrypt(dek, &bytes)?;
    let name = format!("dev/{device}/artifacts/{}.enc", snapshot["artifact"]["id"].as_str().unwrap_or(""));
    let url = format!("{}/sync/object/{}", relay_url.trim_end_matches('/'), name);
    put_object_with_retry(&url, secret, &ciphertext, &format!("push_snapshot {name}"))
}

/// Unwrap the DEK from the desktop's `keyring.json` plus the recovery phrase
/// (mirrors `keyring_file.unlock_with_recovery`, per MOB.3a).
#[allow(dead_code)]
#[allow(dead_code)]
pub fn unlock_dek(keyring_json: &str, phrase: &str) -> Result<[u8; DEK_LEN], String> {
    let record: Value =
        serde_json::from_str(keyring_json).map_err(|e| format!("keyring json: {e}"))?;
    let recovery_salt = hex::decode(
        record["recovery_salt"]
            .as_str()
            .ok_or("keyring: missing recovery_salt")?,
    )
    .map_err(|e| format!("keyring: recovery_salt hex: {e}"))?;
    let dek_by_recovery = hex::decode(
        record["dek_by_recovery"]
            .as_str()
            .ok_or("keyring: missing dek_by_recovery")?,
    )
    .map_err(|e| format!("keyring: dek_by_recovery hex: {e}"))?;
    let kek = derive_kek(phrase, &recovery_salt)?;
    let dek = secretbox_decrypt(&kek, &dek_by_recovery)
        .map_err(|_| "wrong recovery phrase".to_string())?;
    if dek.len() != DEK_LEN {
        return Err("keyring: wrong DEK length".into());
    }
    let mut out = [0u8; DEK_LEN];
    out.copy_from_slice(&dek);
    Ok(out)
}

#[allow(dead_code)]
fn str_at(v: Option<&Value>) -> Option<String> {
    v.and_then(Value::as_str).map(str::to_string)
}

#[allow(dead_code)]
fn int_at(v: Option<&Value>) -> Option<i64> {
    v.and_then(Value::as_i64)
}

/// The LWW key `(updated_at, _device_id)`, compared lexicographically (E2E.md E3).
#[allow(dead_code)]
fn lww_key(snapshot: &Value) -> (String, String) {
    let a = &snapshot["artifact"];
    (
        a["updated_at"].as_str().unwrap_or("").to_string(),
        a["_device_id"].as_str().unwrap_or("").to_string(),
    )
}

/// The artifacts read-copy schema, mirroring the desktop's final migrations (0001
/// baseline + pinned/deleted_at/pages/title_explicit/_device_id).
#[allow(dead_code)]
pub fn init_schema(conn: &Connection) -> Result<(), String> {
    conn.execute_batch(
        r#"
        CREATE TABLE IF NOT EXISTS artifacts (
          id             TEXT PRIMARY KEY,
          kind           TEXT NOT NULL,
          title          TEXT NOT NULL,
          body           TEXT,
          source_url     TEXT,
          content_hash   TEXT,
          mime           TEXT,
          filename       TEXT,
          created_at     TEXT NOT NULL,
          updated_at     TEXT NOT NULL,
          local_only     INTEGER NOT NULL DEFAULT 0,
          status         TEXT NOT NULL,
          pinned         INTEGER NOT NULL DEFAULT 0,
          deleted_at     TEXT,
          pages          INTEGER,
          title_explicit INTEGER NOT NULL DEFAULT 0,
          _device_id     TEXT,
          tags_json      TEXT,
          purged_at      TEXT,
          vaulted_at     TEXT,
          embedded_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS annotations (
          id            TEXT PRIMARY KEY,
          artifact_id   TEXT NOT NULL,
          supersedes_id TEXT,
          text          TEXT NOT NULL,
          created_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS page_text (
          artifact_id TEXT NOT NULL,
          page        INTEGER,
          text        TEXT,
          extractor   TEXT
        );
        CREATE TABLE IF NOT EXISTS artifact_versions (
          id          TEXT PRIMARY KEY,
          artifact_id TEXT NOT NULL,
          body        TEXT NOT NULL,
          created_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sync_meta (
          key   TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        -- Link preview cache (title/description/site/image for a saved link). The
        -- reader's link path reads it; on a fresh phone nothing populates it yet, so
        -- the table must exist for that read to return "no preview" instead of
        -- crashing with "no such table". Columns mirror the engine's schema
        -- (migrations 0002 + 0007) so a synced preview would land compatibly.
        CREATE TABLE IF NOT EXISTS link_previews (
          artifact_id TEXT PRIMARY KEY,
          status      TEXT NOT NULL,
          title       TEXT,
          description TEXT,
          site_name   TEXT,
          error       TEXT,
          fetched_at  TEXT,
          image_hash  TEXT,
          image_mime  TEXT
        );
        -- Cover the hot library / list / search query (deleted_at filter + updated_at
        -- ordering) and the annotations join, so they use an index instead of a full
        -- table scan + sort.
        CREATE INDEX IF NOT EXISTS idx_artifacts_live ON artifacts(deleted_at, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_annotations_artifact ON annotations(artifact_id);
        CREATE INDEX IF NOT EXISTS idx_page_text_artifact ON page_text(artifact_id);
        -- Conversations sync now (engine migration 0030). Columns mirror the engine's
        -- chats/chat_messages/chat_citations/chat_topics so a chat snapshot lands
        -- compatibly; a fresh phone starts empty and fills from the relay on pull.
        CREATE TABLE IF NOT EXISTS chats (
          id          TEXT PRIMARY KEY,
          title       TEXT NOT NULL,
          scope_kind  TEXT,
          scope_id    TEXT,
          created_at  TEXT NOT NULL,
          updated_at  TEXT NOT NULL,
          pinned      INTEGER NOT NULL DEFAULT 0,
          deleted_at  TEXT,
          _device_id  TEXT
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
          id         TEXT PRIMARY KEY,
          chat_id    TEXT NOT NULL,
          ordinal    INTEGER,
          role       TEXT,
          text       TEXT,
          grounded   INTEGER,
          created_at TEXT,
          kind       TEXT,
          payload    TEXT,
          status     TEXT,
          error      TEXT
        );
        CREATE TABLE IF NOT EXISTS chat_citations (
          message_id  TEXT NOT NULL,
          artifact_id TEXT NOT NULL,
          rank        INTEGER
        );
        CREATE TABLE IF NOT EXISTS chat_topics (
          id         TEXT PRIMARY KEY,
          chat_id    TEXT NOT NULL,
          topic      TEXT,
          created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_chat_messages_chat ON chat_messages(chat_id);
        CREATE INDEX IF NOT EXISTS idx_chats_live ON chats(deleted_at, pinned, updated_at DESC);
        -- Facets (the summary) sync now as a child of the artifact, so the phone - which
        -- cannot generate its own - can show and hand-edit them. Columns mirror the
        -- engine's facets table.
        CREATE TABLE IF NOT EXISTS facets (
          id            TEXT PRIMARY KEY,
          artifact_id   TEXT NOT NULL,
          level         INTEGER,
          statement     TEXT,
          model_version TEXT,
          body_version  TEXT,
          trust         REAL,
          edited        INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_facets_artifact ON facets(artifact_id);
        -- The activity log (mirrors the engine's events table): the notable things the
        -- phone did - a question asked and answered, a capture, a facet edit, a sync -
        -- each with a one-line detail and an optional JSON `data` blob opened on demand.
        -- Local diagnostics only, never synced; persisted so it survives a relaunch.
        CREATE TABLE IF NOT EXISTS events (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          ts          TEXT NOT NULL,
          kind        TEXT NOT NULL,
          detail      TEXT NOT NULL DEFAULT '',
          data        TEXT,
          duration_ms INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_events_id_desc ON events(id DESC);
        "#,
    )
    .map_err(|e| e.to_string())?;
    // Migration: tags_json was added after the first release. ALTER fails with a
    // "duplicate column" on installs that already have it, which is fine.
    let _ = conn.execute("ALTER TABLE artifacts ADD COLUMN tags_json TEXT", []);
    // Migration: purged_at (cross-device purge tombstone), same duplicate-safe pattern.
    let _ = conn.execute("ALTER TABLE artifacts ADD COLUMN purged_at TEXT", []);
    // Migration: vaulted_at (secret-vault membership marker), same duplicate-safe pattern.
    let _ = conn.execute("ALTER TABLE artifacts ADD COLUMN vaulted_at TEXT", []);
    // Migration: embedded_at (an image pasted inside a note - note content, not a
    // standalone card), same duplicate-safe pattern. The library/list queries filter
    // `embedded_at IS NULL` so it never shows as its own artifact on the phone.
    let _ = conn.execute("ALTER TABLE artifacts ADD COLUMN embedded_at TEXT", []);
    // One-time heal: builds before `vaulted_at` existed here applied vaulted
    // snapshots without the column, dropping the flag and leaving vault-ciphertext
    // visible in the wall. Force a single full re-pull (cursor -> 0); the strictly-
    // greater apply gate above then re-reads the relay's correct snapshot and repairs
    // the row. Guarded by a marker so it runs exactly once, not every launch.
    let healed: Option<String> = conn
        .query_row(
            "SELECT value FROM sync_meta WHERE key = 'heal_vault_repull_v1'",
            [],
            |r| r.get(0),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    if healed.is_none() {
        let _ = conn.execute("DELETE FROM sync_meta WHERE key = 'cursor'", []);
        conn.execute(
            "INSERT INTO sync_meta (key, value) VALUES ('heal_vault_repull_v1', '1')",
            [],
        )
        .map_err(|e| e.to_string())?;
    }
    // One-time heal v2: the pull advances the cursor to the relay's latest even when
    // an individual snapshot failed to apply (e.g. an older build inserting a row
    // before its column - purged_at, vaulted_at - existed on the phone). A snapshot
    // skipped that way is never retried, so a live artifact can be missing on the
    // phone while its snapshot sits intact on the relay. Force one more full re-pull
    // (cursor -> 0) so every relay snapshot is re-applied against the current schema.
    // Same run-once marker pattern as v1.
    let healed_v2: Option<String> = conn
        .query_row(
            "SELECT value FROM sync_meta WHERE key = 'heal_repull_v2'",
            [],
            |r| r.get(0),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    if healed_v2.is_none() {
        let _ = conn.execute("DELETE FROM sync_meta WHERE key = 'cursor'", []);
        conn.execute(
            "INSERT INTO sync_meta (key, value) VALUES ('heal_repull_v2', '1')",
            [],
        )
        .map_err(|e| e.to_string())?;
    }
    // One-time heal v3: conversations started syncing after this install existed, so
    // any chat snapshot already on the relay sits past the cursor and never arrives.
    // Force one full re-pull so the chat limb applies every chat object. Same marker.
    let healed_v3: Option<String> = conn
        .query_row(
            "SELECT value FROM sync_meta WHERE key = 'heal_repull_v3_chats'",
            [],
            |r| r.get(0),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    if healed_v3.is_none() {
        let _ = conn.execute("DELETE FROM sync_meta WHERE key = 'cursor'", []);
        conn.execute(
            "INSERT INTO sync_meta (key, value) VALUES ('heal_repull_v3_chats', '1')",
            [],
        )
        .map_err(|e| e.to_string())?;
    }
    // One-time heal v4: facets started riding the artifact snapshot after this install
    // existed, so artifacts already pulled carry no facets locally. Force one full
    // re-pull so every artifact snapshot re-applies with its facets. Same marker.
    let healed_v4: Option<String> = conn
        .query_row(
            "SELECT value FROM sync_meta WHERE key = 'heal_repull_v4_facets'",
            [],
            |r| r.get(0),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    if healed_v4.is_none() {
        let _ = conn.execute("DELETE FROM sync_meta WHERE key = 'cursor'", []);
        conn.execute(
            "INSERT INTO sync_meta (key, value) VALUES ('heal_repull_v4_facets', '1')",
            [],
        )
        .map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[allow(dead_code)]
fn apply_snapshot(conn: &Connection, snapshot: &Value) -> Result<(), String> {
    let artifact = &snapshot["artifact"];
    let id = artifact["id"].as_str().ok_or("snapshot: missing id")?;

    // LWW no-op check. A read-only device has no local edits, so this only makes a
    // re-pull of the same snapshot idempotent. Note the gate is STRICTLY greater
    // (`>`), not `>=`: on an equal LWW key the two snapshots are the same logical
    // version, so re-applying is a harmless overwrite that ALSO repairs any field an
    // older-schema apply silently dropped (e.g. a vaulted snapshot pulled before this
    // device had the `vaulted_at` column, which left vault-ciphertext showing in the
    // wall). A strictly-greater local key still wins and is never clobbered.
    let local: Option<(String, String, Option<String>)> = conn
        .query_row(
            "SELECT updated_at, COALESCE(_device_id,''), purged_at FROM artifacts WHERE id = ?1",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    if let Some((local_updated, local_device, local_purged)) = local {
        // A tombstone is terminal: once purged locally, a non-purge snapshot (e.g. a
        // stale edit from a device that had not seen the purge) never revives it.
        let incoming_purged = artifact.get("purged_at").and_then(Value::as_str).is_some();
        if local_purged.is_some() && !incoming_purged {
            return Ok(());
        }
        if (local_updated, local_device) > lww_key(snapshot) {
            return Ok(());
        }
    }

    let g = |c: &str| artifact.get(c);
    conn.execute(
        "INSERT INTO artifacts (id,kind,title,body,source_url,content_hash,mime,filename,\
         created_at,updated_at,local_only,status,pinned,deleted_at,pages,title_explicit,_device_id,purged_at,vaulted_at,embedded_at)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20)
         ON CONFLICT(id) DO UPDATE SET
           kind=excluded.kind, title=excluded.title, body=excluded.body,
           source_url=excluded.source_url, content_hash=excluded.content_hash,
           mime=excluded.mime, filename=excluded.filename, created_at=excluded.created_at,
           updated_at=excluded.updated_at, local_only=excluded.local_only,
           status=excluded.status, pinned=excluded.pinned, deleted_at=excluded.deleted_at,
           pages=excluded.pages, title_explicit=excluded.title_explicit,
           _device_id=excluded._device_id, purged_at=excluded.purged_at, vaulted_at=excluded.vaulted_at,
           embedded_at=excluded.embedded_at",
        rusqlite::params![
            id,
            str_at(g("kind")),
            str_at(g("title")),
            str_at(g("body")),
            str_at(g("source_url")),
            str_at(g("content_hash")),
            str_at(g("mime")),
            str_at(g("filename")),
            str_at(g("created_at")),
            str_at(g("updated_at")),
            int_at(g("local_only")).unwrap_or(0),
            str_at(g("status")),
            int_at(g("pinned")).unwrap_or(0),
            str_at(g("deleted_at")),
            int_at(g("pages")),
            int_at(g("title_explicit")).unwrap_or(0),
            str_at(g("_device_id")),
            str_at(g("purged_at")),
            str_at(g("vaulted_at")),
            str_at(g("embedded_at")),
        ],
    )
    .map_err(|e| format!("insert artifact: {e}"))?;

    // Tags ride on the snapshot as a string array; store them as JSON for the
    // library's Tags view mode. Absent -> empty array.
    let tags_json = snapshot
        .get("tags")
        .filter(|v| v.is_array())
        .cloned()
        .unwrap_or_else(|| Value::Array(vec![]))
        .to_string();
    conn.execute(
        "UPDATE artifacts SET tags_json = ?1 WHERE id = ?2",
        rusqlite::params![tags_json, id],
    )
    .map_err(|e| e.to_string())?;

    for table in ["annotations", "page_text", "artifact_versions"] {
        conn.execute(&format!("DELETE FROM {table} WHERE artifact_id = ?1"), [id])
            .map_err(|e| e.to_string())?;
    }

    if let Some(anns) = snapshot["annotations"].as_array() {
        for a in anns {
            conn.execute(
                "INSERT INTO annotations (id,artifact_id,supersedes_id,text,created_at)\
                 VALUES (?1,?2,?3,?4,?5)",
                rusqlite::params![
                    str_at(a.get("id")),
                    id,
                    str_at(a.get("supersedes_id")),
                    str_at(a.get("text")),
                    str_at(a.get("created_at")),
                ],
            )
            .map_err(|e| format!("insert annotation: {e}"))?;
        }
    }
    if let Some(pages) = snapshot["page_text"].as_array() {
        for p in pages {
            conn.execute(
                "INSERT INTO page_text (artifact_id,page,text,extractor) VALUES (?1,?2,?3,?4)",
                rusqlite::params![
                    id,
                    int_at(p.get("page")),
                    str_at(p.get("text")),
                    str_at(p.get("extractor")),
                ],
            )
            .map_err(|e| format!("insert page_text: {e}"))?;
        }
    }
    if let Some(vers) = snapshot["versions"].as_array() {
        for v in vers {
            conn.execute(
                "INSERT INTO artifact_versions (id,artifact_id,body,created_at) VALUES (?1,?2,?3,?4)",
                rusqlite::params![
                    str_at(v.get("id")),
                    id,
                    str_at(v.get("body")),
                    str_at(v.get("created_at")),
                ],
            )
            .map_err(|e| format!("insert version: {e}"))?;
        }
    }

    // Facets replace only when the snapshot actually carries them (mirrors the engine):
    // a facet-less snapshot must not wipe facets already here, since the equal-key
    // re-apply would otherwise delete them.
    if let Some(facets) = snapshot.get("facets").and_then(|v| v.as_array()) {
        if !facets.is_empty() {
            conn.execute("DELETE FROM facets WHERE artifact_id = ?1", [id])
                .map_err(|e| e.to_string())?;
            for f in facets {
                conn.execute(
                    "INSERT INTO facets\
                     (id,artifact_id,level,statement,model_version,body_version,trust,edited) \
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8)",
                    rusqlite::params![
                        str_at(f.get("id")),
                        id,
                        int_at(f.get("level")),
                        str_at(f.get("statement")),
                        str_at(f.get("model_version")),
                        str_at(f.get("body_version")),
                        f.get("trust").and_then(|v| v.as_f64()),
                        int_at(f.get("edited")).unwrap_or(0),
                    ],
                )
                .map_err(|e| format!("insert facet: {e}"))?;
            }
        }
    }
    Ok(())
}

/// Apply a conversation snapshot: the mirror of the engine's apply_chat_snapshot.
/// Same (updated_at, _device_id) LWW and terminal-tombstone rules as apply_snapshot,
/// then the chat row upserts and its messages/citations/topics are replaced wholesale.
fn apply_chat_snapshot(conn: &Connection, snapshot: &Value) -> Result<(), String> {
    let chat = &snapshot["chat"];
    let id = chat["id"].as_str().ok_or("chat snapshot: missing id")?;

    let local: Option<(String, String, Option<String>)> = conn
        .query_row(
            "SELECT updated_at, COALESCE(_device_id,''), deleted_at FROM chats WHERE id = ?1",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    if let Some((local_updated, local_device, local_deleted)) = local {
        let incoming_deleted = chat.get("deleted_at").and_then(Value::as_str).is_some();
        if local_deleted.is_some() && !incoming_deleted {
            return Ok(()); // a delete is terminal and stays won
        }
        let inc_key = (
            chat["updated_at"].as_str().unwrap_or("").to_string(),
            chat.get("_device_id")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
        );
        if (local_updated, local_device) > inc_key {
            return Ok(());
        }
    }

    let g = |c: &str| chat.get(c);
    conn.execute(
        "INSERT INTO chats (id,title,scope_kind,scope_id,created_at,updated_at,pinned,deleted_at,_device_id)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)
         ON CONFLICT(id) DO UPDATE SET
           title=excluded.title, scope_kind=excluded.scope_kind, scope_id=excluded.scope_id,
           created_at=excluded.created_at, updated_at=excluded.updated_at, pinned=excluded.pinned,
           deleted_at=excluded.deleted_at, _device_id=excluded._device_id",
        rusqlite::params![
            id,
            str_at(g("title")),
            str_at(g("scope_kind")),
            str_at(g("scope_id")),
            str_at(g("created_at")),
            str_at(g("updated_at")),
            int_at(g("pinned")).unwrap_or(0),
            str_at(g("deleted_at")),
            str_at(g("_device_id")),
        ],
    )
    .map_err(|e| format!("insert chat: {e}"))?;

    conn.execute(
        "DELETE FROM chat_citations WHERE message_id IN \
         (SELECT id FROM chat_messages WHERE chat_id = ?1)",
        [id],
    )
    .map_err(|e| e.to_string())?;
    conn.execute("DELETE FROM chat_messages WHERE chat_id = ?1", [id])
        .map_err(|e| e.to_string())?;
    conn.execute("DELETE FROM chat_topics WHERE chat_id = ?1", [id])
        .map_err(|e| e.to_string())?;

    if let Some(msgs) = snapshot["messages"].as_array() {
        for m in msgs {
            conn.execute(
                "INSERT INTO chat_messages \
                 (id,chat_id,ordinal,role,text,grounded,created_at,kind,payload,status,error) \
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)",
                rusqlite::params![
                    str_at(m.get("id")),
                    id,
                    int_at(m.get("ordinal")),
                    str_at(m.get("role")),
                    str_at(m.get("text")),
                    int_at(m.get("grounded")),
                    str_at(m.get("created_at")),
                    str_at(m.get("kind")),
                    str_at(m.get("payload")),
                    str_at(m.get("status")),
                    str_at(m.get("error")),
                ],
            )
            .map_err(|e| format!("insert chat_message: {e}"))?;
        }
    }
    if let Some(cites) = snapshot["citations"].as_array() {
        for c in cites {
            conn.execute(
                "INSERT INTO chat_citations (message_id,artifact_id,rank) VALUES (?1,?2,?3)",
                rusqlite::params![
                    str_at(c.get("message_id")),
                    str_at(c.get("artifact_id")),
                    int_at(c.get("rank")),
                ],
            )
            .map_err(|e| format!("insert chat_citation: {e}"))?;
        }
    }
    if let Some(topics) = snapshot["topics"].as_array() {
        for t in topics {
            conn.execute(
                "INSERT INTO chat_topics (id,chat_id,topic,created_at) VALUES (?1,?2,?3,?4)",
                rusqlite::params![
                    str_at(t.get("id")),
                    id,
                    str_at(t.get("topic")),
                    str_at(t.get("created_at")),
                ],
            )
            .map_err(|e| format!("insert chat_topic: {e}"))?;
        }
    }
    Ok(())
}

#[allow(dead_code)]
fn read_cursor(conn: &Connection) -> Result<u64, String> {
    let v: Option<String> = conn
        .query_row(
            "SELECT value FROM sync_meta WHERE key = 'cursor'",
            [],
            |r| r.get(0),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    Ok(v.and_then(|s| s.parse().ok()).unwrap_or(0))
}

#[allow(dead_code)]
fn write_cursor(conn: &Connection, cursor: u64) -> Result<(), String> {
    conn.execute(
        "INSERT INTO sync_meta (key,value) VALUES ('cursor',?1) \
         ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        [cursor.to_string()],
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

/// The result of a sync attempt, reduced to a status the UI (MOB.3b) can show.
#[allow(dead_code)]
pub struct SyncOutcome {
    pub status: String, // "synced" | "locked" | "error"
    pub pulled: usize,
    pub error: Option<String>,
}

/// Pull the library from the relay into the local read copy. `dek` is None when the
/// keyring has not been unlocked; then the sync reports "locked" instead of crashing.
#[allow(dead_code)]
/// PERF.2: fetch and decrypt many artifact snapshots concurrently.
///
/// The pull used to do one blocking `GET /sync/object/{name}` per changed object,
/// so a cold backfill of a few hundred artifacts was a few hundred sequential
/// round trips (~100ms each over the internet). Network + decrypt touch no DB, so
/// a bounded worker pool runs them in parallel; the caller applies the results on
/// the single connection afterwards. Order is irrelevant - `apply_snapshot` is LWW
/// per artifact - and this changes no wire format: it is the same per-object GET,
/// just not serialized. Failures are skipped exactly as the sequential path did.
fn fetch_snapshots_parallel(
    base: &str,
    auth: &str,
    dek: &[u8; DEK_LEN],
    names: &[String],
) -> Vec<Value> {
    const WORKERS: usize = 8;
    if names.is_empty() {
        return Vec::new();
    }
    // One agent, cloned per worker: `ureq::Agent` is Send + Sync and shares a
    // connection pool, so cloning is cheap and keeps sockets warm across a chunk.
    let agent = ureq::AgentBuilder::new().build();
    let chunk = (names.len() + WORKERS - 1) / WORKERS;
    let mut out: Vec<Value> = Vec::new();
    std::thread::scope(|scope| {
        let handles: Vec<_> = names
            .chunks(chunk)
            .map(|group| {
                let agent = agent.clone();
                scope.spawn(move || {
                    let mut local: Vec<Value> = Vec::new();
                    for name in group {
                        let resp = match agent
                            .get(&format!("{base}/sync/object/{name}"))
                            .set("Authorization", auth)
                            .call()
                        {
                            Ok(r) => r,
                            Err(_) => continue, // unreachable relay: skip this object
                        };
                        if resp.status() != 200 {
                            continue;
                        }
                        let mut bytes = Vec::new();
                        if resp.into_reader().read_to_end(&mut bytes).is_err() {
                            continue;
                        }
                        // The payload is secretbox-encrypted (PERF.6): the LWW key is
                        // unreadable until after decrypt, so every fetched object is
                        // decrypted here; the caller's apply_snapshot does the no-op
                        // LWW check.
                        let plain = match secretbox_decrypt(dek, &bytes) {
                            Ok(p) => p,
                            Err(_) => continue, // unreadable = "not yet arrived"
                        };
                        if let Ok(v) = serde_json::from_slice::<Value>(&plain) {
                            local.push(v);
                        }
                    }
                    local
                })
            })
            .collect();
        for h in handles {
            if let Ok(mut v) = h.join() {
                out.append(&mut v);
            }
        }
    });
    out
}

pub fn sync_library(
    relay_url: &str,
    sync_secret: &str,
    dek: Option<&[u8; DEK_LEN]>,
    conn: &Connection,
) -> SyncOutcome {
    let Some(dek) = dek else {
        return SyncOutcome {
            status: "locked".into(),
            pulled: 0,
            error: None,
        };
    };

    let base = relay_url.trim_end_matches('/');
    let auth = format!("Bearer {sync_secret}");
    let cursor = match read_cursor(conn) {
        Ok(c) => c,
        Err(e) => {
            return SyncOutcome {
                status: "error".into(),
                pulled: 0,
                error: Some(e),
            }
        }
    };

    // List changed objects since the cursor.
    let listing = match ureq::get(&format!("{base}/sync/objects"))
        .query("since", &cursor.to_string())
        .set("Authorization", &auth)
        .call()
    {
        Ok(r) => r,
        Err(ureq::Error::Status(401, _)) => {
            return SyncOutcome {
                status: "error".into(),
                pulled: 0,
                error: Some("wrong sync secret".into()),
            }
        }
        Err(e) => {
            return SyncOutcome {
                status: "error".into(),
                pulled: 0,
                error: Some(e.to_string()),
            }
        }
    };
    let body: Value = match listing
        .into_string()
        .map_err(|e| e.to_string())
        .and_then(|s| serde_json::from_str(&s).map_err(|e| e.to_string()))
    {
        Ok(v) => v,
        Err(e) => {
            return SyncOutcome {
                status: "error".into(),
                pulled: 0,
                error: Some(e),
            }
        }
    };
    let new_cursor = body["cursor"].as_u64().unwrap_or(cursor);

    let mut pulled = 0usize;
    // PERF.2: artifact object names are collected here and fetched concurrently
    // after the listing walk; the library-level objects (pivots, settings) stay
    // inline since there are only a handful of them.
    let mut dev_names: Vec<String> = Vec::new();
    for obj in body["objects"].as_array().into_iter().flatten() {
        let Some(name) = obj["name"].as_str() else { continue };
        // Custom views (saved pivots) are a single library-level object; pull it,
        // decrypt, and cache the JSON in sync_meta for the Custom view mode.
        if name == "lib/pivots.enc" {
            if let Ok(r) = ureq::get(&format!("{base}/sync/object/{name}"))
                .set("Authorization", &auth)
                .call()
            {
                let mut bytes = Vec::new();
                if r.status() == 200 && r.into_reader().read_to_end(&mut bytes).is_ok() {
                    if let Ok(plain) = secretbox_decrypt(dek, &bytes) {
                        if let Ok(s) = std::str::from_utf8(&plain) {
                            let _ = conn.execute(
                                "INSERT INTO sync_meta (key,value) VALUES ('pivots',?1)\
                                 ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                [s],
                            );
                        }
                    }
                }
            }
            continue;
        }
        // The PIN-wrapped vault key (VAULT.2b): decrypt the DEK layer and cache the
        // wrap in sync_meta so this device can unlock the same vault with the same
        // PIN. The inner value is still PIN-wrapped, so the DEK alone cannot read it.
        if name == "lib/vault.enc" {
            if let Ok(r) = ureq::get(&format!("{base}/sync/object/{name}"))
                .set("Authorization", &auth)
                .call()
            {
                let mut bytes = Vec::new();
                if r.status() == 200 && r.into_reader().read_to_end(&mut bytes).is_ok() {
                    if let Ok(plain) = secretbox_decrypt(dek, &bytes) {
                        if let Ok(s) = std::str::from_utf8(&plain) {
                            let _ = conn.execute(
                                "INSERT INTO sync_meta (key,value) VALUES ('vault_meta',?1)\
                                 ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                [s],
                            );
                        }
                    }
                }
            }
            continue;
        }
        // Desktop settings (MOB2.9): the desktop's effective LLM config - backend,
        // model, url, and the provider api_key - encrypted under the DEK. Each push
        // is a fresh timestamped object; keep the newest by `updated_at` so a later
        // desktop edit wins, and cache it in sync_meta for mobile_chat / settings to
        // read. This is what makes the desktop config propagate fully to the phone.
        if name.starts_with("lib/settings/") {
            if let Ok(r) = ureq::get(&format!("{base}/sync/object/{name}"))
                .set("Authorization", &auth)
                .call()
            {
                let mut bytes = Vec::new();
                if r.status() == 200 && r.into_reader().read_to_end(&mut bytes).is_ok() {
                    if let Ok(plain) = secretbox_decrypt(dek, &bytes) {
                        if let Ok(incoming) = serde_json::from_slice::<Value>(&plain) {
                            let incoming_ts =
                                incoming["updated_at"].as_str().unwrap_or("").to_string();
                            let stored_ts: String = conn
                                .query_row(
                                    "SELECT value FROM sync_meta WHERE key = 'settings'",
                                    [],
                                    |row| row.get::<_, String>(0),
                                )
                                .ok()
                                .and_then(|s| serde_json::from_str::<Value>(&s).ok())
                                .and_then(|v| {
                                    v["updated_at"].as_str().map(str::to_string)
                                })
                                .unwrap_or_default();
                            // ISO-8601 timestamps sort lexicographically.
                            if incoming_ts >= stored_ts {
                                if let Ok(s) = std::str::from_utf8(&plain) {
                                    let _ = conn.execute(
                                        "INSERT INTO sync_meta (key,value) VALUES ('settings',?1)\
                                         ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                        [s],
                                    );
                                }
                            }
                        }
                    }
                }
            }
            continue;
        }
        // Blobs are fetched on demand (MOB.5), not pulled here.
        if !name.starts_with("dev/") || !name.ends_with(".enc") {
            continue;
        }
        // PERF.2: defer the artifact fetch. Collect the name and pull them all
        // concurrently below instead of one blocking GET per object here.
        dev_names.push(name.to_string());
    }

    // PERF.2: fetch + decrypt every artifact snapshot concurrently (no DB touched),
    // then apply them on the single connection. `apply_snapshot` is LWW per artifact,
    // so the order they come back in does not matter, and the stale/no-op LWW check
    // still runs on each one - we just no longer pay hundreds of round trips in
    // series. (Why every object is decrypted at all: PERF.6 - the payload is
    // secretbox-encrypted, so the LWW key cannot be peeked before decrypt.)
    let mut failed = 0usize;
    for snapshot in fetch_snapshots_parallel(base, &auth, dek, &dev_names) {
        // The snapshot names itself: a conversation carries a `chat` object, an
        // artifact a `artifact` one. Route each to its own apply.
        let applied = if snapshot.get("chat").is_some() {
            apply_chat_snapshot(conn, &snapshot)
        } else {
            apply_snapshot(conn, &snapshot)
        };
        match applied {
            Ok(()) => pulled += 1,
            Err(e) => {
                failed += 1;
                eprintln!("[sync] apply skipped one snapshot: {e}");
            }
        }
    }

    // Only advance the cursor when every snapshot in this window applied. If one
    // failed (e.g. a schema the phone has not caught up to yet), keep the old cursor
    // so the next sync re-pulls and retries it, instead of stepping past it and
    // losing the artifact silently. Re-applied successes are LWW no-ops, so retrying
    // the whole window is safe.
    let cursor_to_write = if failed == 0 { new_cursor } else { cursor };
    if let Err(e) = write_cursor(conn, cursor_to_write) {
        return SyncOutcome {
            status: "error".into(),
            pulled,
            error: Some(e),
        };
    }

    SyncOutcome {
        status: "synced".into(),
        pulled,
        error: None,
    }
}

/// Artifact ids present in the local read copy, newest first, excluding trashed rows.
#[allow(dead_code)]
pub fn list_artifact_ids(conn: &Connection) -> Result<Vec<String>, String> {
    let mut stmt = conn
        .prepare("SELECT id FROM artifacts WHERE deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL ORDER BY updated_at DESC")
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |r| r.get::<_, String>(0))
        .map_err(|e| e.to_string())?;
    let mut ids = Vec::new();
    for row in rows {
        ids.push(row.map_err(|e| e.to_string())?);
    }
    Ok(ids)
}

/// Conversation rows for the eye panel's list: id, title, pinned, updated_at, and the
/// topics it circles. Pinned first then newest; tombstones excluded.
#[allow(dead_code)]
pub fn list_chats(conn: &Connection) -> Result<Vec<Value>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT id, title, pinned, updated_at FROM chats \
             WHERE deleted_at IS NULL ORDER BY pinned DESC, updated_at DESC LIMIT 100",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, i64>(2)?,
                r.get::<_, String>(3)?,
            ))
        })
        .map_err(|e| e.to_string())?;
    let mut out = Vec::new();
    for row in rows {
        let (id, title, pinned, updated_at) = row.map_err(|e| e.to_string())?;
        let mut topics = Vec::new();
        let mut tstmt = conn
            .prepare("SELECT topic FROM chat_topics WHERE chat_id = ?1 ORDER BY created_at")
            .map_err(|e| e.to_string())?;
        let trows = tstmt
            .query_map([&id], |r| r.get::<_, String>(0))
            .map_err(|e| e.to_string())?;
        for t in trows {
            topics.push(t.map_err(|e| e.to_string())?);
        }
        out.push(serde_json::json!({
            "id": id, "title": title, "pinned": pinned,
            "updated_at": updated_at, "topics": topics,
        }));
    }
    Ok(out)
}

/// One conversation's transcript for the reader: the chat plus its messages in order,
/// each with the artifact ids it cited (and their local titles when present).
#[allow(dead_code)]
pub fn get_chat(conn: &Connection, id: &str) -> Result<Value, String> {
    let chat: Option<(String, String, Option<String>, Option<String>, i64)> = conn
        .query_row(
            "SELECT id, title, scope_kind, scope_id, pinned FROM chats \
             WHERE id = ?1 AND deleted_at IS NULL",
            [id],
            |r| {
                Ok((
                    r.get(0)?,
                    r.get(1)?,
                    r.get(2)?,
                    r.get(3)?,
                    r.get(4)?,
                ))
            },
        )
        .optional()
        .map_err(|e| e.to_string())?;
    let (cid, title, scope_kind, scope_id, pinned) = chat.ok_or("no such chat")?;

    let mut stmt = conn
        .prepare(
            "SELECT id, role, text, kind, status FROM chat_messages \
             WHERE chat_id = ?1 ORDER BY ordinal",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([&cid], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, Option<String>>(2)?,
                r.get::<_, Option<String>>(3)?,
                r.get::<_, Option<String>>(4)?,
            ))
        })
        .map_err(|e| e.to_string())?;
    let mut messages = Vec::new();
    for row in rows {
        let (mid, role, text, kind, status) = row.map_err(|e| e.to_string())?;
        // Citations: the artifact ids this message stood on, with a local title if the
        // artifact synced here too (it usually has).
        let mut cstmt = conn
            .prepare(
                "SELECT c.artifact_id, a.title FROM chat_citations c \
                 LEFT JOIN artifacts a ON a.id = c.artifact_id \
                 WHERE c.message_id = ?1 ORDER BY c.rank",
            )
            .map_err(|e| e.to_string())?;
        let crows = cstmt
            .query_map([&mid], |r| {
                Ok(serde_json::json!({
                    "artifact_id": r.get::<_, String>(0)?,
                    "title": r.get::<_, Option<String>>(1)?,
                }))
            })
            .map_err(|e| e.to_string())?;
        let mut cited = Vec::new();
        for c in crows {
            cited.push(c.map_err(|e| e.to_string())?);
        }
        messages.push(serde_json::json!({
            "id": mid, "role": role, "text": text,
            "kind": kind, "status": status, "cited": cited,
        }));
    }
    Ok(serde_json::json!({
        "chat": {
            "id": cid, "title": title, "scope_kind": scope_kind,
            "scope_id": scope_id, "pinned": pinned,
        },
        "messages": messages,
    }))
}

/// Serialize a conversation for the relay: the mirror of the engine's
/// read_chat_snapshot. Children ordered so the canonical JSON is byte-stable.
#[allow(dead_code)]
pub fn build_chat_snapshot(conn: &Connection, id: &str) -> Result<Option<Value>, String> {
    let chat: Option<Value> = conn
        .query_row("SELECT * FROM chats WHERE id = ?1", [id], |r| {
            Ok(serde_json::json!({
                "id": r.get::<_, String>("id")?,
                "title": r.get::<_, String>("title")?,
                "scope_kind": r.get::<_, Option<String>>("scope_kind")?,
                "scope_id": r.get::<_, Option<String>>("scope_id")?,
                "created_at": r.get::<_, String>("created_at")?,
                "updated_at": r.get::<_, String>("updated_at")?,
                "pinned": r.get::<_, i64>("pinned")?,
                "deleted_at": r.get::<_, Option<String>>("deleted_at")?,
                "_device_id": r.get::<_, Option<String>>("_device_id")?,
            }))
        })
        .optional()
        .map_err(|e| e.to_string())?;
    let chat = match chat {
        Some(c) => c,
        None => return Ok(None),
    };

    let mut mstmt = conn
        .prepare(
            "SELECT id,chat_id,ordinal,role,text,grounded,created_at,kind,payload,status,error \
             FROM chat_messages WHERE chat_id = ?1 ORDER BY ordinal, id",
        )
        .map_err(|e| e.to_string())?;
    let messages: Vec<Value> = mstmt
        .query_map([id], |r| {
            Ok(serde_json::json!({
                "id": r.get::<_, String>(0)?,
                "chat_id": r.get::<_, String>(1)?,
                "ordinal": r.get::<_, Option<i64>>(2)?,
                "role": r.get::<_, Option<String>>(3)?,
                "text": r.get::<_, Option<String>>(4)?,
                "grounded": r.get::<_, Option<i64>>(5)?,
                "created_at": r.get::<_, Option<String>>(6)?,
                "kind": r.get::<_, Option<String>>(7)?,
                "payload": r.get::<_, Option<String>>(8)?,
                "status": r.get::<_, Option<String>>(9)?,
                "error": r.get::<_, Option<String>>(10)?,
            }))
        })
        .map_err(|e| e.to_string())?
        .collect::<Result<_, _>>()
        .map_err(|e| e.to_string())?;

    let mut cstmt = conn
        .prepare(
            "SELECT c.message_id, c.artifact_id, c.rank FROM chat_citations c \
             JOIN chat_messages m ON m.id = c.message_id \
             WHERE m.chat_id = ?1 ORDER BY c.message_id, c.rank",
        )
        .map_err(|e| e.to_string())?;
    let citations: Vec<Value> = cstmt
        .query_map([id], |r| {
            Ok(serde_json::json!({
                "message_id": r.get::<_, String>(0)?,
                "artifact_id": r.get::<_, String>(1)?,
                "rank": r.get::<_, Option<i64>>(2)?,
            }))
        })
        .map_err(|e| e.to_string())?
        .collect::<Result<_, _>>()
        .map_err(|e| e.to_string())?;

    let mut tstmt = conn
        .prepare(
            "SELECT id, chat_id, topic, created_at FROM chat_topics \
             WHERE chat_id = ?1 ORDER BY created_at, id",
        )
        .map_err(|e| e.to_string())?;
    let topics: Vec<Value> = tstmt
        .query_map([id], |r| {
            Ok(serde_json::json!({
                "id": r.get::<_, String>(0)?,
                "chat_id": r.get::<_, String>(1)?,
                "topic": r.get::<_, Option<String>>(2)?,
                "created_at": r.get::<_, Option<String>>(3)?,
            }))
        })
        .map_err(|e| e.to_string())?
        .collect::<Result<_, _>>()
        .map_err(|e| e.to_string())?;

    Ok(Some(serde_json::json!({
        "chat": chat,
        "messages": messages,
        "citations": citations,
        "topics": topics,
    })))
}

/// Push a conversation snapshot to the relay under this device's chat namespace.
#[allow(dead_code)]
pub fn push_chat_snapshot(
    base: &str,
    secret: &str,
    device: &str,
    dek: &[u8; DEK_LEN],
    snapshot: &Value,
) -> Result<(), String> {
    let id = snapshot["chat"]["id"].as_str().unwrap_or("");
    let name = format!("dev/{device}/chats/{id}.enc");
    let plaintext = serde_json::to_vec(snapshot).map_err(|e| e.to_string())?;
    let body = secretbox_encrypt(dek, &plaintext)?;
    let url = format!("{}/sync/object/{name}", base.trim_end_matches('/'));
    put_object_with_retry(&url, secret, &body, "chat")
}

/// The library rows for the Library surface (MOB.4): id, kind, title, body (for the
/// snippet), timestamps, and capture metadata. Newest first, trashed excluded.
#[allow(dead_code)]
pub fn list_artifacts(conn: &Connection) -> Result<Vec<Value>, String> {
    let mut stmt = conn
        .prepare(
            // body is trimmed to a prefix: the library card shows a 3-line clamped
            // excerpt, so shipping full note bodies bloated this payload ~5x for nothing
            // (the reader fetches the full body via mobile_get). 280 chars covers 3 lines.
            "SELECT id,kind,title,substr(body,1,280),source_url,mime,filename,created_at,updated_at,pinned,status,tags_json
             FROM artifacts WHERE deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL ORDER BY updated_at DESC",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |r| {
            let tags: Value = r
                .get::<_, Option<String>>(11)?
                .and_then(|s| serde_json::from_str(&s).ok())
                .unwrap_or_else(|| Value::Array(vec![]));
            Ok(serde_json::json!({
                "id": r.get::<_, String>(0)?,
                "kind": r.get::<_, String>(1)?,
                "title": r.get::<_, String>(2)?,
                "body": r.get::<_, Option<String>>(3)?,
                "source_url": r.get::<_, Option<String>>(4)?,
                "mime": r.get::<_, Option<String>>(5)?,
                "filename": r.get::<_, Option<String>>(6)?,
                "created_at": r.get::<_, String>(7)?,
                "updated_at": r.get::<_, String>(8)?,
                "pinned": r.get::<_, i64>(9)?,
                "status": r.get::<_, String>(10)?,
                "tags": tags,
            }))
        })
        .map_err(|e| e.to_string())?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(|e| e.to_string())?);
    }
    Ok(out)
}

/// One artifact plus its annotations, for the Reader surface (MOB.5).
#[allow(dead_code)]
pub fn get_artifact(conn: &Connection, id: &str) -> Result<Value, String> {
    let artifact: Option<Value> = conn
        .query_row(
            "SELECT id,kind,title,body,source_url,content_hash,mime,filename,created_at,updated_at,pinned,pages
             FROM artifacts WHERE id = ?1",
            [id],
            |r| {
                Ok(serde_json::json!({
                    "id": r.get::<_, String>(0)?,
                    "kind": r.get::<_, String>(1)?,
                    "title": r.get::<_, String>(2)?,
                    "body": r.get::<_, Option<String>>(3)?,
                    "source_url": r.get::<_, Option<String>>(4)?,
                    "content_hash": r.get::<_, Option<String>>(5)?,
                    "mime": r.get::<_, Option<String>>(6)?,
                    "filename": r.get::<_, Option<String>>(7)?,
                    "created_at": r.get::<_, String>(8)?,
                    "updated_at": r.get::<_, String>(9)?,
                    "pinned": r.get::<_, i64>(10)?,
                    "pages": r.get::<_, Option<i64>>(11)?,
                }))
            },
        )
        .optional()
        .map_err(|e| e.to_string())?;
    let Some(artifact) = artifact else {
        return Err("not found".into());
    };
    
    // For link artifacts, also fetch preview data (title, description, site_name, image_hash, image_mime)
    let mut preview: Option<Value> = None;
    if artifact["kind"] == "link" {
        let preview_row: Option<Value> = conn
            .query_row(
                "SELECT title,description,site_name,image_hash,image_mime FROM link_previews WHERE artifact_id = ?1 AND status = 'ok'",
                [id],
                |r| {
                    Ok(serde_json::json!({
                        "title": r.get::<_, Option<String>>(0)?,
                        "description": r.get::<_, Option<String>>(1)?,
                        "site_name": r.get::<_, Option<String>>(2)?,
                        "image_hash": r.get::<_, Option<String>>(3)?,
                        "image_mime": r.get::<_, Option<String>>(4)?,
                    }))
                },
            )
            .optional()
            .map_err(|e| e.to_string())?;
        preview = preview_row;
    }

    let mut anns = Vec::new();
    let mut stmt = conn
        .prepare(
            "SELECT id,text,created_at FROM annotations WHERE artifact_id = ?1
             ORDER BY created_at, id",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([id], |r| {
            Ok(serde_json::json!({
                "id": r.get::<_, String>(0)?,
                "text": r.get::<_, String>(1)?,
                "created_at": r.get::<_, String>(2)?,
            }))
        })
        .map_err(|e| e.to_string())?;
    for row in rows {
        anns.push(row.map_err(|e| e.to_string())?);
    }

    // The summary (facets), synced from the desktop that generated it. Ordered by level
    // so the reader shows them concrete-to-abstract, like the desktop drawer.
    let mut facets = Vec::new();
    let mut fstmt = conn
        .prepare(
            "SELECT id, level, statement, edited FROM facets WHERE artifact_id = ?1 \
             ORDER BY level, statement, id",
        )
        .map_err(|e| e.to_string())?;
    let frows = fstmt
        .query_map([id], |r| {
            Ok(serde_json::json!({
                "id": r.get::<_, String>(0)?,
                "level": r.get::<_, Option<i64>>(1)?,
                "statement": r.get::<_, Option<String>>(2)?,
                "edited": r.get::<_, i64>(3)?,
            }))
        })
        .map_err(|e| e.to_string())?;
    for row in frows {
        facets.push(row.map_err(|e| e.to_string())?);
    }
    Ok(serde_json::json!({
        "artifact": artifact, "annotations": anns, "preview": preview, "facets": facets,
    }))
}

/// Rewrite one facet from the phone: mark it edited + full-trust, and bump the artifact's
/// updated_at so the edit wins LWW and reaches the desktop when the artifact is pushed.
pub fn edit_facet_local(conn: &Connection, facet_id: &str, statement: &str) -> Result<String, String> {
    let aid: Option<String> = conn
        .query_row("SELECT artifact_id FROM facets WHERE id = ?1", [facet_id], |r| r.get(0))
        .optional()
        .map_err(|e| e.to_string())?;
    let aid = aid.ok_or("no such facet")?;
    conn.execute(
        "UPDATE facets SET statement = ?1, edited = 1, trust = 1.0 WHERE id = ?2",
        rusqlite::params![statement, facet_id],
    )
    .map_err(|e| e.to_string())?;
    Ok(aid)
}

/// Remove one facet from the phone. Returns its artifact id for the caller to push.
pub fn delete_facet_local(conn: &Connection, facet_id: &str) -> Result<String, String> {
    let aid: Option<String> = conn
        .query_row("SELECT artifact_id FROM facets WHERE id = ?1", [facet_id], |r| r.get(0))
        .optional()
        .map_err(|e| e.to_string())?;
    let aid = aid.ok_or("no such facet")?;
    conn.execute("DELETE FROM facets WHERE id = ?1", [facet_id])
        .map_err(|e| e.to_string())?;
    Ok(aid)
}

/// Record one activity-log event (persisted, mirrors the engine's events table). The
/// `data` blob is opened on demand in the Activity view; `duration_ms` is the action's
/// wall time when known. Best effort: a logging failure never fails the real action.
pub fn log_event(
    conn: &Connection,
    kind: &str,
    detail: &str,
    data: Option<&Value>,
    duration_ms: Option<i64>,
) {
    let blob = data.map(|d| {
        let s = d.to_string();
        if s.len() > 20000 {
            s[..20000].to_string()
        } else {
            s
        }
    });
    let ts = chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S").to_string();
    let _ = conn.execute(
        "INSERT INTO events (ts, kind, detail, data, duration_ms) VALUES (?1,?2,?3,?4,?5)",
        rusqlite::params![ts, kind, detail, blob, duration_ms],
    );
    // Keep the log bounded; trim occasionally rather than on every write.
    let _ = conn.execute(
        "DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - 2000",
        [],
    );
}

/// The most recent events, newest first, each with its parsed `data`.
pub fn read_events(conn: &Connection, limit: i64) -> Result<Vec<Value>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT id, ts, kind, detail, data, duration_ms FROM events \
             ORDER BY id DESC LIMIT ?1",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([limit.clamp(1, 2000)], |r| {
            let data_str: Option<String> = r.get(4)?;
            let data = data_str
                .and_then(|s| serde_json::from_str::<Value>(&s).ok())
                .unwrap_or(Value::Null);
            Ok(serde_json::json!({
                "id": r.get::<_, i64>(0)?,
                "ts": r.get::<_, String>(1)?,
                "kind": r.get::<_, String>(2)?,
                "detail": r.get::<_, String>(3)?,
                "data": data,
                "duration_ms": r.get::<_, Option<i64>>(5)?,
            }))
        })
        .map_err(|e| e.to_string())?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(|e| e.to_string())?);
    }
    Ok(out)
}

/// Keyword search over titles, bodies, and annotations (MOB.6). No embeddings, no
/// model - a plain case-insensitive substring match, the same honesty as the desktop's
/// keyword leg. Returns library rows, newest first.
#[allow(dead_code)]
pub fn search_artifacts(conn: &Connection, query: &str) -> Result<Vec<Value>, String> {
    // A question ("do I have any docker notes?") used to be matched as one literal
    // substring, so it found nothing and the answer path returned canned "no match"
    // without ever calling the model. Instead break the query into keywords, drop the
    // stopwords, and match any of them - ranked by how many distinct terms an artifact
    // hits, then recency. This is the phone's honest keyword leg: no embeddings, but it
    // actually finds the docker note when you ask about docker.
    let terms = query_terms(query);
    if terms.is_empty() {
        // No meaningful keywords (a very short or all-stopword query): fall back to the
        // whole trimmed string as one substring, so "docker" still works.
        return search_like(conn, &[query.trim().to_lowercase()]);
    }
    search_like(conn, &terms)
}

/// Keywords worth matching: lowercased, split on non-alphanumerics, stopwords and
/// one-character tokens dropped, de-duplicated, capped so a rambling query stays cheap.
fn query_terms(query: &str) -> Vec<String> {
    const STOP: &[&str] = &[
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "do",
        "did", "does", "i", "you", "my", "me", "any", "have", "has", "had", "what", "which",
        "that", "this", "with", "about", "from", "it", "be", "can", "could", "would", "should",
        "there", "here", "get", "got", "some", "all", "how", "when", "where", "who", "note",
        "notes", "saved", "save",
    ];
    let mut seen = std::collections::HashSet::new();
    let mut out = Vec::new();
    for raw in query.split(|c: char| !c.is_alphanumeric()) {
        let t = raw.trim().to_lowercase();
        if t.len() < 2 || STOP.contains(&t.as_str()) {
            continue;
        }
        if seen.insert(t.clone()) {
            out.push(t);
        }
        if out.len() >= 12 {
            break;
        }
    }
    out
}

/// Run the keyword match: OR the terms across title, body, and annotations, rank each
/// artifact by how many distinct terms it hits, then by recency. Returns library rows.
fn search_like(conn: &Connection, terms: &[String]) -> Result<Vec<Value>, String> {
    let terms: Vec<String> = terms.iter().filter(|t| !t.is_empty()).cloned().collect();
    if terms.is_empty() {
        return Ok(Vec::new());
    }
    // Per term: 1 if any of the artifact's rows (incl. its annotations) matched it. The
    // sum of those is the distinct-term hit count the ranking uses.
    let mut score_parts = Vec::new();
    let mut where_parts = Vec::new();
    for i in 1..=terms.len() {
        score_parts.push(format!(
            "MAX(CASE WHEN a.title LIKE ?{i} OR a.body LIKE ?{i} OR an.text LIKE ?{i} THEN 1 ELSE 0 END)"
        ));
        where_parts.push(format!("a.title LIKE ?{i} OR a.body LIKE ?{i} OR an.text LIKE ?{i}"));
    }
    let sql = format!(
        "SELECT a.id,a.kind,a.title,substr(a.body,1,280),a.source_url,a.mime,a.filename,
                a.created_at,a.updated_at,a.pinned,
                ({score}) AS hits
         FROM artifacts a
         LEFT JOIN annotations an ON an.artifact_id = a.id
         WHERE a.deleted_at IS NULL AND a.vaulted_at IS NULL AND ({wh})
         GROUP BY a.id
         ORDER BY hits DESC, a.updated_at DESC
         LIMIT 40",
        score = score_parts.join(" + "),
        wh = where_parts.join(" OR "),
    );
    let needles: Vec<String> = terms.iter().map(|t| format!("%{t}%")).collect();
    let params: Vec<&dyn rusqlite::ToSql> = needles.iter().map(|n| n as &dyn rusqlite::ToSql).collect();
    let mut stmt = conn.prepare(&sql).map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map(params.as_slice(), |r| {
            Ok(serde_json::json!({
                "id": r.get::<_, String>(0)?,
                "kind": r.get::<_, String>(1)?,
                "title": r.get::<_, String>(2)?,
                "body": r.get::<_, Option<String>>(3)?,
                "source_url": r.get::<_, Option<String>>(4)?,
                "mime": r.get::<_, Option<String>>(5)?,
                "filename": r.get::<_, Option<String>>(6)?,
                "created_at": r.get::<_, String>(7)?,
                "updated_at": r.get::<_, String>(8)?,
                "pinned": r.get::<_, i64>(9)?,
            }))
        })
        .map_err(|e| e.to_string())?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(|e| e.to_string())?);
    }
    Ok(out)
}

/// A rough mirror of `notes.py:title_from_body` for the capture path: the first
/// markdown heading, else the first non-empty line, `*_`` stripped, capped at 120.
#[allow(dead_code)]
pub fn title_hint(body: &str) -> String {
    for line in body.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let s = if line.starts_with('#') {
            line.trim_start_matches('#').trim_start()
        } else {
            line
        };
        let cleaned: String = s.chars().filter(|c| !"*_`".contains(*c)).collect();
        let cleaned = cleaned.trim();
        if !cleaned.is_empty() {
            return cleaned.chars().take(120).collect();
        }
    }
    "Untitled".to_string()
}

/// The content-addressed blob name: HMAC-SHA256 of the content hash keyed by the DEK
/// (mirrors `crypto.blob_name`), so a blob's address leaks nothing about its contents.
#[allow(dead_code)]
#[allow(dead_code)]
pub fn blob_name(content_hash: &str, dek: &[u8; DEK_LEN]) -> String {
    use hmac::{Hmac, Mac};
    use sha2::Sha256;
    let mut mac = Hmac::<Sha256>::new_from_slice(dek).map_err(|e| e.to_string()).unwrap();
    mac.update(content_hash.as_bytes());
    hex::encode(mac.finalize().into_bytes())
}

/// Upload one file blob to the relay, encrypted and content-addressed exactly as
/// `fetch_blob` expects (`blobs/{HMAC(content_hash, DEK)}`, secretbox under the
/// DEK). This is the mobile capture counterpart to the desktop `push_artifact`
/// blob push: without it a picture taken or uploaded on the phone never leaves the
/// phone - notes and links carry no blob, but an image/pdf/file needs its bytes on
/// the relay for any other device to fetch them (MOB.5). Idempotent: a re-push of
/// the same content-addressed name returns 409, which is accepted.
pub fn push_blob(
    relay_url: &str,
    secret: &str,
    dek: &[u8; DEK_LEN],
    content_hash: &str,
    plaintext: &[u8],
) -> Result<(), String> {
    let name = blob_name(content_hash, dek);
    let ciphertext = secretbox_encrypt(dek, plaintext)?;
    let url = format!("{}/sync/object/blobs/{}", relay_url.trim_end_matches('/'), name);
    put_object_with_retry(&url, secret, &ciphertext, "push_blob")
}

/// Fetch + decrypt one file blob (an image/PDF/file) from the relay (MOB.5). The blob
/// is fetched on demand, cached by the caller.
#[allow(dead_code)]
pub fn fetch_blob(
    relay_url: &str,
    secret: &str,
    dek: &[u8; DEK_LEN],
    content_hash: &str,
) -> Result<Vec<u8>, String> {
    let name = blob_name(content_hash, dek);
    let resp = ureq::get(&format!(
        "{}/sync/object/blobs/{}",
        relay_url.trim_end_matches('/'),
        name
    ))
    .set("Authorization", &format!("Bearer {secret}"))
    .call()
    .map_err(|e| e.to_string())?;
    if resp.status() != 200 {
        return Err(format!("blob fetch: {}", resp.status()));
    }
    let mut bytes = Vec::new();
    resp.into_reader()
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    secretbox_decrypt(dek, &bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn argon2_matches_the_desktop_preset() {
        // A fixed vector: derive_kek("phrase", 16-byte salt) must be deterministic and
        // 32 bytes; the exact bytes are verified against Python in the integration run.
        let salt = [0u8; 16];
        let a = derive_kek("recovery", &salt).unwrap();
        let b = derive_kek("recovery", &salt).unwrap();
        assert_eq!(a, b);
        assert_ne!(a, derive_kek("other", &salt).unwrap());
    }

    #[test]
    fn matches_python_secretbox() {
        // Fixed vectors from `crypto.derive_kek` + `crypto.wrap` (Python), so a
        // divergence on either side (argon2 params or the stream cipher) is caught.
        let salt: Vec<u8> = (0..16).collect();
        let kek = derive_kek("test-password", &salt).unwrap();
        assert_eq!(
            hex::encode(kek),
            "1713a0b809a695d0af33d5db9dd84e5637b461700afc3410c78e53de1ce598d7"
        );
        let ct = hex::decode(
            "86bddcee138a8a9287a5a66d9831b8ffa0068a1c16896140de19273ce906d1af\
             9ebe38c624169fe9d85e2c1d23ae93cc4449984cb18e60d5d7e1e090",
        )
        .unwrap();
        assert_eq!(secretbox_decrypt(&kek, &ct).unwrap(), b"hello cross-language");
    }

    #[test]
    fn secretbox_round_trips() {
        use xsalsa20poly1305::aead::{Aead, KeyInit};
        use xsalsa20poly1305::{Nonce, XSalsa20Poly1305};
        let key = [7u8; 32];
        let nonce = [1u8; 24];
        let cipher = XSalsa20Poly1305::new_from_slice(&key).unwrap();
        let ct = cipher.encrypt(Nonce::from_slice(&nonce), b"hello".as_slice()).unwrap();
        // Prepend the nonce to mimic SecretBox's wire format, then decrypt via ours.
        let mut wire = nonce.to_vec();
        wire.extend_from_slice(&ct);
        assert_eq!(secretbox_decrypt(&key, &wire).unwrap(), b"hello");
    }

    #[test]
    fn apply_and_list() {
        let conn = Connection::open_in_memory().unwrap();
        init_schema(&conn).unwrap();
        let snap: Value = serde_json::from_str(
            r#"{
              "artifact": {"id":"a1","kind":"note","title":"t","body":"b","source_url":null,
                "content_hash":"h","mime":null,"filename":null,"created_at":"2026-01-01T00:00:00Z",
                "updated_at":"2026-01-01T00:00:00Z","local_only":0,"status":"ok","pinned":0,
                "deleted_at":null,"pages":null,"title_explicit":0,"_device_id":"d1"},
              "annotations": [], "page_text": [], "versions": []
            }"#,
        )
        .unwrap();
        apply_snapshot(&conn, &snap).unwrap();
        assert_eq!(list_artifact_ids(&conn).unwrap(), vec!["a1".to_string()]);
    }

    #[test]
    fn get_link_artifact_without_a_preview_row_does_not_error() {
        // Regression: opening a link on a fresh phone hit `link_previews` before the
        // table existed and failed with "no such table". init_schema now creates it,
        // so the read returns a null preview instead of crashing.
        let conn = Connection::open_in_memory().unwrap();
        init_schema(&conn).unwrap();
        let snap: Value = serde_json::from_str(
            r#"{
              "artifact": {"id":"l1","kind":"link","title":"t","body":null,
                "source_url":"https://example.com","content_hash":null,"mime":null,"filename":null,
                "created_at":"2026-01-01T00:00:00Z","updated_at":"2026-01-01T00:00:00Z",
                "local_only":0,"status":"ok","pinned":0,"deleted_at":null,"pages":null,
                "title_explicit":0,"_device_id":"d1"},
              "annotations": [], "page_text": [], "versions": []
            }"#,
        )
        .unwrap();
        apply_snapshot(&conn, &snap).unwrap();
        let detail = get_artifact(&conn, "l1").unwrap();
        assert!(detail["preview"].is_null());
    }

    #[test]
    fn mob3_integration_against_a_real_relay() {
        // Reads /tmp/mob3_config.json (written by the Python setup script) and verifies
        // the full pull -> decrypt -> list against a real relay. Skips quietly when the
        // config is absent, so `cargo test` needs no setup.
        let cfg_str = match std::fs::read_to_string("/tmp/mob3_config.json") {
            Ok(s) => s,
            Err(_) => {
                eprintln!("mob3 config not present; skipping integration test");
                return;
            }
        };
        let cfg: Value = serde_json::from_str(&cfg_str).unwrap();
        let relay_url = cfg["relay_url"].as_str().unwrap();
        let secret = cfg["secret"].as_str().unwrap();
        let keyring_json = cfg["keyring_json"].as_str().unwrap();
        let phrase = cfg["phrase"].as_str().unwrap();
        let mut expected: Vec<String> = cfg["ids"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();

        let conn = Connection::open_in_memory().unwrap();
        init_schema(&conn).unwrap();

        // Locked path: no DEK -> "locked", never a crash.
        let locked = sync_library(relay_url, secret, None, &conn);
        assert_eq!(locked.status, "locked");

        // Unlocked: pull + decrypt + list.
        let dek = unlock_dek(keyring_json, phrase).unwrap();
        let outcome = sync_library(relay_url, secret, Some(&dek), &conn);
        assert_eq!(outcome.status, "synced", "error: {:?}", outcome.error);
        let mut ids = list_artifact_ids(&conn).unwrap();
        ids.sort();
        expected.sort();
        assert_eq!(ids, expected, "pulled ids do not match the pushed snapshots");
    }
}

/// Update a note's body, appending a version and respecting title_explicit (MOB2.4).
/// Returns the updated artifact.
#[allow(dead_code)]
pub fn update_note_body(conn: &Connection, artifact_id: &str, new_body: &str, new_title: Option<&str>) -> Result<Value, String> {
    let now = chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.6f+00:00").to_string();
    
    // Check if artifact exists and is a note
    let artifact: Option<Value> = conn
        .query_row(
            "SELECT id,kind,title,title_explicit,body,created_at FROM artifacts WHERE id = ?1 AND kind = 'note'",
            [artifact_id],
            |r| {
                Ok(serde_json::json!({
                    "id": r.get::<_, String>(0)?,
                    "kind": r.get::<_, String>(1)?,
                    "title": r.get::<_, String>(2)?,
                    "title_explicit": r.get::<_, i64>(3)?,
                    "body": r.get::<_, Option<String>>(4)?,
                    "created_at": r.get::<_, String>(5)?,
                }))
            },
        )
        .optional()
        .map_err(|e| e.to_string())?;
    
    let Some(artifact) = artifact else {
        return Err("note not found".into());
    };
    
    // Determine if title should be updated
    let title_explicit = artifact["title_explicit"].as_i64().unwrap_or(0) == 1;
    let (title, new_title_explicit) = if let Some(t) = new_title {
        if !t.is_empty() {
            (t.to_string(), 1)
        } else {
            (crate::sync::title_hint(new_body), 0)
        }
    } else if title_explicit {
        (artifact["title"].as_str().unwrap_or("").to_string(), 1)
    } else {
        (crate::sync::title_hint(new_body), 0)
    };
    
    // Append version with old body
    let old_body = artifact["body"].as_str().unwrap_or("");
    if !old_body.is_empty() {
        conn.execute(
            "INSERT INTO artifact_versions (id, artifact_id, body, created_at) VALUES (?,?,?,?)",
            rusqlite::params![uuid::Uuid::new_v4().to_string(), artifact_id, old_body, now],
        ).map_err(|e| e.to_string())?;
    }
    
    // Update artifact
    conn.execute(
        "UPDATE artifacts SET body = ?, title = ?, title_explicit = ?, updated_at = ? WHERE id = ?",
        rusqlite::params![new_body, title, new_title_explicit, now, artifact_id],
    ).map_err(|e| e.to_string())?;
    
    get_artifact(conn, artifact_id)
}

/// Add an annotation to an artifact (MOB2.4).
#[allow(dead_code)]
pub fn add_annotation(conn: &Connection, artifact_id: &str, text: &str) -> Result<Value, String> {
    let now = chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.6f+00:00").to_string();
    let ann_id = uuid::Uuid::new_v4().to_string();
    
    conn.execute(
        "INSERT INTO annotations (id, artifact_id, supersedes_id, text, created_at) VALUES (?,?,NULL,?,?)",
        rusqlite::params![ann_id, artifact_id, text, now],
    ).map_err(|e| e.to_string())?;
    
    conn.execute(
        "UPDATE artifacts SET updated_at = ? WHERE id = ?",
        rusqlite::params![now, artifact_id],
    ).map_err(|e| e.to_string())?;
    
    get_artifact(conn, artifact_id)
}

/// Remove an annotation (MOB2.4).
#[allow(dead_code)]
pub fn remove_annotation(conn: &Connection, artifact_id: &str, annotation_id: &str) -> Result<Value, String> {
    let now = chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.6f+00:00").to_string();
    
    conn.execute(
        "DELETE FROM annotations WHERE id = ?1 AND artifact_id = ?2",
        rusqlite::params![annotation_id, artifact_id],
    ).map_err(|e| e.to_string())?;
    
    conn.execute(
        "UPDATE artifacts SET updated_at = ? WHERE id = ?",
        rusqlite::params![now, artifact_id],
    ).map_err(|e| e.to_string())?;
    
    get_artifact(conn, artifact_id)
}

/// Toggle pin status (MOB2.4).
#[allow(dead_code)]
pub fn toggle_pin(conn: &Connection, artifact_id: &str) -> Result<Value, String> {
    let now = chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.6f+00:00").to_string();
    
    let current: i64 = conn
        .query_row("SELECT pinned FROM artifacts WHERE id = ?1", [artifact_id], |r| r.get(0))
        .map_err(|e| e.to_string())?;
    
    let new_pinned = if current == 1 { 0 } else { 1 };
    
    conn.execute(
        "UPDATE artifacts SET pinned = ?, updated_at = ? WHERE id = ?",
        rusqlite::params![new_pinned, now, artifact_id],
    ).map_err(|e| e.to_string())?;
    
    get_artifact(conn, artifact_id)
}

/// Toggle trash status (MOB2.4). Trash/restore, no purge.
#[allow(dead_code)]
pub fn toggle_trash(conn: &Connection, artifact_id: &str) -> Result<Value, String> {
    let now = chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.6f+00:00").to_string();
    
    let current: Option<String> = conn
        .query_row("SELECT deleted_at FROM artifacts WHERE id = ?1", [artifact_id], |r| r.get(0))
        .optional()
        .map_err(|e| e.to_string())?;
    
    let new_deleted_at = current.filter(|s| !s.is_empty());
    let new_deleted_at = if new_deleted_at.is_some() { None } else { Some(now.clone()) };
    
    conn.execute(
        "UPDATE artifacts SET deleted_at = ?, updated_at = ? WHERE id = ?",
        rusqlite::params![new_deleted_at, now, artifact_id],
    ).map_err(|e| e.to_string())?;
    
    get_artifact(conn, artifact_id)
}

/// List trashed artifacts (MOB2.4).
#[allow(dead_code)]
pub fn list_trashed(conn: &Connection) -> Result<Vec<Value>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT id,kind,title,body,source_url,mime,filename,created_at,updated_at,pinned,vaulted_at
             FROM artifacts WHERE deleted_at IS NOT NULL AND purged_at IS NULL
             ORDER BY updated_at DESC",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |r| {
            Ok(serde_json::json!({
                "id": r.get::<_, String>(0)?,
                "kind": r.get::<_, String>(1)?,
                "title": r.get::<_, String>(2)?,
                "body": r.get::<_, Option<String>>(3)?,
                "source_url": r.get::<_, Option<String>>(4)?,
                "mime": r.get::<_, Option<String>>(5)?,
                "filename": r.get::<_, Option<String>>(6)?,
                "created_at": r.get::<_, String>(7)?,
                "updated_at": r.get::<_, String>(8)?,
                "pinned": r.get::<_, i64>(9)?,
                "vaulted_at": r.get::<_, Option<String>>(10)?,
            }))
        })
        .map_err(|e| e.to_string())?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(|e| e.to_string())?);
    }
    Ok(out)
}

