# PLAN.md - the desktop sync setup flow

Clean-cut restart (2026-08-15). The prior PLAN/PROGRESS history was retired; durable
context (architecture, sync/E2E model, Option A pairing, mobile scope, deviations,
build commands) now lives in `AGENTS.md`, `docs/DESIGN.md`, and `README.md`. Read
those first. This file holds only open work.

## Context: what is built, and the one gap

Sync, E2E, and the Android app are built (see `AGENTS.md` "Resolved decisions" #2).
The relay, engine sync client/worker, snapshot LWW, the E2E keyring
(`keyring_file.py`: DEK wrapped under a password-KEK and a recovery-phrase-KEK), and
the mobile app all exist. The desktop can also SHOW a pairing code once configured.

The gap: **there is no way to CONFIGURE sync on the desktop in the first place.**
- `keyring_file.initialize(password)` (creates the DEK, returns the recovery phrase) is
  called by no CLI and no endpoint - the keyring can never be created from a surface.
- The Settings > Sync tab, when unconfigured, shows a dead-end "Not configured" message
  with no inputs (and stale copy: "import your keyring and recovery phrase on your
  mobile device").
- There is no `enq relay` command; the relay only runs via a raw uvicorn factory call.

Result: `keyring_file.dek()` is always None, sync stays locked, and the pairing code UI
(which assumes a configured, initialized library) is unreachable. This phase builds the
front door.

## Pairing model (decided - do not change)

Option A. The pairing code carries ONLY `{relay_url, relay_secret}` - never the DEK,
keyring, or recovery phrase. The key is derived on each device from the LIBRARY
PASSWORD, which never leaves the device. QR renders locally. Full statement in
`AGENTS.md` decision #2.

## Phase SU - the desktop sync setup flow

- [ ] **SU.1 [AGENT]** An `enq relay` CLI command to run the relay locally.
  Wrap `enqueue.relay.app.create_relay(data_dir, secret=...)` in a CLI command
  (`src/enqueue/cli.py`) that serves it with uvicorn. Flags/env for port (default a
  fixed local port, documented), the Bearer secret (`RELAY_SECRET`), and the data dir
  (`RELAY_DATA_DIR`). Bind to `127.0.0.1` by default; a LAN/remote bind is an explicit
  opt-in (the payload is already encrypted, so `guard.py` allows non-local, but the
  default stays local). Document it in `README.md` (running the relay) and `AGENTS.md`
  (CLI surface).
  Done when: `enq relay` boots and answers on the documented local port; a wrong Bearer
  secret is rejected (401); `enq relay --help` shows the flags.

- [ ] **SU.2 [AGENT]** An endpoint to initialize the library keyring.
  Add `POST /settings/keyring-init` taking `{password}` that calls
  `keyring_file.initialize(password)` and returns the recovery phrase ONCE in the
  response body. Guard with `keyring_file.is_initialized()`: refuse to re-initialize an
  existing keyring (that would orphan the current DEK and all synced data) unless an
  explicit destructive flag is passed, and say so in a human sentence. Security: the
  recovery phrase is returned exactly once and never logged, never persisted anywhere
  except its wrapped form inside `keyring.json`; the password is never logged or stored
  in plaintext. Also expose keyring state on `GET /settings` (initialized or not, and
  locked or unlocked) so the UI can branch.
  Done when: a fresh init returns a recovery phrase and writes `keyring.json` with both
  wrap slots; a second init without the destructive flag is refused with a clear
  message; the phrase never appears in any log; `keyring_file.dek()` is non-None after a
  subsequent unlock with that password.

- [ ] **SU.3 [AGENT]** The Settings > Sync setup form (replaces the dead "Not
  configured" state in `static/js/settings.js`). When sync is not configured, render a
  real form, walking the person through, in order:
  1. Relay URL (default the local `enq relay` address from SU.1).
  2. Set a library password → calls SU.2, then displays the recovery phrase ONCE inside
     a clear "write this down, it is the only way to recover if you forget the password"
     panel with an explicit "I have saved it" confirmation before continuing. Never show
     the phrase again after this step.
  3. Set (or generate) the sync secret via the existing `PUT /settings/sync-secret`
     (which already calls `push_keyring()`), and persist the relay URL via
     `PATCH /settings` (`sync_relay_url`).
  On success the tab flips to the already-built "Configured" state (Relay URL / secret
  hint / device id + the Option A pairing code UI). If the keyring is already
  initialized but sync is unconfigured (e.g. re-pairing this same desktop), skip step 2
  and just collect relay URL + secret.
  Done when: from a fresh library, filling the form configures sync end to end - keyring
  created, recovery phrase shown once and confirmed, secret stored, keyring pushed to
  the relay - and the tab then shows the pairing code; reloading Settings shows the
  configured state; `bin/verify` passes.

- [ ] **SU.4 [AGENT]** Fix the stale empty-state copy. Remove the pre-Option-A wording
  ("import your keyring and recovery phrase on your mobile device") from
  `settings.js`; the new SU.3 form replaces it. Grep for any other stale "import your
  keyring" / "scan the QR with your phone's camera" strings that imply removed flows and
  correct them to the Option A language (paste code + library password).
  Done when: no stale sync copy remains; the Sync tab reads consistently with Option A.

- [ ] **SU.5 [AGENT]** End-to-end verification, real devices. With `enq relay` running
  locally and a desktop configured via SU.3: capture an artifact on the desktop, show
  the pairing code, pair a physical phone (`bin/launch mobile`) by pasting the code and
  entering the library password, and confirm the artifact appears on the phone. Capture
  on the phone, confirm it syncs back to the desktop. Record the run in `PROGRESS.md`.
  Done when: an artifact made on either device appears on the other through the local
  relay, with the password never leaving its device and no key material in the pairing
  code.

## Smaller open item (optional, decide before building)

- [ ] **SU.6 [AGENT]** Mobile recovery-phrase fallback. The keyring carries
  `dek_by_recovery`, but mobile setup currently unlocks by password only - lose the
  password on a fresh phone with no other unlocked device and you are stuck until you
  re-pair from the desktop. If wanted, add an "unlock with recovery phrase instead"
  path to `mobile_pairing_setup` (mirror the password branch, using the recovery-KEK
  slot). Skip if the desktop-as-recovery-anchor is acceptable.
  Done when: a phone can unlock with either the password or the recovery phrase; both
  paths give a human error on a wrong secret.

## Out of scope

Same boundaries as before (now recorded in `AGENTS.md` decision #11): no model
enrichment on the phone; one person / one library (no multi-user); iOS is a follow-on;
the relay is additive (sync off = desktop unchanged); `saved_pivots` and chats do not
cross the relay.
