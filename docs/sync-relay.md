# Sync relay protocol

The relay is the live transport for Enqueue sync.
It replaces the synced-folder transport from `docs/e2e/E2E.md` for mobile, while the
folder path stays valid for desktop-to-desktop.

The relay is a dumb byte store.
It holds per-device snapshot objects and content-addressed blobs, serves them back, and
streams a "something changed" signal.
It parses none of the bytes, stores no plaintext, and can decrypt nothing.
In the plaintext prototype (SYNC.1 to SYNC.7) the bytes are canonical-JSON snapshots; in
the encrypted stage (SYNC.8 to SYNC.9) they are the same bytes wrapped in an XChaCha20
ciphertext.
The relay code does not change between those two stages.

## Auth model

There are no user accounts.
One person, one library, a small number of devices.

Each library has one **shared secret** (a per-library sync secret, generated once and
stored in the Keychain on every device, per SYNC.3).
Every device in the library knows the same secret.
The relay trusts any caller that presents it.

- HTTP endpoints carry it as `Authorization: Bearer <secret>`.
- The SSE endpoint carries it as a query parameter `?token=<secret>`, because
  `EventSource` cannot set headers.
  The token is validated on connect, exactly like dequeue's `GET /events?token=<jwt>`.

The relay stores the secret (or a hash of it) only to compare on request; it is not a
user identity and it authorizes nothing beyond "this caller may read and write this
library's objects".
A wrong or missing secret gets `401`.

`device_id` is separate from the secret.
It is a UUID4 generated once per device and stored at `DATA_DIR/device_id` (E2E.md
Section 1).
It names a device's own write namespace and breaks LWW ties; it is not an identity the
relay verifies.

## Object namespace

Objects are named exactly as in E2E.md Section 1, minus the dropped `exhibits/` path
(exhibits were removed in migration 0019; saved-pivot sync is out of scope).

- Snapshot objects: `dev/<device_id>/artifacts/<artifact_id>.enc`
- Blob objects: `blobs/<blob_name>`

`<blob_name>` is the E2E.md content-addressed name `blob_name(content_hash, dek)` - a
hex HMAC-SHA256 of the content hash keyed by the DEK - so a blob's address leaks nothing
about its contents.
Names are the only metadata the relay ever sees.

A device writes **only** to its own `dev/<device_id>/` namespace.
It reads every namespace.

## Endpoints

Base URL is the configured `SYNC_RELAY_URL`, e.g. `https://<host>`.

### 1. `GET /sync/objects?since=<cursor>` - list changed objects

Request:

- `Authorization: Bearer <secret>` header.
- `since` query parameter: an opaque cursor from a previous call, or absent (or `0`) on
  first call.

Response `200`:

```json
{
  "objects": [
    {"name": "dev/<device_id>/artifacts/<id>.enc", "size": 1234},
    {"name": "blobs/<blob_name>", "size": 5678}
  ],
  "cursor": "<opaque-cursor>"
}
```

- `objects` lists every object that changed at or after the cursor, newest first, by
  object name.
- `cursor` is the new cursor to pass to the next call.
  It is an opaque monotonic value; clients must treat it as a black box and never derive
  anything from its shape.
- The list is bounded (the relay may paginate); a client that reaches the end simply
  re-reads with the returned cursor until it sees no new names.
- It never returns the bytes; clients call get-object for bytes they do not have.

### 2. `GET /sync/object/<name>` - fetch one object

Request:

- `Authorization: Bearer <secret>` header.
- `<name>` is a full object name, e.g. `dev/<device_id>/artifacts/<id>.enc` or
  `blobs/<blob_name>`.
  The name is URL-escaped; slashes inside the name are part of the path.

Response `200`:

- `Content-Type: application/octet-stream`.
- Body is the exact bytes that were put, byte-for-byte.
- The relay adds no framing, no envelope, no metadata.

Errors:

- `404` when no object with that name exists.
- `401` on a bad secret.

The relay never interprets the bytes.
A client treats an unreadable or decrypt-failing object as "not yet arrived", never as
corruption (E2E.md Phase E4).

### 3. `PUT /sync/object/<name>` - store one object (write-by-unique-name)

Request:

- `Authorization: Bearer <secret>` header.
- `<name>` is a full object name, same escaping as get-object.
- `Content-Type: application/octet-stream`.
- Body is the object bytes.

Response `201`:

```json
{"name": "<name>", "size": 1234}
```

Semantics:

- Write-by-unique-name: the name is the object's identity.
  A `PUT` of an existing name is a conflict, not an update.
- The relay **never overwrites in place**.
  A re-`PUT` of a name that already exists returns `409 Conflict` and leaves the stored
  object untouched.
- Idempotence for the client: re-pushing an unchanged snapshot is a no-op because the
  name is already present; the client treats `409` as "already there" and moves on.
- The relay writes the object durably (to disk or object storage) before returning, and
  records the name in the change feed that `list-changed-since` and `subscribe` read.

### 4. `GET /sync/events?token=<secret>` - subscribe (SSE)

Request:

- `token` query parameter: the shared secret.
  There is no header form for this endpoint.
- `Accept: text/event-stream`.

Response `200`, then a persistent `text/event-stream`:

```
event: object
data: {"name": "dev/<device_id>/artifacts/<id>.enc", "cursor": "<cursor>"}

event: object
data: {"name": "blobs/<blob_name>", "cursor": "<cursor>"}
```

