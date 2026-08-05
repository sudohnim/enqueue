# Part 4 — Encrypted, provider-agnostic sync (per-artifact snapshot model)

Phases E1 to E8. Largest, riskiest, last. This file replaces the old event-sourcing
plan (the previous `PRODUCT.md`, now a stub pointing here).

**Read `00-README.md` and `PROGRESS.md` before starting. Do not load other part files.**

---

## 0. What changed from the old plan, and why

The old plan synced an append-only **event log** merged by a **hybrid logical clock**
with a **deterministic-replay** invariant, plus **compaction**. That is the correct
design for conflict-free multi-writer merge, and it is also the single most dangerous
code in the project: mistakes there are silent and destroy data.

This plan is for a different, smaller problem: **one person, a small number of devices,
who rarely edits the same artifact on two offline devices at once.** For that problem a
much simpler model is correct:

- The sync unit is **one canonical snapshot per artifact** (and per exhibit), encrypted.
- Conflicts resolve by **last-writer-wins per artifact**, using a deterministic rule.
- There is **no event log, no logical clock, no replay, no compaction.**
- The app encrypts every unit itself, so the **storage provider is a dumb byte
  replicator**: any synced folder works (iCloud Drive, Dropbox, Google Drive, Proton
  Drive, Syncthing). Proton Drive is a *recommended default*, not a requirement.

### Decisions this plan bakes in (ratify before starting)

- **DEC-A (LWW data loss, accepted).** If the same artifact is edited on two devices
  while both are offline, the edit with the newer `updated_at` wins the whole artifact
  and the other edit is lost (the losing snapshot is retained locally as a version row,
  never silently discarded from disk, but it is not merged). This is `[HUMAN]`-accepted.
- **DEC-B (provider-agnostic).** Encryption is unconditional and does not depend on the
  provider. The security guarantee must never rest on the provider being end-to-end
  encrypted.
- **DEC-C (crypto is now load-bearing).** With no second layer from a specific provider,
  correctness rests entirely on `crypto.py` (Phase E1) and recovery (Phase E2). Those
  two phases get the strongest review. Full-disk encryption (FileVault) is assumed on
  every device for local-at-rest, because the working DB is plaintext today.
- **DEC-D5 (Argon2id preset).** libsodium `crypto_pwhash` `MODERATE`. Recorded once here;
  do not choose other numbers.

### The one invariant everything depends on

**Convergence:** given the same set of snapshot files on disk, every device computes the
same winning snapshot for every id and therefore reaches byte-identical local state.
This replaces the old "any event shuffle yields identical state" invariant. It is proved
by property tests in Phase E3. A weak test here is worse than none.

---

## 1. Glossary and fixed constants

A dumb agent must use these exact names. Do not invent alternatives.

| Name | Exact value / meaning |
|---|---|
| `SYNC_DIR` | config value, a filesystem path the user picks. Default unset (sync off). |
| device folder | `SYNC_DIR/enqueue/dev/<device_id>/` — a device writes **only** here. |
| blob folder | `SYNC_DIR/enqueue/blobs/` — shared, content-addressed, write-by-rename only. |
| snapshot file | `SYNC_DIR/enqueue/dev/<device_id>/artifacts/<artifact_id>.enc` |
| exhibit file | `SYNC_DIR/enqueue/dev/<device_id>/exhibits/<exhibit_id>.enc` |
| `device_id` | UUID4 string, generated once, stored at `DATA_DIR/device_id`, never from hardware. |
| `keyring.json` | `DATA_DIR/keyring.json` — the **wrapped** keys only. Never the plaintext DEK. Never synced. |
| DEK | data-encryption-key, 32 random bytes. In memory only after unlock. |
| KEK | key-encryption-key, derived from the password via Argon2id. Never stored. |
| snapshot | canonical JSON dict for one artifact: its row plus its child rows (below). |
| LWW key | the tuple `(updated_at, device_id)`, compared lexicographically. Higher wins. |

