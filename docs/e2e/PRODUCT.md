# Part 4 — Local-First Encrypted Sync

Phases 23 to 31. Largest, riskiest, last.

**Read `00-README.md` and `PROGRESS.md` before starting. Do not load other part files.**

## Before you begin

- [ ] `[HUMAN]` Confirm Part 1 Phase 4 export works and is tested. Sync creates an
      unrecoverable-loss path; export is the escape hatch. **Do not proceed otherwise.**
- [ ] `[HUMAN]` Confirm decision **D5** (Argon2id parameters), **D6** (bundle window),
      **D7** (offline window for pruning), and **D8** (trash auto-empty) are answered.
- [ ] `[HUMAN]` Confirm decision **D10**: which model runs this part, and that a human
      reviews every phase before the next begins.

## Why this part is different

Everything in Parts 1 to 3 is reversible. Nothing here is. A mistake in the encryption
envelope, the clock, or the replay logic is **silent** — the tests pass, the app works,
and the data is quietly wrong or quietly lost. Multi-turn reliability degrades over long
sequences, and this is the longest sequence in the plan.

Treat every phase as needing review. Do not batch. Do not improvise around a failure.

---

## PHASE 23 — Encryption and clock building blocks, in isolation

No sync in this phase. These components are built and tested alone.

- [ ] `[AGENT]` Add `src/enqueue/crypto.py`.
- [ ] `[AGENT]` Derive a key-encryption-key from the user's password using Argon2id with **exactly the parameters recorded in decision D5**. Do not choose parameters. If D5 is blank, stop.
- [ ] `[AGENT]` Record the D5 parameters in a comment and in `docs/decisions/encryption-model.md`.
- [ ] `[AGENT]` Generate a random data-encryption-key once, stored wrapped by the key-encryption-key.
- [ ] `[AGENT]` Encrypt individual objects with XChaCha20-Poly1305 using a vetted library such as PyNaCl. Do not implement any cryptographic primitive by hand.
- [ ] `[AGENT]` Generate a fresh random nonce per object. Never reuse one.
- [ ] `[AGENT]` Write a test: encrypt then decrypt returns the original bytes.
- [ ] `[AGENT]` Write a test: decrypting with a wrong password fails with a clear error and never returns partial data.
- [ ] `[AGENT]` Write a test: flipping any single byte of ciphertext causes decryption to fail.
- [ ] `[AGENT]` Write a test: encrypting the same plaintext twice produces different ciphertext.
- [ ] `[AGENT]` Write a property test over at least 100 random plaintexts that round-trip is lossless.
- [ ] `[HUMAN]` **STOP.** A human reviews `crypto.py` before it is used anywhere. Confirm the library, the parameters, and that nothing was hand-rolled.
- [ ] `[AGENT]` Add `src/enqueue/hlc.py` implementing a hybrid logical clock with a device-id tiebreak.
- [ ] `[AGENT]` Never use wall-clock time for ordering.
- [ ] `[AGENT]` Write a test: the clock never goes backwards across restarts.
- [ ] `[AGENT]` Write a property test over at least 100 generated interleavings: two devices with skewed clocks still produce a stable total order.
- [ ] `[AGENT]` Add a `device_id` generated once per installation, stored locally, never derived from hardware.

---

## PHASE 24 — Recovery code, in Settings

Without this, forgetting a password destroys a lifetime of notes with no appeal.

- [ ] `[AGENT]` Generate a high-entropy recovery phrase at first setup.
- [ ] `[AGENT]` Store the data-encryption-key wrapped a second time by a key derived from the recovery phrase.
- [ ] `[AGENT]` Show the recovery phrase once during setup, with a checkbox the user must tick to confirm they saved it.
- [ ] `[AGENT]` Add a Settings section named Security.
- [ ] `[AGENT]` Add a Reveal Recovery Code action requiring the password to be re-entered first.
- [ ] `[AGENT]` Add a Regenerate Recovery Code action invalidating the previous one.
- [ ] `[AGENT]` Show a persistent reminder until the user confirms they saved the code.
- [ ] `[AGENT]` Display this warning next to the code: `Do not store this in the same cloud account that holds your sync folder. If you lose both, your library cannot be recovered.`
- [ ] `[AGENT]` Never write the recovery phrase into the sync folder, logs, or crash reports.
- [ ] `[AGENT]` Write a test: unlocking with the recovery phrase works when the password is unknown.
- [ ] `[AGENT]` Write a test: the recovery phrase does not appear anywhere in the sync directory after a full sync.
- [ ] `[AGENT]` Write a test: the recovery phrase does not appear in any log file or crash report.
- [ ] `[HUMAN]` **STOP.** A human verifies the recovery flow end to end by actually forgetting the password and recovering. This cannot be simulated.

---

## PHASE 25 — Event log with local replay only, no network