- One `event: object` is emitted whenever any object changes (a successful `PUT`).
- `data` is a JSON object with the changed object's `name` and the new `cursor`.
- A client uses the `name` to decide whether to fetch, and the `cursor` to reconcile with
  `list-changed-since` if it falls behind.

Reconnect discipline (mirrors dequeue):

- `EventSource` auto-reconnects on transient drops; the client must not add a second
  reconnect loop on top of it.
- `403`/`401` on connect is terminal: the secret is wrong.
- A client that reconnects after a gap must re-run `list-changed-since` from its last
  cursor, because the SSE stream is not a durable log and events emitted while it was
  away are not replayed.
- The relay sends a heartbeat (an SSE comment line, or a `: ping`) at a fixed interval so
  dead connections are noticed and half-open sockets do not linger.

## Object namespace (extended for MOB2.9)

In addition to artifacts and blobs, the sync relay also carries a **settings object**
for MOB2.9:

- Settings objects: `lib/settings/<timestamp>-<device_id>.enc`

Each settings object carries an embedded `updated_at` timestamp in its encrypted payload.
The reader takes the newest by `updated_at` (device id breaks ties), enabling LWW merge
without requiring the relay to parse the contents.
Settings objects are encrypted with the same DEK as artifacts, so the relay still stores
only opaque bytes.

## Running it as a hosted service (public deploy)

The relay is designed to run on a small always-on host (the user picks the
provider - a VPS, a Raspberry Pi at home, a container on any host), reachable
over the internet so the phone syncs anywhere, not only on the same wifi or
plugged in over USB. It stores only opaque ciphertext, so hosting it publicly
changes nothing about the E2E model: `guard.py` already allows non-local relay
URLs because the bytes are encrypted before they leave a device.

- The configured `sync_relay_url` in Settings is the PUBLIC URL, e.g.
  `https://relay.example.com`. The QR/ pairing surfaces must encode that public
  URL, never `127.0.0.1`.
- Run it with `enq relay --host 0.0.0.0 --port <port> --secret <strong-secret>`
  (or `RELAY_HOST`/`RELAY_PORT`/`RELAY_DATA_DIR`/`RELAY_SECRET`). Bind to
  `0.0.0.0` only when it is behind a firewall/reverse proxy - the default
  `127.0.0.1` stays the safe local/dev default.
- The Bearer secret must be sent over TLS in the hosted case. Terminate TLS at
  the edge (Caddy, nginx, a PaaS TLS endpoint, cloudflare) and forward to the
  relay on localhost; the relay itself is plain HTTP behind that. Never expose
  an un-TLS'd relay to the public internet with a guessable secret.
- Give it a real data dir that survives restarts (`RELAY_DATA_DIR`), and back it
  up if the library is irreplaceable - the relay is the only copy of what was
  synced. Disk use is bounded by what devices have pushed; blobs are
  content-addressed and de-duplicated by name.
- **CORS: none needed.** Every sync client is native - the desktop worker is
  Python `httpx` and the mobile client is Rust `ureq`. No browser page talks to
  the relay (mobile.html has no `EventSource`/`fetch` to it), so a public deploy
  needs no CORS middleware. If a browser-origin client is ever added, add
  CORS then.

## Dev tunnel (no deploy needed for development)

To test sync against a reachable URL WITHOUT deploying the relay, expose the
local `enq relay` through a tunnel:

```bash
# terminal 1 - the relay on localhost
uv run enq relay --secret <your-secret>

# terminal 2 - a public URL that forwards to it
cloudflared tunnel --url http://127.0.0.1:8788
# or: ngrok http 8788
```

The tunnel prints a public `https://...` URL; use THAT as `sync_relay_url` (and
in the QR payload). TLS is provided by the tunnel, so the Bearer secret is safe
in transit. The tunnel is for development/testing only - a real host is the
production answer.

## The dev harness is USB by design; the app is not

`bin/launch mobile` runs `cargo tauri android dev`, whose dev-server connection
is USB-tethered by design (`adb reverse`). That is the DEV HARNESS, not the
product: an app that only syncs while plugged in is a bug in the test setup, not
in sync.

To verify the app works unplugged, do NOT use `bin/launch mobile`:
build the apk, install it, and launch it from the phone with USB disconnected:

```bash
cargo tauri android build --debug --target aarch64
# install the apk, disconnect USB, launch from the phone
```

The installed app syncs over the hosted/tunnelled relay (QR.2) with no USB at
all. Treat any "works only while plugged in" result as a failure of the harness
to be ignored, and re-test via the installed apk.

## Security invariants

- The relay stores opaque bytes only.
  It never parses a snapshot, a blob, a settings object, or any field inside them.
- The relay can decrypt nothing.
  Encryption happens on the device before `PUT` (E2E.md Phase E1) and after `GET`
  (E2E.md Phase E4).
  The relay holds neither the DEK, the KEK, nor the recovery phrase.
- The only plaintext the relay ever holds is the object **name**, which is
  `dev/<device_id>/artifacts/<id>.enc` (a UUID and an artifact UUID, deliberately not
  meaningful), `lib/settings/<timestamp>-<device_id>.enc` (a timestamp and device UUID),
  or `blobs/<HMAC>` (a keyed digest that reveals nothing).
- The shared secret authenticates "this caller belongs to this library".
  It grants no finer identity; the relay does not know which device is which and does not
  need to.