Snapshot child rows for an artifact are, in this exact order of keys:
`artifact` (the `artifacts` row as a dict), `annotations` (list, ordered by
`created_at, id`), `page_text` (list, ordered by `page`), `versions`
(`artifact_versions` list, ordered by `created_at, id`). Exhibits are a separate
snapshot type carrying the `exhibits` row plus its `exhibit_members` list ordered by
`rank`.

Canonical JSON is exactly:
`json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`
encoded UTF-8. No other serialization is permitted for a snapshot.

---

## 2. How to work these steps

Same protocol as `00-README.md`: one checkbox per commit, `[AGENT]` mechanical,
`[HUMAN]` stop and hand over, every step idempotent, app must start and tests must pass
after each. Where a step says **STOP**, stop.

Property tests use `hypothesis`, at least 100 examples, a fixed recorded seed.

---

## PHASE E1 — Crypto building blocks, in isolation

No sync, no files-on-disk sync, no clock. Built and tested alone. This phase is
load-bearing (DEC-C).

- [ ] `[AGENT]` Add `PyNaCl` to `pyproject.toml` dependencies. Do not add any other crypto library. Do not implement any primitive by hand.
- [ ] `[AGENT]` Add `src/enqueue/crypto.py`.
- [ ] `[AGENT]` Implement `derive_kek(password: str, salt: bytes) -> bytes` using libsodium `crypto_pwhash` with the `MODERATE` preset (DEC-D5): `nacl.pwhash.argon2id.kdf`, `opslimit=OPSLIMIT_MODERATE`, `memlimit=MEMLIMIT_MODERATE`, output length 32. Put the exact preset in a comment and in `docs/decisions/encryption-model.md`.
- [ ] `[AGENT]` Implement `new_dek() -> bytes` returning 32 bytes from `nacl.utils.random`.
- [ ] `[AGENT]` Implement `wrap(dek: bytes, kek: bytes) -> bytes` and `unwrap(wrapped: bytes, kek: bytes) -> bytes` using `nacl.secret.SecretBox` (XChaCha20-Poly1305), fresh random nonce prepended to the ciphertext.
- [ ] `[AGENT]` Implement `encrypt(plaintext: bytes, dek: bytes) -> bytes` and `decrypt(ciphertext: bytes, dek: bytes) -> bytes` using `nacl.secret.SecretBox`, a fresh random nonce per call, nonce prepended.
- [ ] `[AGENT]` Implement `blob_name(content_hash: str, dek: bytes) -> str`: a hex HMAC-SHA256 of `content_hash` keyed by the DEK, using `hmac` + `hashlib`. Comment: a plain content hash would let anyone with folder access test whether a known file is in the library.
- [ ] `[AGENT]` Test: `decrypt(encrypt(x, dek), dek) == x` for fixed bytes.
- [ ] `[AGENT]` Test: decrypting with a wrong key raises `nacl.exceptions.CryptoError` and returns no partial data.
- [ ] `[AGENT]` Test: flipping any single byte of a ciphertext makes `decrypt` raise.
- [ ] `[AGENT]` Test: `encrypt(x, dek) != encrypt(x, dek)` (nonce makes them differ).
- [ ] `[AGENT]` Test: `unwrap(wrap(dek, kek), kek) == dek`, and unwrap with a wrong kek raises.
- [ ] `[AGENT]` Property test (100+ examples, fixed seed): round-trip `decrypt(encrypt(x)) == x` over random byte strings of length 0 to 4096.
- [ ] `[HUMAN]` **STOP.** A human reviews `crypto.py` before it is used anywhere. Confirm PyNaCl is the only library, the `MODERATE` preset is used, nonces are per-call random, and nothing was hand-rolled.

---

## PHASE E2 — Keyring, password, and recovery code

Forgetting the password must not destroy the library. The DEK is wrapped twice.

