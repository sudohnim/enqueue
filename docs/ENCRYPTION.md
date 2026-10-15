# Encryption

Enqueue is zero-knowledge.
Nothing it stores off a device, and nothing it leaves on a device's disk, can be read without a key only the person holds.
There is no reset: Enqueue keeps no copy of any key, so the recovery kit is the way back after every device is gone.
This is the design as built on 2026-10-14, and the one step left (hosted sign-in with a passkey), which needs infrastructure.

## The keys

| Key | What it is | Where it lives | What it locks |
| --- | --- | --- | --- |
| Library key | 32 random bytes, made once (`libkey.py`) | macOS Keychain, `enqueue-library-key` | the root: everything on the Mac derives from it or is wrapped under it |
| Disk key | derived from the library key, `disk` | nowhere; derived when needed | the library database on the Mac (SQLCipher) |
| Backup key, backup-names key | derived, `backup`, `backup-names` | nowhere | every file in the backup folder, and their names |
| Sync key (DEK) | 32 random bytes | Keychain `enqueue-sync-dek`; the phone's sealed config; `keyring.json` wrapped under the library key (`dek_by_library`) and under the old recovery phrase | everything on the relay |
| Relay names key | HMAC of the sync key, `enqueue relay names v1` | nowhere | the names of relay objects |
| Phone store key | 32 random bytes, made on the phone | Android: `filesDir/store_key`, encrypted by an Android Keystore key (`StoreKey.kt`); iOS: a Keychain item, this device only (`store_key` in `lib.rs`) | the phone's database (SQLCipher), its sealed secrets, its file cache |
| Vault key | 32 random bytes | wrapped under the 6-digit PIN (and a fingerprint-guarded Keystore secret on the phone) | vaulted items, a second lock inside everything above |

The recovery kit is the library key written as 56 Crockford base32 characters (with a checksum).
It recovers, on a new Mac: the backups, the library inside them, and the sync key (from the `keyring.json` in the backup), so sync comes back too.
The phone needs none of it: it is linked by scanning the Mac's code, which hands it the sync key, and its own store key never leaves it.

## At rest

- **Mac, library:** a SQLCipher database once the recovery kit is saved (`db.encrypt_library`, at the engine's start; checked by integrity and row counts before it replaces the plain file).
  Before the kit is saved the library stays plain on purpose: a lost Keychain would otherwise lose the library itself.
  Every connection comes from `db.connect`, on SQLCipher's driver (`sqlite.py`), which reads a plain file too.
- **Mac, original files (`blobs/`):** not encrypted by Enqueue. FileVault covers a stolen Mac; the folder is the owner's only (0700).
  Encrypting them means routing PDF rendering, previews and captures through a sealed reader; left for later.
- **Backups:** every file sealed (libsodium secretstream) under the backup key, named by keyed hashes, checked by opening it again (`backup.py`).
- **Phone (Android and iOS):** the database is SQLCipher (`bundled-sqlcipher-vendored-openssl`), the sync config and vault records are sealed files, and the file cache is sealed; all under keys derived from the store key.
  A plain database and plain files from an older build are converted the first time they are opened.
  The quick-capture inbox (thoughts written in the launcher popup before the app files them) is still plain, for the seconds it exists.

## In transit (the relay)

- Every object is sealed under the sync key, padded to a size bucket (a power of two from 256 bytes, then multiples of 64 KiB), and named by a keyed hash of its id (`crypto.seal_payload`, `crypto.object_name`; the same in `desktop/src/sync.rs`).
- The relay still sees: how many objects, their bucketed sizes, when they change, and which device namespace wrote them.
- Libraries synced before this were re-pushed once under the new names (`repush_relay_v2`), and each device's old id-named objects deleted, on a relay that has the DELETE route (redeploy the hosted relay with `bin/deploy-relay`).

## Not built: hosted sign-in with a passkey

The paid tier's promise is that a new device signs in with a passkey (Face ID, Touch ID, the phone's lock) and the library arrives, with no recovery kit typed.
The design: the library key is wrapped under a key the passkey derives with the WebAuthn PRF extension, and only that wrapped copy is stored on our server.
The server holds ciphertext; the passkey stays in the person's Apple or Google account.

What it needs, in order:

1. A domain for the service, serving `/.well-known/apple-app-site-association` and `/.well-known/assetlinks.json`.
2. An account server (beside the relay) that stores per account: the wrapped library key, the relay secret, and WebAuthn credentials; with WebAuthn registration and assertion endpoints.
3. The macOS app signed with an Associated Domains entitlement (`webcredentials:<domain>`), since a passkey in a non-Safari web view needs it; likely a small native bridge (ASAuthorizationController with the PRF extension) because WKWebView's WebAuthn support in an embedded app is limited.
4. The Android app with Credential Manager (`androidx.credentials`) and the PRF extension, and the asset links file.
5. A sign-in screen on both: "Sign in with a passkey" restores the library key, then the relay secret, then the sync key from `keyring.json` (or from the account record).
6. Server-side guess limits for the vault PIN, which the hosted server makes possible (the PIN's wrap stays the person's; the server only counts attempts, as Signal's secure value recovery does).

The free tier keeps working without any of it: the person runs their own relay and keeps their recovery kit.
