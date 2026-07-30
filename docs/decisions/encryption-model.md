# Encryption model

Investigated as part of Phase 0, Part 1 of the implementation plan.

## Finding

The database is **plaintext** (no encryption at rest).

## Evidence

`src/enqueue/db.py` opens SQLite via:

```python
conn = sqlite3.connect(config.DB_PATH)
```

No encryption layer, no SQLCipher, no custom VFS. The connection uses standard
`sqlite3` with WAL journal mode and foreign keys enabled. No key is provided at open
time.

The on-disk file at `~/.enqueue-poc/enqueue.db` is a standard SQLite database
(confirmed via `file` command and hex signature `SQLite format 3\0`).

## Decision (D1)

**(C) Not encrypted at all.**

Encryption at rest is a planned milestone, not built yet. When it arrives, it must
be whole-file encryption (option A) because search — both keyword and vector — needs
readable data inside the database.

## Consequences

- Part 3 (sqlite-vec migration) needs no redesign for encryption. The engine sees
  plaintext data regardless.
- Until encryption lands, the database is readable by anything with filesystem access
  to `~/.enqueue-poc/`.
- No secret material (API keys, tokens) is stored in the database. API keys live in
  the macOS Keychain (see `keyring.py`).