- [ ] `[AGENT]` Add `src/enqueue/keyring_file.py` (do not touch the existing `keyring.py`, which is the macOS API-key store).
- [ ] `[AGENT]` `initialize(password: str) -> str`: generate a DEK, a random 16-byte password salt, derive the KEK, wrap the DEK by the KEK; generate a high-entropy recovery phrase (use `nacl.utils.random(32)` rendered as a BIP39-style or base32 word list; if no wordlist dependency is wanted, use Crockford base32 of 20 bytes), derive a recovery-KEK from it with the same Argon2id `MODERATE`, wrap the DEK a second time by the recovery-KEK. Write `keyring.json` with fields `version=1`, `password_salt`, `recovery_salt`, `dek_by_password`, `dek_by_recovery`. Return the recovery phrase. Never write the phrase or the plaintext DEK to disk.
- [ ] `[AGENT]` `unlock(password: str) -> bytes`: read `keyring.json`, derive KEK from password + stored salt, unwrap `dek_by_password`. Raise a clear `UnlockError` on failure; never return partial bytes.
- [ ] `[AGENT]` `unlock_with_recovery(phrase: str) -> bytes`: unwrap `dek_by_recovery`.
- [ ] `[AGENT]` `regenerate_recovery(dek: bytes) -> str`: make a new recovery phrase and rewrap, invalidating the old one. Requires the DEK (caller must have unlocked first).
- [ ] `[AGENT]` `is_initialized() -> bool`: `keyring.json` exists.
- [ ] `[AGENT]` Test: `unlock` returns the same DEK that `initialize` produced.
- [ ] `[AGENT]` Test: `unlock` with the wrong password raises `UnlockError` and returns nothing.
- [ ] `[AGENT]` Test: `unlock_with_recovery` works when the password is unknown.
- [ ] `[AGENT]` Test: after `regenerate_recovery`, the old phrase no longer unlocks and the new one does.
- [ ] `[AGENT]` Test: the recovery phrase string never appears in `keyring.json` bytes.
- [ ] `[AGENT]` Add a Settings section `Security` with actions: `Reveal recovery code` (re-enter password first), `Regenerate recovery code`. Show the warning verbatim: `Do not store this in the same cloud account that holds your sync folder. If you lose both, your library cannot be recovered.`
- [ ] `[AGENT]` Test: the recovery phrase never appears in any log file the engine writes.
- [ ] `[HUMAN]` **STOP.** A human verifies recovery end to end by actually forgetting the password and recovering. Cannot be simulated.

---

## PHASE E3 — Snapshot serialization and LWW merge, local only, no network

This phase replaces the old event log. No files are written to `SYNC_DIR` yet. All work
is in memory and against the local DB, so the merge rule can be proven before any I/O.

- [ ] `[AGENT]` Add `src/enqueue/sync/snapshot.py`.
- [ ] `[AGENT]` `read_artifact_snapshot(conn, artifact_id) -> dict`: build the snapshot dict per Section 1 (artifact row + annotations + page_text + versions), each child list ordered exactly as specified. Return `None` if the artifact does not exist.
- [ ] `[AGENT]` `serialize(snapshot: dict) -> bytes`: the canonical JSON from Section 1. Test: `serialize(x) == serialize(x)` and re-parsing then re-serializing is byte-identical.
- [ ] `[AGENT]` `deserialize(raw: bytes) -> dict`: `json.loads`. Test: `deserialize(serialize(x)) == x` over property-generated snapshots (100+ examples, fixed seed).
- [ ] `[AGENT]` `lww_key(snapshot: dict) -> tuple[str, str]`: return `(snapshot["artifact"]["updated_at"], snapshot["artifact"].get("_device_id", ""))`. Higher tuple wins. The `_device_id` field is written into the snapshot at export time (Phase E4); locally it is this device's id.
- [ ] `[AGENT]` `winner(snapshots: list[dict]) -> dict`: return the snapshot with the maximum `lww_key`. Deterministic and total (device_id breaks equal timestamps). Test: order of the input list never changes the result.
- [ ] `[AGENT]` `apply_snapshot(conn, snapshot: dict) -> None`: upsert the artifact row and **replace** its annotations, page_text, and versions with the snapshot's, inside one transaction. Idempotent: applying the same snapshot twice leaves the DB byte-identical. Keyed on `artifact_id`.
- [ ] `[AGENT]` `apply_snapshot` must be a no-op when the local artifact's `lww_key` is already `>=` the incoming one, so a stale pull never overwrites a newer local edit.
- [ ] `[AGENT]` Mirror all of the above for exhibits: `read_exhibit_snapshot`, and reuse `serialize`/`deserialize`/`winner`, plus `apply_exhibit_snapshot`.
- [ ] `[AGENT]` Property test (100+ examples, fixed seed): given a set of snapshots for the same id with distinct `lww_key`s, applying them in **any order** yields the same final DB rows as applying only the `winner`. This is the convergence invariant. Do not weaken it.
- [ ] `[AGENT]` Property test: applying any snapshot twice equals applying it once (idempotence).
- [ ] `[AGENT]` Test: `apply_snapshot` with an older `lww_key` than the local row does nothing.
- [ ] `[HUMAN]` **STOP** if the convergence property test fails. Do not weaken it to pass. Review the tests themselves: confirm hypothesis, 100+ examples, and genuine permutation.