- [ ] `[AGENT]` Define the event envelope in one place: `event_id`, `hlc`, `device_id`, `type`, `schema_version`, `payload`.
- [ ] `[AGENT]` Set `schema_version` to 1 from the first event. Document that all future changes must be additive, because old peers must read new events forever.
- [ ] `[AGENT]` Add typed constructors and validation for `artifact.created`.
- [ ] `[AGENT]` Add `block.added`.
- [ ] `[AGENT]` Add `note.revised`.
- [ ] `[AGENT]` Add `annotation.appended`.
- [ ] `[AGENT]` Add `facet.generated`.
- [ ] `[AGENT]` Add `exhibit.saved`.
- [ ] `[AGENT]` Add `member.placard_edited`.
- [ ] `[AGENT]` Add `member.ejected`.
- [ ] `[AGENT]` Add `artifact.flagged`.
- [ ] `[AGENT]` Add `artifact.trashed`.
- [ ] `[AGENT]` Add `artifact.purged`.
- [ ] `[AGENT]` Emit events on every mutation, appending to a local directory. No upload yet.
- [ ] `[AGENT]` Ensure artifacts flagged local-only emit no events at all.
- [ ] `[AGENT]` Write a test proving a local-only artifact produces zero event files.
- [ ] `[AGENT]` Implement `apply(event)` for each type above, one commit per type.
- [ ] `[AGENT]` Make every `apply` idempotent, keyed on `event_id`.
- [ ] `[AGENT]` Add command `enq rebuild` wiping SQLite and all index tables, then replaying the local log in clock order.
- [ ] `[AGENT]` Write a property test with `hypothesis`, at least 100 examples, fixed seed: **any shuffle of the same event set produces byte-identical final database state.**
- [ ] `[AGENT]` Write a property test, at least 100 examples: applying every event twice produces the same state as applying it once.
- [ ] `[AGENT]` Verify `enq eval` and `enq lens-eval` scores are unchanged after a full `enq rebuild`.
- [ ] `[HUMAN]` **STOP** if the shuffle test fails, and do not weaken the test to make it pass. Deterministic replay is the invariant every other feature in this part depends on. A weak test here is worse than no test.
- [ ] `[HUMAN]` A human reviews the property tests themselves: confirm they use hypothesis, at least 100 examples, and genuinely permute rather than checking a handful of orders.

---

## PHASE 26 — Folder sync

Transport is a plain directory that the user's existing cloud client replicates.
No WebDAV, no S3, no custom protocol, no server.

- [ ] `[AGENT]` Remove all WebDAV code, dependencies, and documentation references.
- [ ] `[AGENT]` Remove S3 and GCS from the primary design. Do not add their SDKs.
- [ ] `[AGENT]` Add config value `SYNC_DIR`, a plain filesystem path chosen by the user.
- [ ] `[AGENT]` Add a Settings control for choosing the folder, with help text explaining any synced cloud folder works.
- [ ] `[AGENT]` Write objects under `SYNC_DIR/enqueue/log/<device_id>/`.
- [ ] `[AGENT]` Ensure a device only ever writes inside its own `device_id` folder. This is what makes a dumb file-sync client safe: two devices can never write the same file.
- [ ] `[AGENT]` Encrypt every event object before writing. Encryption is unconditional and does not depend on which cloud provider owns the folder.
- [ ] `[AGENT]` Write every object to a temporary filename, then atomically rename it into place.
- [ ] `[AGENT]` Verify a checksum on read. Treat a mismatch as not-yet-arrived, never as corruption.
- [ ] `[AGENT]` Batch events into bundles using the time window recorded in decision **D6**. Do not choose the window.
- [ ] `[AGENT]` Store a per-device watermark locally recording what has been applied.
- [ ] `[AGENT]` Implement pull: list objects newer than the watermark, decrypt, apply in clock order.
- [ ] `[AGENT]` Make pull safe to interrupt and rerun.
- [ ] `[AGENT]` Handle placeholder or online-only files as produced by OneDrive, iCloud, and Google Drive streaming. Detect them and either trigger download or defer.
- [ ] `[AGENT]` Never assume the filesystem returns objects in any particular order.
- [ ] `[AGENT]` Add a test harness simulating three devices sharing one temporary directory.
- [ ] `[AGENT]` Add a test with events delivered out of order.
- [ ] `[AGENT]` Add a test with duplicate delivery of the same event.
- [ ] `[AGENT]` Add a test with one device's clock set five minutes ahead.
- [ ] `[AGENT]` Add a test with a device offline for many events, then catching up in one pull.
- [ ] `[AGENT]` Add a test proving two devices editing the same note produce two version rows, both retained, with only the current one decided by the clock.
- [ ] `[AGENT]` Add sync fields to `enq doctor`: watermark per device, unapplied object count, last successful pull time.
- [ ] `[HUMAN]` **STOP.** A human tests with two real machines and a real cloud folder before this is considered working. The simulated harness does not catch sync-client behavior.

---

## PHASE 27 — Original files

