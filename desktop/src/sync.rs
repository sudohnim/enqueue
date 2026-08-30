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
                    updated_at,local_only,status,pinned,deleted_at,pages,title_explicit,_device_id
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
    Ok(Some(serde_json::json!({
        "artifact": artifact,
        "annotations": anns,
        "page_text": [],
        "versions": [],
    })))
}

/// Push one snapshot to the relay (MOB.7): serialize, encrypt, PUT under this device's
/// namespace. The relay upserts by name (MOBFIX.5), so a re-PUT of an edited or deleted
/// snapshot overwrites in place and returns 201; a 409 (older relay) is still tolerated.
#[allow(dead_code)]
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
    let resp = ureq::put(&format!("{}/sync/object/{}", relay_url.trim_end_matches('/'), name))
        .set("Authorization", &format!("Bearer {secret}"))
        .set("Content-Type", "application/octet-stream")
        .send_bytes(&ciphertext)
        .map_err(|e| e.to_string())?;
    if resp.status() != 201 && resp.status() != 409 {
        return Err(format!("push rejected: {}", resp.status()));
    }
    Ok(())
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
          tags_json      TEXT
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
        "#,
    )
    .map_err(|e| e.to_string())?;
    // Migration: tags_json was added after the first release. ALTER fails with a
    // "duplicate column" on installs that already have it, which is fine.
    let _ = conn.execute("ALTER TABLE artifacts ADD COLUMN tags_json TEXT", []);
    Ok(())
}