---

## PHASE E4 — Folder transport: write own folder, pull others

Now snapshots reach disk. A device writes only its own folder; it reads all folders.

- [ ] `[AGENT]` Add config `SYNC_DIR = os.getenv("ENQ_SYNC_DIR", "")` and `SYNC_ENABLED = bool(SYNC_DIR)`. Empty means sync is off and no sync code runs.
- [ ] `[AGENT]` Add `src/enqueue/sync/transport.py`.
- [ ] `[AGENT]` `_device_id() -> str`: read `DATA_DIR/device_id`; if absent, generate a UUID4, write it, return it. Idempotent.
- [ ] `[AGENT]` `write_object(path: Path, data: bytes) -> None`: write to `path + ".tmp-<random>"`, `fsync`, then `os.replace` into place (atomic). Never write the final name directly.
- [ ] `[AGENT]` `push_artifact(conn, dek, artifact_id) -> None`: read the snapshot, stamp `snapshot["artifact"]["_device_id"] = _device_id()`, `serialize`, `encrypt` with the DEK, `write_object` to this device's `artifacts/<artifact_id>.enc`. Skip entirely if the artifact is `local_only`.
- [ ] `[AGENT]` Test proving a `local_only` artifact writes zero files under `SYNC_DIR`.
- [ ] `[AGENT]` `read_object(path, dek) -> dict | None`: read bytes, `decrypt`, `deserialize`. On any decrypt failure treat the file as **not yet arrived** (return `None`), never as corruption. A half-written file from another client is normal.
- [ ] `[AGENT]` `pull() -> dict`: enumerate every `dev/*/artifacts/*.enc` and `dev/*/exhibits/*.enc` under `SYNC_DIR/enqueue` **except this device's own folder**. Group by id. For each id, `read_object` each candidate, drop `None`s, pick `winner`, `apply_snapshot` (which no-ops if local is newer). Never assume filesystem ordering. Return a summary `{applied, skipped, unreadable}`.
- [ ] `[AGENT]` Store a per-object watermark in a local `sync_applied` table `(device_id, obj_id, lww_updated_at, lww_device)` so `pull` skips objects already applied. Rescanning all files is acceptable for a personal library; the watermark only skips re-decrypt+apply.
- [ ] `[AGENT]` Make `pull` safe to interrupt and rerun: it is a pure function of the files on disk plus the watermark, and applying is idempotent.
- [ ] `[AGENT]` Handle placeholder / online-only files (iCloud, OneDrive, Google Drive streaming): if a file's size is 0 or a decrypt yields `None` on a file the OS marks as a placeholder, treat as not-yet-arrived and skip; do not delete it.
- [ ] `[AGENT]` Wire `push_artifact` into every mutation path that today writes an artifact (capture, note edit, annotation, flag, trash — find them via the existing mutation functions in `capture.py`, `notes.py`, `chats.py`, `trash.py`). Push after the local transaction commits, never inside it. Guard every call with `if config.SYNC_ENABLED`.
- [ ] `[AGENT]` Add a Settings control to choose `SYNC_DIR`, with help text: `Any folder your cloud client keeps in sync works. Your data is encrypted before it is written, so the provider cannot read it.`
- [ ] `[AGENT]` Add a background pull loop: on a timer (reuse the ingest worker thread pattern), call `pull()` when `SYNC_ENABLED`. Never block a request on it.
- [ ] `[AGENT]` Add sync fields to `enq doctor`: this `device_id`, per-device object counts, unapplied count, last successful pull time.
- [ ] `[AGENT]` Test harness: three temp directories acting as three devices sharing one `SYNC_DIR`. Assert final DB state is identical on all three after each pushes some artifacts and all pull.
- [ ] `[AGENT]` Test: objects delivered out of order still converge.
- [ ] `[AGENT]` Test: the same object delivered twice changes nothing the second time.
- [ ] `[AGENT]` Test: device A and device B both edit the same artifact offline; after both pull, both hold the snapshot with the higher `lww_key`, and the loser's snapshot is retained locally as an `artifact_versions` row (DEC-A), not discarded.
- [ ] `[AGENT]` Test: a device offline for many pushes catches up in a single `pull`.
- [ ] `[HUMAN]` **STOP.** A human tests with two real machines and a real synced folder (recommend Proton Drive or iCloud Drive) before this is considered working. The simulated harness does not catch real sync-client behavior.