- [ ] `[AGENT]` Store originals under `SYNC_DIR/enqueue/blobs/`.
- [ ] `[AGENT]` Name each object using an HMAC of its contents keyed by the data-encryption-key, **not** a plain hash of the contents.
- [ ] `[AGENT]` Add a comment explaining why: a plain content hash lets anyone with folder access test whether a specific known file is in the library.
- [ ] `[AGENT]` Encrypt the file bytes before writing.
- [ ] `[AGENT]` Skip upload entirely for local-only artifacts.
- [ ] `[AGENT]` Add a local cache directory for downloaded originals with a size limit.
- [ ] `[AGENT]` Ensure search never requires downloading an original.
- [ ] `[AGENT]` Write a test making the blobs directory unreadable and confirming search still returns correct results.
- [ ] `[AGENT]` Keep preview thumbnails local and small so browsing never waits on the network.
- [ ] `[AGENT]` Add a Pin For Offline action forcing download of a chosen artifact's original.

---

## PHASE 28 — Optional readable copy in the sync folder

- [ ] `[AGENT]` Add config value `EXPORT_MIRROR_ENABLED`, defaulting to off.
- [ ] `[AGENT]` When enabled, run `enq export` on a schedule into `SYNC_DIR/enqueue/export/`.
- [ ] `[AGENT]` Add a Settings toggle.
- [ ] `[AGENT]` When the user enables it, show: `This saves a readable copy of your library into your sync folder. If your cloud provider is not end-to-end encrypted, they will be able to read it.`
- [ ] `[AGENT]` Document in `AGENTS.md` that the encrypted log is the source of truth and works with any provider, while this readable copy is for human access and its privacy depends on the provider.

---

## PHASE 29 — Trash, and making delete mean delete

Implements decision **D8**.

- [ ] `[AGENT]` Confirm the existing trash feature marks items deleted without removing them.
- [ ] `[AGENT]` Emit `artifact.trashed` when an item is moved to the trash.
- [ ] `[AGENT]` Ensure trashed items are excluded from search, from the wall, and from both lens sections.
- [ ] `[AGENT]` Ensure trashed items can be restored, and that restoring emits an event other devices apply.
- [ ] `[AGENT]` Add an Empty Trash action.
- [ ] `[AGENT]` On Empty Trash, emit `artifact.purged` for each affected artifact.
- [ ] `[AGENT]` On Empty Trash, delete that artifact's original file objects from the sync folder.
- [ ] `[AGENT]` On Empty Trash, delete that artifact's event objects from the sync folder.
- [ ] `[AGENT]` Add a comment explaining that deleting event objects is a deliberate, user-initiated exception to the append-only rule, and the only way Empty Trash can mean what a user expects.
- [ ] `[AGENT]` When a device applies `artifact.purged`, delete the local rows, the local index entries, the local cached original, and any rows in `lens_judgments` for that artifact.
- [ ] `[AGENT]` Write a test: device A empties the trash, device B syncs, and device B no longer has the content in its database, index, cache, or judgment cache.
- [ ] `[AGENT]` Write a test: after Empty Trash, a full `enq rebuild` does not resurrect the purged artifact.
- [ ] `[AGENT]` Implement auto-empty according to **D8**. Do not choose the default.
- [ ] `[AGENT]` Show on the trash screen: `Items here are still stored. Empty the trash to remove them permanently.`
- [ ] `[AGENT]` Show before emptying: `This permanently removes these items from all your devices. This cannot be undone.`

---

## PHASE 30 — Log compaction

Implements decision **D7**.

- [ ] `[AGENT]` Add periodic snapshots under `SYNC_DIR/enqueue/snapshots/`.
- [ ] `[AGENT]` Make a new device able to start from the most recent snapshot instead of replaying all history.
- [ ] `[AGENT]` Implement pruning using the offline window recorded in **D7**. Write the rules into `docs/decisions/` before implementing them.
- [ ] `[AGENT]` Add `enq compact` as an explicit command before making it automatic.
- [ ] `[AGENT]` Write a test: compact, then add a new device, and confirm it reaches identical state.
- [ ] `[AGENT]` Write a test: compact while one simulated device is offline for the full **D7** window, then bring it online and confirm it converges.
- [ ] `[HUMAN]` **STOP.** Pruning is the one operation that deletes history a device may still need. A human reviews the rules and the tests before compaction is ever run automatically.

---

## PHASE 31 — Mobile consistency

Implements decision **D9**.

- [ ] `[AGENT]` Resolve the contradiction in `AGENTS.md` between the statement that a phone reads an index built by a Mac, and the statement that embeddings never leave a device.
- [ ] `[AGENT]` Write the behavior chosen in **D9** into `AGENTS.md` before writing code.
- [ ] `[AGENT]` Ensure a device with no vector index returns keyword results rather than an error.
- [ ] `[AGENT]` Write a test proving search works with the vector tables empty.
- [ ] `[AGENT]` Implement lens availability on keyword-only devices according to **D9**.
- [ ] `[AGENT]` If **D9** chose on-device embeddings, pin the embedding version across platforms and record that decision.

---

## Part 4 done

- [ ] `[AGENT]` Update `PROGRESS.md`: Part 4 complete.
- [ ] `[HUMAN]` Final review: confirm export still works, recovery still works, and a full
      `enq rebuild` on each device produces identical state. Then this plan is finished.