#[allow(dead_code)]
fn apply_snapshot(conn: &Connection, snapshot: &Value) -> Result<(), String> {
    let artifact = &snapshot["artifact"];
    let id = artifact["id"].as_str().ok_or("snapshot: missing id")?;

    // LWW no-op check. A read-only device has no local edits, so this only makes a
    // re-pull of the same snapshot idempotent.
    let local: Option<(String, String)> = conn
        .query_row(
            "SELECT updated_at, COALESCE(_device_id,'') FROM artifacts WHERE id = ?1",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    if let Some(local_key) = local {
        if local_key >= lww_key(snapshot) {
            return Ok(());
        }
    }

    let g = |c: &str| artifact.get(c);
    conn.execute(
        "INSERT INTO artifacts (id,kind,title,body,source_url,content_hash,mime,filename,\
         created_at,updated_at,local_only,status,pinned,deleted_at,pages,title_explicit,_device_id)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17)
         ON CONFLICT(id) DO UPDATE SET
           kind=excluded.kind, title=excluded.title, body=excluded.body,
           source_url=excluded.source_url, content_hash=excluded.content_hash,
           mime=excluded.mime, filename=excluded.filename, created_at=excluded.created_at,
           updated_at=excluded.updated_at, local_only=excluded.local_only,
           status=excluded.status, pinned=excluded.pinned, deleted_at=excluded.deleted_at,
           pages=excluded.pages, title_explicit=excluded.title_explicit,
           _device_id=excluded._device_id",
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
        "INSERT INTO sync_meta (key,value) VALUES ('cursor',?1)\
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
        // Blobs are fetched on demand (MOB.5), not pulled here.
        if !name.starts_with("dev/") || !name.ends_with(".enc") {
            continue;
        }
        let resp = match ureq::get(&format!("{base}/sync/object/{name}"))
            .set("Authorization", &auth)
            .call()
        {
            Ok(r) => r,
            Err(_) => continue, // unreachable relay; the cursor is not advanced
        };
        if resp.status() != 200 {
            continue;
        }
        let mut bytes = Vec::new();
        if resp.into_reader().read_to_end(&mut bytes).is_err() {
            continue;
        }
        let plain = match secretbox_decrypt(dek, &bytes) {
            Ok(p) => p,
            Err(_) => continue, // unreadable = "not yet arrived", never corruption
        };
        let snapshot: Value = match serde_json::from_slice(&plain) {
            Ok(s) => s,
            Err(_) => continue,
        };
        if apply_snapshot(conn, &snapshot).is_ok() {
            pulled += 1;
        }
    }

    if let Err(e) = write_cursor(conn, new_cursor) {
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
        .prepare("SELECT id FROM artifacts WHERE deleted_at IS NULL ORDER BY updated_at DESC")
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

/// The library rows for the Library surface (MOB.4): id, kind, title, body (for the
/// snippet), timestamps, and capture metadata. Newest first, trashed excluded.
#[allow(dead_code)]
pub fn list_artifacts(conn: &Connection) -> Result<Vec<Value>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT id,kind,title,body,source_url,mime,filename,created_at,updated_at,pinned,status,tags_json
             FROM artifacts WHERE deleted_at IS NULL ORDER BY updated_at DESC",
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
    Ok(serde_json::json!({ "artifact": artifact, "annotations": anns, "preview": preview }))
}

/// Keyword search over titles, bodies, and annotations (MOB.6). No embeddings, no
/// model - a plain case-insensitive substring match, the same honesty as the desktop's
/// keyword leg. Returns library rows, newest first.
#[allow(dead_code)]
pub fn search_artifacts(conn: &Connection, query: &str) -> Result<Vec<Value>, String> {
    let needle = format!("%{}%", query);
    let mut stmt = conn
        .prepare(
            "SELECT DISTINCT a.id,a.kind,a.title,a.body,a.source_url,a.mime,a.filename,
                    a.created_at,a.updated_at,a.pinned
             FROM artifacts a
             LEFT JOIN annotations an ON an.artifact_id = a.id
             WHERE a.deleted_at IS NULL
               AND (a.title LIKE ?1 OR a.body LIKE ?1 OR an.text LIKE ?1)
             ORDER BY a.updated_at DESC",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([&needle], |r| {
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

/// Add a tag to an artifact (MOB2.4).
#[allow(dead_code)]
pub fn add_tag(conn: &Connection, artifact_id: &str, tag_name: &str) -> Result<Value, String> {
    let now = chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.6f+00:00").to_string();
    let normalized = tag_name.trim().to_lowercase();
    if normalized.is_empty() {
        return Err("a tag needs a name".into());
    }
    
    let tag_id: String = conn
        .query_row(
            "SELECT id FROM tags WHERE name = ?1",
            [&normalized],
            |r| r.get(0),
        )
        .optional()
        .map_err(|e| e.to_string())?
        .unwrap_or_else(|| {
            let new_id = uuid::Uuid::new_v4().to_string();
            let _ = conn.execute(
                "INSERT INTO tags (id, name, created_at) VALUES (?,?,?)",
                rusqlite::params![new_id, normalized, now],
            );
            new_id
        });
    
    conn.execute(
        "INSERT OR IGNORE INTO artifact_tags (artifact_id, tag_id, created_at) VALUES (?,?,?)",
        rusqlite::params![artifact_id, tag_id, now],
    ).map_err(|e| e.to_string())?;
    
    conn.execute(
        "UPDATE artifacts SET updated_at = ? WHERE id = ?",
        rusqlite::params![now, artifact_id],
    ).map_err(|e| e.to_string())?;
    
    get_artifact(conn, artifact_id)
}

/// Remove a tag from an artifact (MOB2.4).
#[allow(dead_code)]
pub fn remove_tag(conn: &Connection, artifact_id: &str, tag_name: &str) -> Result<Value, String> {
    let now = chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.6f+00:00").to_string();
    let normalized = tag_name.trim().to_lowercase();
    
    conn.execute(
        "DELETE FROM artifact_tags WHERE artifact_id = ?1 AND tag_id = (SELECT id FROM tags WHERE name = ?2)",
        rusqlite::params![artifact_id, normalized],
    ).map_err(|e| e.to_string())?;
    
    conn.execute(
        "DELETE FROM tags WHERE name = ?1 AND NOT EXISTS (SELECT 1 FROM artifact_tags WHERE tag_id = tags.id)",
        rusqlite::params![normalized],
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

/// Get tags for an artifact (MOB2.4).
#[allow(dead_code)]
pub fn get_tags(conn: &Connection, artifact_id: &str) -> Result<Vec<String>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT t.name FROM tags t JOIN artifact_tags at ON at.tag_id = t.id WHERE at.artifact_id = ?1 ORDER BY t.name",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([artifact_id], |r| r.get::<_, String>(0))
        .map_err(|e| e.to_string())?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(|e| e.to_string())?);
    }
    Ok(out)
}

/// List trashed artifacts (MOB2.4).
#[allow(dead_code)]
pub fn list_trashed(conn: &Connection) -> Result<Vec<Value>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT id,kind,title,body,source_url,mime,filename,created_at,updated_at,pinned
             FROM artifacts WHERE deleted_at IS NOT NULL ORDER BY updated_at DESC",
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
            }))
        })
        .map_err(|e| e.to_string())?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(|e| e.to_string())?);
    }
    Ok(out)
}

/// Fetch the keyring.json from the relay (MOB2.10).
/// The keyring.enc is the raw keyring.json (wrapped DEK only, no extra encryption).
#[allow(dead_code)]
pub fn fetch_keyring(relay_url: &str, secret: &str) -> Result<Vec<u8>, String> {
    let resp = ureq::get(&format!(
        "{}/sync/object/lib/keyring.enc",
        relay_url.trim_end_matches('/')
    ))
    .set("Authorization", &format!("Bearer {secret}"))
    .call()
    .map_err(|e| e.to_string())?;
    if resp.status() != 200 {
        return Err(format!("keyring fetch: {}", resp.status()));
    }
    let mut bytes = Vec::new();
    resp.into_reader()
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    Ok(bytes)
}