---

## PHASE E5 — Original files (blobs)

Content-addressed, encrypted, shared folder, natural dedup, no conflicts.

- [ ] `[AGENT]` `push_blob(dek, content_hash) -> None`: read `config.BLOB_DIR/<content_hash>`, encrypt, `write_object` to `SYNC_DIR/enqueue/blobs/<blob_name(content_hash, dek)>`. Skip if already present (content-addressed name means identical bytes map to identical name; dedup is free). Skip local-only artifacts.
- [ ] `[AGENT]` `fetch_blob(dek, content_hash) -> bool`: if the local blob is missing, read the encrypted object by `blob_name`, decrypt, write to `config.BLOB_DIR`. Return whether it now exists.
- [ ] `[AGENT]` Add a local cache size limit for downloaded originals (`ENQ_BLOB_CACHE_MB`, default 2048); evict least-recently-used originals for synced artifacts only, never local-only bytes.
- [ ] `[AGENT]` Ensure search never requires a blob download. Test: make the blob folder unreadable and confirm search still returns correct results (search uses `page_text`/`chunks`, already local).
- [ ] `[AGENT]` Keep preview thumbnails local and small so browsing never waits on the network.
- [ ] `[AGENT]` Add a `Pin for offline` action forcing `fetch_blob` for a chosen artifact.
- [ ] `[AGENT]` Test: `blob_name` for the same `content_hash` and DEK is stable, and differs under a different DEK.

---

## PHASE E6 — Optional readable mirror (reuse `export.py`)

The human escape hatch. Separate from the encrypted sync, and off by default.

- [ ] `[AGENT]` Add config `EXPORT_MIRROR_ENABLED = os.getenv("ENQ_EXPORT_MIRROR", "") == "1"`, default off.
- [ ] `[AGENT]` When enabled, run the existing `export.export(SYNC_DIR + "/enqueue/export")` on the same background timer as pull. Reuse `export.py` verbatim; do not reimplement it.
- [ ] `[AGENT]` Add a Settings toggle. When the user enables it, show: `This saves a readable, UNENCRYPTED copy of your library into your sync folder. If your cloud provider is not end-to-end encrypted, they will be able to read it.`
- [ ] `[AGENT]` Document in `AGENTS.md`: the encrypted snapshots are the source of truth and work with any provider; this readable copy is for human access and its privacy depends on the provider.

---

## PHASE E7 — Trash and purge via tombstones

Delete must mean delete on every device. No append-only log, so a purge is a snapshot
that says "gone", resolved by the same LWW rule.

- [ ] `[AGENT]` When an artifact is trashed, its snapshot already carries `deleted_at`; a normal `push_artifact` propagates it. A device applying a snapshot with `deleted_at` set marks the local artifact deleted and removes it from search, the wall, and both lens sections. No new mechanism.
- [ ] `[AGENT]` Restoring clears `deleted_at`, bumps `updated_at`, and pushes; other devices apply it by LWW.
- [ ] `[AGENT]` On `Empty trash`, for each purged artifact: delete this device's `artifacts/<id>.enc`, delete the blob object if no non-deleted artifact shares its `content_hash`, and write a **tombstone** snapshot `{"artifact": {"id": <id>, "updated_at": <now>, "_device_id": <me>, "purged": true}}` to this device's folder.
- [ ] `[AGENT]` `apply_snapshot` must treat a `purged` snapshot as: delete the local artifact rows, its index entries, its cached original, and any `lens_judgments` rows for it, then keep a minimal purge tombstone in `sync_applied` so a later re-scan does not resurrect it.
- [ ] `[AGENT]` Comment: deleting a device's own snapshot files on purge is the one deliberate, user-initiated removal; every other write is add-or-replace.
- [ ] `[AGENT]` Test: device A empties the trash, device B pulls, and B no longer holds the content in DB, index, cache, or judgment cache.
- [ ] `[AGENT]` Test: after a purge, a fresh device that pulls the full folder set never reconstructs the purged artifact (the tombstone wins by LWW over any older snapshot of it).
- [ ] `[AGENT]` Implement auto-empty per the existing `trash_days` setting (already built). Do not change its default.
- [ ] `[AGENT]` Show on the trash screen: `Items here are still stored. Empty the trash to remove them permanently.` Before emptying: `This permanently removes these items from all your devices. This cannot be undone.`

---

## PHASE E8 — Mobile consistency (keyword-only), per D9

There is no compaction phase; snapshots are self-compacting (a new device reads current
state, never history).

- [ ] `[AGENT]` Resolve the contradiction in `AGENTS.md` between "a phone reads an index built by a Mac" and "embeddings never leave a device": the phone builds its own keyword index from the snapshots it pulls and has no vector index. Write this into `AGENTS.md` before code.
- [ ] `[AGENT]` Ensure a device with empty vector tables returns keyword (FTS5) results rather than an error. Test: search works with the vector tables empty.
- [ ] `[AGENT]` Per D9, the phone gets no lens/topic view (search only). Do not ship a weaker inconsistent version.
- [ ] `[AGENT]` The phone's transport is **not** assumed to be a synced folder. Proton Drive, iCloud, and Google Drive expose mobile file access as an app/API, not a folder a client replicates. Treat the mobile transport as a separate `[HUMAN]` design step: which provider API, and how `pull`/`push_blob` map onto it. STOP and hand over before implementing mobile transport.

---

## Part 4 done

- [ ] `[AGENT]` Update `PROGRESS.md`: Part 4 (E2E sync) complete.
- [ ] `[HUMAN]` Final review: export still works, recovery still works, and two real devices sharing a real synced folder converge to identical state after edits, an offline gap, a same-artifact conflict, and an Empty-trash purge.

---

## What was cut from the old plan, and why (for the record)

- **Event log + `apply(event)` per type (old Phase 25):** replaced by per-artifact
  snapshots. No event types, no per-mutation event emission.
- **Hybrid logical clock + `hlc.py` (old Phase 23):** replaced by the `(updated_at,
  device_id)` LWW key. No clock service.
- **Log compaction + snapshots-of-history (old Phase 30):** unnecessary; a snapshot per
  artifact is already the compact current state.
- **WebDAV / S3 / GCS:** never add. The transport is a plain directory.

The cut phases were the riskiest, most data-destroying parts. Everything kept — crypto,
recovery, blobs, the readable mirror, mobile keyword-only — is either well-trodden or
independent of the sync engine.
