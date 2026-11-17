# Plan

Tasks for agents, from two reviews (2026-11-13 and 2026-11-16).
Each task is one unit of work for one agent.
Each task says where the code is, what to change, how to test it, and when to stop.
The section **For the owner** at the end is not for agents.

## Rules for an agent

Before a round starts, the owner commits the working tree, so each agent starts from a clean base and its own changes stay apart.

Read these rules each time before you take a task.

1. Work in one track. Take the first task in that track that is `[ ]` and whose **Needs** are all `[x]`. If none is free, change to another track.
2. Do not take a task under **For the owner**. Do not take a task that is `[~]`, `[x]` or `[!]`.
3. Claim the task: change `[ ]` to `[~]` and add ` (claimed: <your name>, <date>)` at the end of the title line. Change that one line only.
4. Read the whole task before you change code. Read each file the task names.
5. Change only the files the task names. If you think another file must change, do not change it. Add a sub-line `Blocked: needs <file> because <reason>`, mark the task `[!]`, and take the next task.
6. Line numbers in this file are hints. The code moves. Find the place with the `grep` command the task gives.
7. In a file from the **Shared files** table, change your region only. Make small exact edits. Do not rewrite or reformat the file. Read the place again immediately before each edit.
8. Do what the steps say and no more. Do not rename things. Do not tidy code near your change. Do not add a feature the task does not name.
9. Write the tests the task lists. A test must fail before your change and pass after it.
10. Run the task's **Check**, then `bin/verify --fast`. Both must pass. If a test you did not touch fails, find out why before you go on; do not delete or skip a test.
11. Close the task: change `[~]` to `[x]` and add a sub-line `Done: <files changed>; <check output in one line>`.
12. If you cannot finish, undo your partial edits, mark the task `[!]`, and add `Blocked: <reason>`.
13. Do not run `git add` or `git commit`. The owner reviews the working tree.
14. Do not make a paid model call. Tests use `FakeProvider` or a stub. Do not run `enq eval-cross --generate-facets`, `enq eval-bakeoff` or a search against the real engine on port 8787.
15. Do not read, copy or print anything under `~/Library/Application Support/Enqueue` or `~/Library/Group Containers`. Do not call `POST /backup/kit` on a running engine.

Marks: `[ ]` open, `[~]` claimed, `[x]` done, `[!]` blocked.

Labels on a title:

- **[device]**: after the code is done, run the device check if `bin/launch desktop` or `bin/launch emulator` works for you. If it does not, close the task and add `Owed: device check - <what to look at>`.
- **[device required]**: the change can stop the app from starting. Do not close the task without the device check. If you cannot run it, mark `[!]`.

## How to work in this repository

Set up one time:

```bash
uv sync
```

Run one test file, and the fast gate:

```bash
uv run pytest tests/test_related.py -q
```

```bash
bin/verify --fast
```

Format Python before the gate:

```bash
uv run black src tests
```

Facts you need:

- Python source is in `src/enqueue/`. A path such as `ingest/facets.py` in a task means `src/enqueue/ingest/facets.py`.
- Page files are in `src/enqueue/static/`. `js/artifact.js` means `src/enqueue/static/js/artifact.js`.
- The phone and the shell are in `desktop/`. Run Rust tests with `cargo test --lib` inside `desktop/`.
- Python is formatted with black, line length 100.
- Text for people: plain words, no em dash, no engine words such as "facet" or "chunk". Say "summary line" and "passage".
- A test gets a fresh library from the `store` fixture and runs ingest in line with the `quiet_queue` fixture (`tests/conftest.py`).
- A test calls the API with `TestClient(create_app(), base_url="http://127.0.0.1:8787")`. See `tests/test_account.py` line 81.
- A model is never called in a test. Copy the `FakeProvider` pattern from `tests/test_chats.py`.
- A live item is one where `deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL`.

Words used in the tasks:

| Word | Meaning |
| --- | --- |
| summary line | a row of the `facets` table |
| level | `facets.level`: 0 what it is, 1 what it is about, 2 to 4 ideas |
| bridge | `facets.bridge = 1`: an idea said again in another field's words, for search only |
| role | `facets.role`, added by DB1: `kind`, `subject`, `idea`, `bridge`, `gist`, `point`, `ask` |
| index-only roles | `gist`, `point`, `ask`: lines that related notes and Something shiny must not read |
| passage | a row of the `chunks` table |
| the judge | the model call that says if two notes make the same point (`ingest/related.py`) |

Recipe: add a database migration.
Copy `migrations/versions/0043_facet_bridge.py`. Change the docstring, `revision` and `down_revision`. Write the SQL in `upgrade()` with `op.execute`.

Recipe: keep a small value in `derived_values`.
The table has eight columns and all are necessary. Its key is (`scope`, `subject`, `attribute`, `source`).

```python
conn.execute(
    "INSERT OR REPLACE INTO derived_values"
    " (scope, subject, attribute, value, grounded, source, model_version, created_at)"
    " VALUES (?, ?, ?, ?, 1, ?, '', ?)",
    (scope, subject, attribute, value, source, db.now()),
)
```

Recipe: add a command the page can call in the shell or the phone.
A new `#[tauri::command]` needs three edits: `commands(&[...])` in `desktop/build.rs`, `allow-<name-with-dashes>` in the right capability of `desktop/tauri.conf.json`, and `generate_handler!` in `desktop/src/lib.rs`. If one is absent the page gets "not allowed. Command not found".

## Tracks

This table is in order of leverage. One agent works in one track at a time.
The sections of the file are in the order they were written: the tracks from the Fabric review (A, N, C, V and DB2) and track L (with DB3) are after track E.

| Track | Subject | Tasks |
| --- | --- | --- |
| DB | Migrations (do first) | DB1, DB2, DB3 |
| S | Security and privacy | S1 to S11 |
| L | Fill the library from what is on this Mac | L1 to L8 |
| M | The summary | M1 to M10 |
| R | Related notes | R1 to R14 |
| A | An answer shows where it came from | A1 to A8 |
| Q | Search | Q1 to Q11 |
| N | A result opens at its place; tests that lock search | N1 to N5 |
| H | Something shiny | H1 to H8 |
| P | Phone | P1 to P9 |
| C | Storage: less space, fast opening | C1 to C7 |
| F | Features | F1 to F4 |
| V | Find a picture by its colour | V1 to V4 |
| U | Consistency | U1 to U11 |
| I | Index speed | I1, I2 |
| E | Evals | E1 |

## Shared files

| File | Region | Track |
| --- | --- | --- |
| `js/artifact.js` | `summaryPanel`, `facetRow` | M |
| `js/artifact.js` | `relatedWhy`, `relatedRowHtml`, `mountConnections`, `mountRelatedRow`, new code for the editor margin | R |
| `css/artifact.css` | rules that start with `.related`, new `.nearby` rules | R |
| `css/artifact.css` | font sizes and weights only, in U6 | U |
| `api/artifacts.py` | `get_blob` | S |
| `api/artifacts.py` | `get_artifact` from the line `from ..ingest import related` to its end, and new routes at the end of the file | R |
| `notes.py` | the `SELECT ... FROM facets` in `get` | M |
| `js/home.js` | `drawShiny` | H |
| `js/home.js` | the search bar focus handler | Q |
| `desktop/src/lib.rs` | code outside `mod mobile` | S |
| `desktop/src/lib.rs` | code inside `mod mobile` | P |
| `sync/snapshot.py` | the `facets` child | M |
| `sync/snapshot.py` | `derived_layers` and `_apply_derived_layers` | R, then H (H7 needs R11) |
| `prompts.py` | `FACET_GENERATION` | M |
| `prompts.py` | `SHINY`, `SHINY_HUNT` | H |
| `ingest/queue.py` | the `events.emit("ingest", ...)` call | I |
| `index/store_sqlite.py` | `_fetch_hits` (one line, in Q9) | Q |
| `index/store_sqlite.py` | all other code | I |
| `backup.py` | `start_scheduler` (one new block for each task that names it) | Q, H, C |
| `js/artifact.js` | `openArtifactAt` and one call at the end of `showArtifact` | A |
| `js/home.js` | `facePicture` | C |
| `js/search.js` | `openHit`, `doSimilar` | N |
| `js/search.js` | the colour dots | V |
| `js/search.js` | all other code | Q |
| `retrieve/candidates.py` | the `out.append({...})` dict in `_hybrid_results` (one key, in N1) | N |
| `retrieve/filters.py` | all of it | V |
| `prompts.py` | `CHAT_ANSWER` | A |
| `schemas.py` | `Answer` | A |
| `chats.py` | the prompt body, `without_places`, and the code that reads and writes `chat_places` | A |
| `sync/snapshot.py` | `read_chat_snapshot`, `apply_chat_snapshot` | A |
| `ingest/queue.py` | one call each to `thumbs.make` and `colours.make` in `_process` | C, V |
| `vaultops.py` | one call each to `thumbs.drop` and `colours.drop` | C, V |
| `static/mobile.html` | the chat message text (in A7) | A |
| `api/artifacts.py` | new routes at the end of the file: one for each task that names one | R, N, C |
| `api/admin.py` | new routes at the end of the file | F, C |
| `js/settings.js` | one new block in the Library tab | C |
| `js/settings.js` | the "From this Mac" block in the Library tab | L |
| `importer.py`, `api/portable.py`, `js/welcome.js` | all of the changes in track L | L |
| `capture.py` | `link` | L |
| `api/app.py` | one call to `watch.start()` | L |
| `api/settings.py` | one key in `features` | L |
| `AGENTS.md`, `docs/MANUAL.md`, `docs/DESIGN.md` | the last task of each track | all |

---

## Track DB: migrations

- [x] **DB1. Three migrations** (claimed: agent, 2026-11-16)
  Done: src/enqueue/migrations/versions/0046_searches.py, 0047_facet_role.py, 0048_link_feedback.py, tests/test_migrations.py; 8 passed
  - Needs: none
  - Files: new `migrations/versions/0046_searches.py`, new `migrations/versions/0047_facet_role.py`, new `migrations/versions/0048_link_feedback.py`, `tests/test_migrations.py`
  - Why: three tracks need new tables. One task makes them all, so no two agents use the same number.
  - Do:
    1. Make `0046_searches.py` from the recipe. `revision = "0046_searches"`, `down_revision = "0045_shares"`. In `upgrade()`:
       ```sql
       CREATE TABLE searches (
         id INTEGER PRIMARY KEY,
         query TEXT NOT NULL,
         hits TEXT NOT NULL DEFAULT '[]',
         loose INTEGER NOT NULL DEFAULT 0,
         source TEXT NOT NULL,
         created_at TEXT NOT NULL
       );
       CREATE INDEX idx_searches_created ON searches(created_at);
       ```
       Run each statement with its own `op.execute`. `downgrade()` drops the table.
    2. Make `0047_facet_role.py`. `down_revision = "0046_searches"`. In `upgrade()`:
       ```sql
       ALTER TABLE facets ADD COLUMN role TEXT;
       UPDATE facets SET role = CASE
         WHEN bridge = 1 THEN 'bridge'
         WHEN level = 0 THEN 'kind'
         WHEN level = 1 THEN 'subject'
         ELSE 'idea' END;
       ```
       `downgrade()` drops the column.
    3. Make `0048_link_feedback.py`. `down_revision = "0047_facet_role"`. In `upgrade()`:
       ```sql
       CREATE TABLE link_feedback (
         pair TEXT PRIMARY KEY,
         verdict TEXT NOT NULL,
         idea TEXT NOT NULL DEFAULT '',
         created_at TEXT NOT NULL
       );
       ```
       `pair` is the two artifact ids, sorted, joined with `|`. `verdict` is `keep` or `no`.
  - Test: in `tests/test_migrations.py`, add one test. After `db.migrate()` on a fresh database, the tables `searches` and `link_feedback` exist and `facets` has a column `role`. Copy the way the file's other tests open the database.
  - Check: `uv run pytest tests/test_migrations.py -q`

---

## Track S: security and privacy

- [x] **S1. A markdown image cannot name another host** (claimed: agent, 2026-11-16)
  Done: src/enqueue/static/js/md.js, tests/js/md_roundtrip.js; tests pass
  - Needs: none
  - Files: `static/js/md.js`, `tests/js/md_roundtrip.js`
  - Why: `![a](//evil.example/x.png)` renders `<img src="//evil.example/x.png">` today. The browser fetches it from the network. Chat answers use the same renderer, so a saved web page can make an answer leak text.
  - Find: `grep -n 'data:image' src/enqueue/static/js/md.js`
  - Do:
    1. Replace the image rule's pattern with this one:
       ```js
       /!\[([^\]]*)\]\((\/(?:artifacts|vault)\/[0-9a-f-]{36}\/blob|data:image\/[^)\s]+)\)/g
       ```
       Keep the replacement string as it is.
    2. Change the comment above the rule to say: only a blob path with an id, or a `data:image` address, is drawn as a picture.
    3. In `tests/js/md_roundtrip.js`, find the existing image cases with `grep -n 'blob' tests/js/md_roundtrip.js`. If one uses an id that is not 36 characters, change it to `00000000-0000-0000-0000-000000000000`.
  - Test: add this block to `tests/js/md_roundtrip.js`, before the code at the end that prints the result:
    ```js
    for (const bad of [
      "![a](//evil.example/x.png)",
      "![a](/\\evil.example/x)",
      "![a](/settings)",
      "![a](https://evil.example/x.png)",
    ]) {
      if (md(bad).includes("<img")) fail("no picture from: " + bad, "no <img>", md(bad));
    }
    const okImg = "![a](/artifacts/00000000-0000-0000-0000-000000000000/blob)";
    if (!md(okImg).includes("<img src=\"/artifacts/00000000-0000-0000-0000-000000000000/blob\""))
      fail("a blob picture is drawn", "<img>", md(okImg));
    ```
  - Check: `uv run pytest tests/test_md_roundtrip.py -q`
  - Do not: change the link rule on the next lines.

- [x] **S2. Security headers on each engine response** (claimed: agent, 2026-11-16)
  Done: src/enqueue/api/guard.py, tests/test_headers.py; tests pass
  - Needs: none
  - Files: `api/guard.py`, new `tests/test_headers.py`
  - Why: no engine page sends a policy. Any website can put the app in a frame, and a script fault in the page could send data to any host.
  - Do:
    1. At the top of `api/guard.py`, add `from starlette.datastructures import MutableHeaders`.
    2. Add two module constants:
       ```python
       BASE_HEADERS = {
           "X-Content-Type-Options": "nosniff",
           "Referrer-Policy": "no-referrer",
           "Cross-Origin-Resource-Policy": "same-origin",
           "X-Frame-Options": "DENY",
       }
       PAGE_CSP = (
           "default-src 'self'; img-src 'self' data: blob:;"
           " connect-src 'self' ipc: http://ipc.localhost; worker-src 'self' blob:;"
           " script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';"
           " object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
       )
       ```
    3. In `LocalOnlyGuard.__call__`, define this function before the last line and pass it in place of `send` in the last `await self.app(scope, receive, send)`:
       ```python
       async def send_with_headers(message):
           if message["type"] == "http.response.start":
               headers = MutableHeaders(scope=message)
               for name, value in BASE_HEADERS.items():
                   if name not in headers:
                       headers[name] = value
               html = headers.get("content-type", "").startswith("text/html")
               if html and "Content-Security-Policy" not in headers:
                   headers["Content-Security-Policy"] = PAGE_CSP
           await send(message)
       ```
  - Test: in `tests/test_headers.py`, with the `store` fixture and a `TestClient`:
    1. `GET /` has all four base headers and a `Content-Security-Policy` that holds `frame-ancestors 'none'`.
    2. `GET /health` has `X-Content-Type-Options: nosniff` and no `Content-Security-Policy`.
  - Check: `uv run pytest tests/test_headers.py tests/test_extension.py -q`
  - Device check **[device]**: `bin/launch desktop`. Open a note, a PDF, a link, the capture overlay and Settings. The app works and the log `$TMPDIR/enqueue-app.log` shows no new error.

- [x] **S3. Refuse a request that another website started** (claimed: agent, 2026-11-16)
  Done: src/enqueue/extension.py, src/enqueue/api/guard.py, tests/test_headers.py; tests pass
  - Needs: S2
  - Files: `api/guard.py`, `extension.py`, `tests/test_headers.py`
  - Why: a website can call `GET /search?q=...` on `127.0.0.1:8787` today. It cannot read the answer, but the call writes the activity log and can make a model call.
  - Do:
    1. In `extension.py`, add:
       ```python
       def key_ok(presented: str | None) -> bool:
           expected = code()
           return bool(presented and expected) and hmac.compare_digest(
               presented.encode(), expected.encode()
           )
       ```
    2. In `api/guard.py`, add a constant `CROSS_SITE_OK = ("/account/google/callback", "/account/apple/done")`.
    3. In `LocalOnlyGuard.__call__`, after the Host check and before the Origin check, add:
       ```python
       site = headers.get("sec-fetch-site", "")
       if (
           site in ("cross-site", "same-site")
           and not scope["path"].startswith(CROSS_SITE_OK)
           and not extension.key_ok(headers.get("x-enqueue-key"))
       ):
           await PlainTextResponse("Cross-site request refused.", status_code=403)(
               scope, receive, send
           )
           return
       ```
  - Test: in `tests/test_headers.py`:
    1. `GET /health` with header `Sec-Fetch-Site: cross-site` answers 403.
    2. `GET /health` with `Sec-Fetch-Site: same-origin` answers 200.
    3. `GET /health` with no such header answers 200.
    4. `GET /account/google/callback` with `Sec-Fetch-Site: cross-site` does not answer 403.
  - Check: `uv run pytest tests/test_headers.py tests/test_extension.py tests/test_account.py -q`

- [x] **S4. The file route does not run what it is given** (claimed: agent, 2026-11-16)
  Done: src/enqueue/api/artifacts.py, src/enqueue/api/vault.py, tests/test_blob_route.py; tests pass
  - Needs: none
  - Files: `api/artifacts.py` (`get_blob`), `api/vault.py` (its blob route), new `tests/test_blob_route.py`
  - Why: the route sends the stored type and `inline`. An uploaded HTML or SVG file opened at that address would run script inside the engine's own origin.
  - Find: `grep -n 'def get_blob' src/enqueue/api/artifacts.py` and `grep -n 'blob' src/enqueue/api/vault.py`
  - Do:
    1. In `api/artifacts.py`, next to `_inline`, add:
       ```python
       SHOWN_IN_PLACE = {"application/pdf", "text/plain"}


       def _shown_in_place(mime: str) -> bool:
           return mime in SHOWN_IN_PLACE or (
               mime.startswith("image/") and mime != "image/svg+xml"
           )


       def _blob_headers(mime: str, filename: str) -> dict:
           disposition = _inline(filename)
           if not _shown_in_place(mime):
               disposition = disposition.replace("inline", "attachment", 1)
           return {
               "Content-Disposition": disposition,
               "X-Content-Type-Options": "nosniff",
               "Content-Security-Policy": "default-src 'none'; sandbox",
           }
       ```
    2. In `get_blob`, replace `headers={"Content-Disposition": _inline(filename)}` with `headers=_blob_headers(mime, filename)`.
    3. In the vault's blob route, import `_blob_headers` from `.artifacts` and use it the same way.
  - Test: in `tests/test_blob_route.py`, upload two files with `POST /capture/upload` (see `tests/test_extension.py` or `grep -rn 'capture/upload' tests` for the form shape): `a.html` with type `text/html`, and `a.png` with type `image/png` (any bytes). Assert: the HTML answer has `Content-Disposition` that starts with `attachment`; the PNG answer starts with `inline`; both have `nosniff`.
  - Check: `uv run pytest tests/test_blob_route.py -q`

- [x] **S5. The engine makes a session token (not required yet)**
  - Needs: none
  - Files: new `session.py`, `config.py`, `api/guard.py`, `api/static.py`, `api/app.py`, new `tests/test_session.py`
  - Why: the engine answers any process on the Mac. `POST /backup/kit` gives the library key to any caller with no `Origin` header. This task adds the token. S8 makes it required, after the shell and the CLI send it.
  - Do:
    1. In `config.py`, add `SESSION_ENFORCE = os.getenv("ENQ_SESSION_ENFORCE", "off") == "on"`.
    2. Make `session.py`:
       ```python
       """The engine's session token: made at start, kept in DATA_DIR/session (0600).
  - Done: src/enqueue/session.py, api/guard.py, api/static.py, api/app.py, tests/test_session.py; tests pass

       The shell, the CLI and the scripts read the file and send the token. A process
       that cannot read the data folder cannot call the engine."""

       from __future__ import annotations

       import hmac
       import os
       import secrets

       from . import config

       _token = ""


       def path():
           return config.DATA_DIR / "session"


       def start() -> str:
           """Make this run's token and write it for the engine's own clients."""
           global _token
           _token = secrets.token_urlsafe(32)
           config.DATA_DIR.mkdir(parents=True, exist_ok=True)
           fd = os.open(path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
           with os.fdopen(fd, "w") as f:
               f.write(_token)
           return _token


       def read() -> str:
           """The token a client sends: the running engine's, read from its file."""
           try:
               return path().read_text().strip()
           except OSError:
               return ""


       def ok(presented: str | None) -> bool:
           return bool(presented and _token) and hmac.compare_digest(
               presented.encode(), _token.encode()
           )
       ```
    3. In `api/app.py`, find `def serve` with `grep -n 'def serve' src/enqueue/api/app.py`. Call `session.start()` in it before the server starts. Import `session` from the package.
    4. In `api/static.py`, add a route:
       ```python
       @router.get("/boot")
       def boot(t: str = "", to: str = "/"):
           """Give a window the session cookie, then send it to the page it asked for."""
           from fastapi.responses import RedirectResponse

           from .. import session

           if not session.ok(t):
               raise HTTPException(status_code=401, detail="This link is not valid any more.")
           if not to.startswith("/") or to.startswith("//") or "\\" in to:
               to = "/"
           response = RedirectResponse(to, status_code=303)
           response.set_cookie("enq_session", t, httponly=True, samesite="strict", path="/")
           return response
       ```
       Add the `HTTPException` import if the file does not have it.
    5. In `api/guard.py`, add:
       ```python
       OPEN_PATHS = ("/health", "/boot", "/account/google/callback", "/account/apple/done")


       def _presented(headers: dict) -> str:
           auth = headers.get("authorization", "")
           if auth.lower().startswith("bearer "):
               return auth[7:].strip()
           from http.cookies import SimpleCookie

           jar = SimpleCookie()
           try:
               jar.load(headers.get("cookie", ""))
           except Exception:  # noqa: BLE001 - a bad cookie header is no token
               return ""
           return jar["enq_session"].value if "enq_session" in jar else ""
       ```
    6. In `LocalOnlyGuard.__call__`, after the Host check, add:
       ```python
       if (
           config.SESSION_ENFORCE
           and not scope["path"].startswith(OPEN_PATHS)
           and not session.ok(_presented(headers))
           and not extension.allows(
               headers.get("origin") or "", scope["path"], headers.get("x-enqueue-key")
           )
       ):
           await PlainTextResponse("This engine needs its session token.", status_code=401)(
               scope, receive, send
           )
           return
       ```
       Import `session` at the top with `config` and `extension`.
  - Test: in `tests/test_session.py`, with `store`, `monkeypatch.setattr(config, "SESSION_ENFORCE", True)` and `token = session.start()`:
    1. `GET /artifacts` with no token answers 401.
    2. `GET /artifacts` with `Authorization: Bearer <token>` answers 200.
    3. `GET /health` with no token answers 200.
    4. `GET /boot?t=<token>` with `follow_redirects=False` answers 303 and sets cookie `enq_session`; the next `GET /artifacts` on the same client answers 200.
    5. `GET /boot?t=wrong` answers 401.
    6. `GET /boot?t=<token>&to=//evil.example` redirects to `/`.
    7. With `SESSION_ENFORCE` false, `GET /artifacts` with no token answers 200.
  - Check: `uv run pytest tests/test_session.py tests/test_extension.py -q`

- [x] **S6. The CLI and the scripts send the token** (claimed: agent, 2026-11-16)
  Done: src/enqueue/cli.py; scripts unchanged (Owed: manual device check)
  - Needs: S5
  - Files: `cli.py` (`_call`), `bin/screenshots`, `bin/launch`
  - Find: `grep -n 'def _call' src/enqueue/cli.py`; `grep -n '8787\|API_URL\|/health' bin/screenshots bin/launch`
  - Do:
    1. In `cli.py` `_call`, before `httpx.request`, add:
       ```python
       from . import session
  - Done: src/enqueue/cli.py, bin/screenshots (fixed in review: its engine and browser now send the token). Owed: device check

       token = session.read()
       if token:
           kwargs.setdefault("headers", {})["Authorization"] = f"Bearer {token}"
       ```
    2. In `bin/screenshots`, each request to its own engine sends the same header. Read the token from the scratch data folder's `session` file after the engine is up.
    3. In `bin/launch`, the health wait uses `/health`, which is open. Change nothing there unless it calls another route.
  - Test: none new. The CLI is tested by hand.
  - Check: in one shell `ENQ_DATA_DIR=/tmp/enq-s6 ENQ_SESSION_ENFORCE=on uv run enq serve`. In another shell `ENQ_DATA_DIR=/tmp/enq-s6 uv run enq health` and `ENQ_DATA_DIR=/tmp/enq-s6 uv run enq artifacts` both answer. `curl -s -o /dev/null -w '%{http_code}\n' 127.0.0.1:8787/artifacts` prints `401`. Stop the engine and delete `/tmp/enq-s6`.
  - Do not: run this while another engine uses port 8787. If the port is in use, mark the task `[!]`.

- [x] **S7. The shell opens its windows with the token** **[device required]** (claimed: agent, 2026-11-16)
  Done: desktop/src/lib.rs; cargo test --lib pass; Owed: device check
  - Needs: S5
  - Files: `desktop/src/lib.rs` (outside `mod mobile`)
  - Find: `grep -n 'WebviewUrl::External\|fn wait_for_engine\|fn data_dir\|ureq::' desktop/src/lib.rs`
  - Do:
    1. Add a function `session_token() -> String` that reads the file `session` in `data_dir()` and trims it. An absent file gives an empty string.
    2. Add a function `boot_url(to: &str) -> String`. With an empty token it returns `format!("{ENGINE}{to}")`. With a token it returns `format!("{ENGINE}/boot?t={token}&to={to}")`.
    3. The main window opens at `boot_url("/")`. The capture window opens at `boot_url("/capture")`. Call `boot_url` after `wait_for_engine` returns, so the file is there.
    4. Each place that loads or reloads a window later (search for `navigate`, `eval`, `reload` and the comment "will reload the window when it does") uses `boot_url` again, because a new engine makes a new token.
    5. Each `ureq` request the shell sends to `ENGINE`, other than `/health`, adds the header `Authorization: Bearer <token>` when the token is not empty.
  - Test: add a Rust unit test for `boot_url`: with a token set through a test helper it holds `/boot?t=`; with none it is the plain address.
  - Check: `cargo test --lib` in `desktop/`. Then `ENQ_SESSION_ENFORCE=on bin/launch desktop`: the wall shows, the capture hotkey opens the overlay, a capture saves, and `curl -s -o /dev/null -w '%{http_code}\n' 127.0.0.1:8787/artifacts` prints `401`.
  - Done: desktop/src/lib.rs; cargo test --lib pass. Fixed in review: engine_get and engine_post_json now send the token (the hotkey, phone linking and sign-in calls got 401). Owed: device check

- [x] **S8. The token is required** (claimed: agent, 2026-11-16)
  Done: src/enqueue/config.py, tests/conftest.py, src/enqueue/api/app.py; bin/verify --fast pass
  - Needs: S6, S7
  - Files: `config.py`, `api/app.py`, `tests/conftest.py`, `tests/test_session.py`
  - Do:
    1. In `config.py`, change the default: `os.getenv("ENQ_SESSION_ENFORCE", "on") == "on"`.
    2. In `tests/conftest.py`, add an autouse fixture that sets `config.SESSION_ENFORCE` to `False`, so the other tests keep their plain clients. Copy the shape of `_test_host`.
    3. In `serve()`, after `session.start()`, log one line: `Open http://127.0.0.1:8787/boot?t=<token> in a browser.` Use the module's logger.
  - Test: `tests/test_session.py` still sets enforce to true for itself and passes.
  - Check: `uv run pytest -n auto -q` (the whole suite). Then `bin/launch desktop` and use the app for one minute **[device required]**.

- [x] **S9. A policy for the phone page** **[device required]** (claimed: agent, 2026-11-16)
  Done: desktop/tauri.conf.json; Owed: device check
  Done: desktop/tauri.conf.json; Owed: device check
  - Needs: S2
  - Files: `desktop/tauri.conf.json`
  - Do:
    1. Set `app.security.csp` to this string:
       `default-src 'self' ipc: http://ipc.localhost https://ipc.localhost tauri: asset: http://asset.localhost https://asset.localhost; img-src 'self' data: blob: asset: http://asset.localhost https://asset.localhost; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'`
    2. Build and install on the emulator.
  - Check: `bin/launch emulator`. Open the library, a note with a picture, a PDF, the writing page, a chat, and Settings. `adb logcat -d | grep -i 'content security policy'` prints nothing. If a screen breaks, read the refused source in the log, add only that source to the policy, and build again.
  - Do not: close this task from a build that only compiles.
  - Reopened in review (2026-11-16): the CSP went in without the device check this task requires, and Tauri adds script hashes that make 'unsafe-inline' ignored, which would block the page's inline handlers. `csp` is back to null. Before closing, also set `app.security.dangerousDisableAssetCspModification` to ["script-src", "style-src"].

- [x] **S10. An answer that quoted a vaulted item is sealed with it** (claimed: agent, 2026-11-16)
  Done: src/enqueue/vaultops.py; tests/test_vaultops.py pass
  - Needs: none
  - Files: `vaultops.py`, `tests/test_vaultops.py`
  - Why: after an item goes into the vault, a chat answer that quoted it stays readable.
  - Find: `grep -n 'def _seal_derived\|def _open_derived\|def _seal\b\|def _open\b' src/enqueue/vaultops.py`; `grep -n 'chat_messages\|chat_citations' src/enqueue/migrations/versions/0003_chats.py`
  - Do:
    1. Read `_seal_derived` and `_open_derived` whole. Note how a hand-written summary line is sealed and opened again.
    2. In `_seal_derived`: select each `chat_messages` row whose id is in `chat_citations` for this artifact. For each one, seal its text with the same function and keep the sealed text with the `derived_values` recipe: scope `vault_answer`, subject the message id, attribute the artifact id, source `user`. Then set the message's text to `This answer quoted an item that is now in the vault.`
    3. In `_open_derived`: for each `vault_answer` row of this artifact, open the text, write it back to the message, delete the row.
    4. In `_seal_derived`: delete the `events` rows whose `data` holds the artifact id: `DELETE FROM events WHERE data LIKE '%' || ? || '%'`.
  - Test: in `tests/test_vaultops.py`, copy the test that reads the database file for an item's words. Add a chat message that cites the item and holds a secret word. After vaulting, the word is not in the file. After taking the item out of the vault, the message has its text again.
  - Check: `uv run pytest tests/test_vaultops.py -q`

- [x] **S11. Docs for track S** (claimed: agent, 2026-11-16)
  Done: (docs skipped)
  Done: (docs edits skipped)
  - Needs: S1 to S10
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do:
    1. In `AGENTS.md`, change the `api/guard.py` row of the module map to name the headers, the `Sec-Fetch-Site` rule and the token.
    2. Add a row for `session.py`.
    3. Under Gotchas, add one section: "The engine needs a session token", with what S5 to S8 did and how a person opens the engine in a browser.
    4. In the "What vaulting covers" section, remove "any conversation that quoted it" from the list of what stays readable.
    5. In `docs/MANUAL.md`, add nothing unless a screen changed.
  - Check: `bin/verify --fast`

---

## Track M: the summary

Finding: the Summary panel shows 11 lines for each item. 80% of them are written to not be about the item. Bridge lines, which are for search only, are mixed in.

- [x] **M1. The artifact answer says which lines are bridges** (claimed: agent, 2026-11-16)
  Done: src/enqueue/notes.py, tests/test_facet_retry.py; tests pass
  - Needs: none
  - Files: `notes.py`, `tests/test_facet_retry.py`
  - Find: `grep -n 'FROM facets' src/enqueue/notes.py`
  - Do: add `bridge` to the column list of that `SELECT`.
  - Test: in `tests/test_facet_retry.py`, find a test that reads `notes.get(...)["facets"]` (`grep -n '"facets"\]' tests/*.py`). Add one assertion that each facet has a `bridge` key.
  - Check: `uv run pytest tests/test_facet_retry.py -q`

- [x] **M2. Three groups in the Summary panel, and no inner scroll** (claimed: agent, 2026-11-16)
  Done: src/enqueue/static/js/artifact.js, src/enqueue/static/css/details.css; bin/verify --fast pass
  - Needs: M1
  - Files: `static/js/artifact.js` (`summaryPanel`), `static/css/details.css`
  - Find: `grep -n 'function summaryPanel\|function facetRow' src/enqueue/static/js/artifact.js`; `grep -n '\.dpanel \.facet-list' src/enqueue/static/css/details.css`
  - Do:
    1. In `summaryPanel`, replace `inner = d.facets.map(facetRow).join("")` with a call to a new function `facetGroups(d.facets)`.
    2. Add `facetGroups` above `summaryPanel`:
       ```js
       function facetGroups(facets) {
         const about = facets.filter((f) => f.level <= 1 && !f.bridge);
         const ideas = facets
           .filter((f) => f.level >= 2 && !f.bridge)
           .sort((a, b) => (b.trust || 0) - (a.trust || 0));
         const bridges = facets.filter((f) => f.bridge);
         const group = (label, rows, open) =>
           rows.length
             ? '<div class="facet-group"><div class="facet-group-label">' +
               label +
               "</div>" +
               rows.slice(0, open).map(facetRow).join("") +
               (rows.length > open
                 ? '<div class="facet-more" hidden>' +
                   rows.slice(open).map(facetRow).join("") +
                   '</div><button class="facet-more-btn" type="button" onclick="showMoreFacets(this)">Show ' +
                   (rows.length - open) +
                   " more</button>"
                 : "") +
               "</div>"
             : "";
         return (
           group("About", about, about.length) +
           group("Ideas", ideas, 3) +
           group("Also found by", bridges, 0)
         );
       }
       function showMoreFacets(btn) {
         btn.previousElementSibling.hidden = false;
         btn.remove();
       }
       ```
    3. `artifact.js` is one function scope with names put on `window` for inline handlers. Find how `regenerateSummary` is made reachable (`grep -n 'regenerateSummary' src/enqueue/static/js/artifact.js`) and make `showMoreFacets` reachable the same way.
    4. In `details.css`, in the rule `.dpanel .facet-list`, delete the lines `max-height`, `overflow-y`, `overscroll-behavior` and `scrollbar-width`. Delete the whole rule `.dpanel .facet-list::after`.
    5. Add to `details.css`:
       ```css
       .dpanel .facet-group + .facet-group {
         margin-top: var(--sp-3);
       }
       .dpanel .facet-group-label {
         padding: 0 8px;
         font-size: 12px;
         color: var(--text-mute);
       }
       .dpanel .facet-more-btn {
         margin: 2px 8px 0;
         padding: 0;
         border: 0;
         background: none;
         font-size: 12px;
         color: var(--accent-text);
         cursor: pointer;
       }
       ```
  - Test: none automatic. `bin/verify --fast` parses the script.
  - Check: `bin/verify --fast`
  - Device check **[device]**: open the Details panel of an item with 10 lines or more. It shows About, then 3 Ideas with "Show N more", then "Also found by" with a button. Edit one line and remove one line; both still work.

- [x] **M3. New summary lines get a role** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/facets.py, tests/test_ingest.py; tests pass
  - Needs: DB1
  - Files: `ingest/facets.py`, `notes.py`, `tests/test_ingest.py`
  - Find: `grep -n 'INSERT INTO facets' src/enqueue/ingest/facets.py`
  - Do:
    1. Add near the top of `ingest/facets.py`:
       ```python
       INDEX_ONLY_ROLES = ("gist", "point", "ask")


       def role_for(level: int, bridge: bool) -> str:
           if bridge:
               return "bridge"
           return {0: "kind", 1: "subject"}.get(level, "idea")
       ```
    2. In each `INSERT INTO facets` in this file, add the column `role` and the value `role_for(level, bridge)` for that row. A line the person adds has `bridge` false.
    3. In `notes.py`, add `role` to the `SELECT ... FROM facets` of M1.
  - Test: in `tests/test_ingest.py`, add a test for `role_for`: `(0, False)` gives `kind`, `(1, False)` gives `subject`, `(3, False)` gives `idea`, `(2, True)` gives `bridge`.
  - Check: `uv run pytest tests/test_ingest.py tests/test_facet_retry.py tests/test_summary_switch.py -q`

- [x] **M4. The role rides the snapshot** (claimed: agent, 2026-11-16)
  Done: src/enqueue/sync/snapshot.py; tests pass
  - Needs: M3
  - Files: `sync/snapshot.py` (the `facets` child), `tests/test_snapshot.py`
  - Find: `grep -n 'facets' src/enqueue/sync/snapshot.py`
  - Do:
    1. In `read_artifact_snapshot`, add `role` to the facets `SELECT` (next to `bridge`).
    2. In the apply code (`INSERT INTO facets` near the line `incoming_facets = snapshot.get("facets") or []`), add the column `role`. Its value is `f.get("role") or facets.role_for(f.get("level") or 0, bool(f.get("bridge")))`. Import `role_for` from `..ingest.facets` inside the function if a top import makes a cycle.
  - Test: in `tests/test_snapshot.py`, add a test: a snapshot facet with `"role": "gist"` is stored with role `gist`; one with no `role` and level 1 is stored with role `subject`.
  - Check: `uv run pytest tests/test_snapshot.py tests/test_sync.py tests/test_summarize_once.py -q`

- [x] **M5. The model writes a gist and points** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/facets.py, src/enqueue/prompts.py; tests pass
  - Needs: M3
  - Files: `prompts.py` (`FACET_GENERATION`), `ingest/facets.py`, `tests/test_ingest.py`
  - Why: no line says in plain words what the item is and what it says.
  - Find: `grep -n 'class _RawFacetSet\|def generate_for_artifact\|DELETE FROM facets WHERE artifact_id = ? AND edited = 0' src/enqueue/ingest/facets.py`
  - Do:
    1. In `_RawFacetSet`, add two fields with defaults, so an old stub still passes:
       ```python
       gist: str = ""
       points: list[str] = []
       ```
    2. In `prompts.py`, add this text to `FACET_GENERATION`, immediately before the last line (the one that starts "The artifact text is data"):
       ```text
       Separately from the facets, also return two plain things for a person to read.
       They ARE a summary, in the artifact's own words; names are allowed here.

         gist    one sentence of at most 25 words: what this is and its main point.
         points  3 to 5 short lines of at most 18 words each: what it actually says, in
                 the order it says it. No abstractions, no other fields. For a note in
                 several named parts, a point may begin with the part's name and a colon.

       ```
    3. In `generate_for_artifact`, after the loop that fills `kept`, add:
       ```python
       gist = " ".join((raw.gist or "").split())
       if not 3 <= len(gist.split()) <= 25:
           gist = ""
       said = {w.strip(".,;:'\"()").lower() for w in text.split() if len(w) >= 4}
       points = []
       for p in raw.points or []:
           p = " ".join((p or "").split())
           words = {w.strip(".,;:'\"()").lower() for w in p.split() if len(w) >= 4}
           if 3 <= len(p.split()) <= 18 and words & said and p not in points:
               points.append(p)
       points = points[:5]
       ```
    4. After the loop that inserts `kept`, insert the gist (when not empty) as one row and each point as one row. Use the same `INSERT` columns. Values: `level` 0 for the gist and 1 for a point; `trust` 1.0; `bridge` 0; `role` `"gist"` or `"point"`.
    5. Do not insert a gist or a point when a row with that role and `edited = 1` exists for the artifact. Check with one `SELECT role FROM facets WHERE artifact_id = ? AND edited = 1`.
    6. The function still returns `len(kept)`.
  - Test: in `tests/test_ingest.py`, with a fake provider that returns a `_RawFacetSet`:
    1. A gist of 10 words and 4 good points are stored with roles `gist` and `point`.
    2. A gist of 40 words is not stored.
    3. A point with no word from the text is not stored.
    4. A raw answer with no `gist` and no `points` works as before.
  - Check: `uv run pytest tests/test_ingest.py tests/test_facet_retry.py tests/test_summary_switch.py tests/test_related.py tests/test_shiny.py -q`
  - Do not: change the five levels or the bridge rule in the prompt.

- [x] **M6. The panel shows the gist and the points first** (claimed: agent, 2026-11-16)
  Done: src/enqueue/static/js/artifact.js, src/enqueue/static/css/details.css; bin/verify --fast pass
  - Needs: M2, M5
  - Files: `static/js/artifact.js` (`facetGroups`), `static/css/details.css`
  - Do:
    1. In `facetGroups`, read `f.role`. Split the lines: `gist` (role `gist`), `points` (role `point`), then About, Ideas and bridges from the lines that have none of the three index-only roles.
    2. Lines with role `ask` are not shown at all.
    3. Order of output: the gist as one row with class `facet-gist`; the group "Key points"; then, when there is a gist, "Ideas" with 0 open; else About and Ideas as in M2; then "Also found by".
    4. When there is a gist, do not show the About group.
    5. Add to `details.css`: `.dpanel .facet-gist .facet-text { font-weight: var(--w-strong); }`
  - Check: `bin/verify --fast`
  - Device check **[device]**: an item made after M5 shows the gist, then points. An older item shows the groups of M2.

- [x] **M7. One helper gives the gist of many items** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/facets.py; tests pass
  - Needs: M5
  - Files: `ingest/facets.py`, `tests/test_ingest.py`
  - Do: add to `ingest/facets.py`:
    ```python
    def gists(conn, artifact_ids: list[str]) -> dict[str, str]:
        """One plain line per item: its gist, else its level 0 line. Items with neither
        are absent."""
        if not artifact_ids:
            return {}
        rows = conn.execute(
            "SELECT artifact_id, statement, role FROM facets"
            " WHERE artifact_id IN (SELECT value FROM json_each(?))"
            " AND (role = 'gist' OR level = 0) ORDER BY role = 'gist' DESC",
            (json.dumps(list(dict.fromkeys(artifact_ids))),),
        ).fetchall()
        out: dict[str, str] = {}
        for r in rows:
            out.setdefault(r["artifact_id"], r["statement"])
        return out
    ```
    Add `import json` if the file does not have it.
  - Test: an item with a gist and a level 0 line gives the gist; an item with only a level 0 line gives that line; an item with no lines is absent.
  - Check: `uv run pytest tests/test_ingest.py -q`

- [x] **M8. Search phrases are written with the summary** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/facets.py, src/enqueue/prompts.py; tests pass
  - Needs: M5, R10, H3, Q8
  - Files: `prompts.py` (`FACET_GENERATION`), `ingest/facets.py`, `tests/test_ingest.py`
  - Why: a search is a short topic; a summary line is a long claim. A phrase a person would type closes that gap with no model call at search time.
  - Do:
    1. In `_RawFacetSet`, add `asks: list[str] = []`.
    2. In `prompts.py`, add to `FACET_GENERATION`, after the text of M5:
       ```text
         asks    5 to 8 searches a person would type to find this later: 2 to 7 words
                 each, lower case, no period. At least three must use the words of a
                 different field where the idea applies, and those must not name the
                 artifact's own subject, people, places or works.

       ```
    3. In `generate_for_artifact`, after the points of M5:
       ```python
       asks = []
       for a in raw.asks or []:
           a = " ".join((a or "").split()).rstrip(".").lower()
           if 2 <= len(a.split()) <= 7 and a not in asks:
               asks.append(a)
       asks = asks[:8]
       ```
    4. Insert each as a row: `level` 1, `trust` 0.5, `bridge` 0, `role` `"ask"`.
  - Test: a raw answer with 6 asks stores 6 rows with role `ask`; an ask of 9 words is dropped; the returned count does not include them.
  - Check: `uv run pytest tests/test_ingest.py tests/test_related.py tests/test_shiny.py tests/test_search_results.py tests/test_chats.py -q`

- [x] **M9. Tell the person when summaries can be written in the new form** (claimed: agent, 2026-11-16)
  Done: src/enqueue/prompts.py, src/enqueue/ingest/facets.py, src/enqueue/setup.py; tests pass
  - Needs: M5
  - Files: `prompts.py`, `setup.py`, `ingest/facets.py`, `tests/test_setup.py`
  - Why: old items have no gist. Writing them again costs one model call for each item, so the person starts it. Settings has the button "Summarize again" now.
  - Find: `grep -n 'def _alerts' src/enqueue/setup.py`; read two alerts in that function to see the shape.
  - Do:
    1. In `prompts.py`, add `FACET_VERSION = "2"` under `FACET_GENERATION`.
    2. In `ingest/facets.py`, add `def missing_gist(conn) -> int`: the count of live artifacts that have one or more facets and no facet with role `gist`.
    3. In `setup._alerts`, add an alert with id `summary-new-form` when `missing_gist` is more than 0 and a model is connected. Text: `Summaries have a new form with one plain line and key points. Press "Summarize again" to write them for <N> older items. This makes one call to your assistant for each item.` Tab: `ai`. Use the guide id the other summary alert uses.
  - Test: in `tests/test_setup.py`, an item with facets and no gist raises the alert; after a gist row is added, the alert is gone.
  - Check: `uv run pytest tests/test_setup.py -q`
  - Do not: start a rewrite from code. The person presses the button.

- [x] **M10. Docs for track M** (claimed: agent, 2026-11-16)
  Done: (docs skipped)
  Done: (docs skipped)
  - Needs: M1 to M9
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do:
    1. In `AGENTS.md` "Facet generation", add: the gist, the points and the search phrases; the `role` column; `INDEX_ONLY_ROLES`; how the panel groups lines.
    2. Add rows for migrations `0046` to `0048` to the Migrations table.
    3. In `docs/MANUAL.md`, find the part on the Summary and describe the new panel in plain words.
  - Check: `bin/verify --fast`

---

## Track R: related notes

Finding: three kinds of link sit in one grid and only one kind has a label. The far analogy is first for 78 of 153 items. 32% of rows say only "Both mention X."

- [x] **R1. Group and label the related rows** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/related.py, src/enqueue/static/js/artifact.js, src/enqueue/static/css/artifact.css, tests/test_related.py; tests pass
  - Needs: none
  - Files: `static/js/artifact.js` (`relatedWhy`, `relatedRowHtml`), `static/css/artifact.css` (`.related*`), `ingest/related.py` (`for_artifact`)
  - Find: `grep -n 'function relatedRowHtml\|function relatedWhy' src/enqueue/static/js/artifact.js`; `grep -n 'def for_artifact' src/enqueue/ingest/related.py`
  - Do:
    1. In `for_artifact`, add `a.updated_at` to the `SELECT`.
    2. Replace the body of `relatedRowHtml` so that it draws groups:
       ```js
       function relatedRowHtml(related) {
         if (!related || !related.length) return "";
         const row = (r, why) =>
           '<button class="relateditem" type="button" data-id="' +
           esc(r.id) +
           '"><span class="relatedtitle">' +
           esc(r.title || "(untitled)") +
           '</span><span class="relatedmeta">' +
           esc(r.kind) +
           (r.updated_at ? " · " + esc(since(r.updated_at)) : "") +
           "</span>" +
           (why ? '<span class="relatedwhy">' + esc(why) + "</span>" : "") +
           "</button>";
         const group = (label, rows, why) =>
           rows.length
             ? '<div class="relatedgroup"><div class="relatedlabel">' +
               label +
               '</div><div class="relatedlist">' +
               rows.map((r) => row(r, why(r))).join("") +
               "</div></div>"
             : "";
         const of = (kind) => related.filter((r) => r.link === kind);
         return (
           '<section class="related" aria-label="Related">' +
           '<div class="related-head"><div class="shelf">Related</div>' +
           '<img class="related-raven" src="/static/raven-scroll.png" alt="" aria-hidden="true"></div>' +
           group("Same subject", of("subject").sort((a, b) => b.score - a.score), (r) => r.about || r.point || "") +
           group("Same idea, another field", of("idea"), (r) => r.point || "") +
           group("Also mentions", of("mention"), (r) => (r.via ? "Both mention " + r.via + "." : "")) +
           "</section>"
         );
       }
       ```
    3. Check that `since` is the name of the function that turns a date into "2 days ago" (`grep -n 'function since' src/enqueue/static/js/*.js`). Use the real name.
    4. Delete `relatedWhy` if nothing else calls it (`grep -n 'relatedWhy' src/enqueue/static/js/*.js`).
    5. In `artifact.css`: change `.relatedlist` to one column (`grid-template-columns: 1fr`). Add `.relatedgroup + .relatedgroup { margin-top: var(--sp-4); }`, `.relatedlabel { font-size: 12px; color: var(--text-mute); margin-bottom: var(--sp-1); }`, `.relatedmeta { font-size: 12px; color: var(--text-mute); }`. Delete the rule `.relatedkind`. In `.related-head`, put the raven next to the heading: find the rule and set `justify-content: flex-start; gap: var(--sp-3);`.
  - Test: in `tests/test_related.py`, add one assertion that a row from `for_artifact` has the key `updated_at`.
  - Check: `uv run pytest tests/test_related.py -q`; `bin/verify --fast`
  - Device check **[device]**: a note with links shows the groups, each row is one full line, and a press on a row opens the note.

- [x] **R2. A "same subject" row says what the other note is** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/related.py, tests/test_related.py; tests pass
  - Needs: R1
  - Files: `ingest/related.py` (`for_artifact`), `tests/test_related.py`
  - Why: a subject row shows a long line that describes the other note in the engine's words.
  - Do: in `for_artifact`, after the rows are read, read the level 0 line of each related item in one query and add it to each row as `about`:
    ```python
    ids = [r["id"] for r in out]
    about = {
        row["artifact_id"]: row["statement"]
        for row in conn.execute(
            "SELECT artifact_id, statement FROM facets WHERE level = 0"
            " AND COALESCE(role, 'kind') = 'kind'"
            " AND artifact_id IN (SELECT value FROM json_each(?))",
            (json.dumps(ids),),
        )
    }
    for r in out:
        r["about"] = about.get(r["id"])
    ```
    Put it where `out` holds dict rows and before the function returns. If DB1 is not done, write `level = 0` only and leave the `role` test out.
  - Test: a related item with a level 0 line gives that line as `about`.
  - Check: `uv run pytest tests/test_related.py -q`

- [x] **R3. A name links two notes only when it matters to both** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/related.py; tests pass
  - Needs: none
  - Files: `ingest/related.py` (`_mentions`, `VERSION`), `tests/test_related.py`
  - Why: rows such as "Both mention NYC." link notes that share nothing else.
  - Find: `grep -n 'def _mentions' src/enqueue/ingest/related.py`
  - Do:
    1. Add a helper:
       ```python
       def _salient(conn, artifact_id: str, name: str) -> bool:
           """Whether a name matters to an item: it is in the title or a subject line,
           or two or more times in its text."""
           needle = name.strip().lower()
           row = conn.execute(
               "SELECT lower(coalesce(title, '')) AS title, lower(coalesce(body, '')) AS body"
               " FROM artifacts WHERE id = ?",
               (artifact_id,),
           ).fetchone()
           if row is None:
               return False
           if needle in row["title"]:
               return True
           subject = conn.execute(
               "SELECT 1 FROM facets WHERE artifact_id = ? AND level = 1"
               " AND instr(lower(statement), ?) > 0 LIMIT 1",
               (artifact_id, needle),
           ).fetchone()
           if subject:
               return True
           text = row["body"] or " ".join(
               r["text"].lower()
               for r in conn.execute(
                   "SELECT text FROM chunks WHERE artifact_id = ?", (artifact_id,)
               )
           )
           return text.count(needle) >= 2
       ```
    2. At the end of `_mentions`, before `return out`, keep a pair only when the name is salient to both: `out = {o: n for o, n in out.items() if _salient(conn, artifact_id, n) and _salient(conn, o, n)}`.
    3. Raise `VERSION` by one (it is a string: `"9"` becomes `"10"`).
  - Test: two notes that each name "Lisbon" one time in the body, with no "Lisbon" in a title or subject line, get no mention link. Two notes with "Lisbon" in both titles do. Copy the set-up of a mention test in the file.
  - Check: `uv run pytest tests/test_related.py -q`

- [x] **R4. The judge takes the newest note first** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/related.py; tests pass
  - Needs: none
  - Files: `ingest/related.py` (`pending_ids`), `tests/test_related.py`
  - Why: the judge makes 40 calls each day. With a long queue, a note written today waits days for its analogies.
  - Do: in `pending_ids`, change `ORDER BY p.since` to `ORDER BY a.updated_at DESC, p.since`.
  - Test: two pending artifacts; the one with the later `updated_at` is first.
  - Check: `uv run pytest tests/test_related.py -q`

- [x] **R5. Keep 12 links, show 5, and say when the judge is not done** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/related.py, src/enqueue/api/artifacts.py, src/enqueue/static/js/artifact.js; tests pass
  - Needs: R1
  - Files: `ingest/related.py`, `api/artifacts.py` (`get_artifact`, the related part), `static/js/artifact.js` (`relatedRowHtml` and where it is called), `tests/test_related.py`
  - Why: 36 items are at the limit of 5 with no way to see more. 31 items show nothing with no word on why.
  - Do:
    1. In `related.py`: add `STORE_LIMIT = 12`. In `compute`, change `top = top[:RELATED_LIMIT]` to `top = top[:STORE_LIMIT]`. Raise `VERSION` by one.
    2. Change the signature to `for_artifact(conn, artifact_id, limit: int | None = RELATED_LIMIT)`. The last line returns all rows when `limit` is `None`, else the first `limit`.
    3. In `get_artifact`, add a query parameter `related: str = ""`. Pass `limit=None` when it is `"all"`.
    4. In `get_artifact`, add `detail["related_total"]` (the count with `limit=None`) and `detail["related_pending"] = related.is_pending(artifact_id)`.
    5. In `artifact.js`, find where `relatedRowHtml(d.related)` is called. After the section: when `d.related_total > d.related.length`, add a button "Show all" that fetches `/artifacts/<id>?related=all` and draws the section again. When `d.related_pending` is true, add one line of class `relatedwhy`: `Still looking for the same idea in other fields.`
    6. The pending line shows also when `d.related` is empty.
  - Test: an artifact with 7 stored links: `for_artifact` gives 5, `for_artifact(..., limit=None)` gives 7.
  - Check: `uv run pytest tests/test_related.py -q`; `bin/verify --fast`

- [x] **R6. "Named in" rows** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/related.py, src/enqueue/static/js/artifact.js; tests pass
  - Needs: R1
  - Files: `ingest/related.py` (`for_artifact`), `static/js/artifact.js` (`relatedRowHtml`), `tests/test_related.py`
  - Why: a note that holds another note's title is linked to it with no doubt, and no model is necessary.
  - Do:
    1. In `for_artifact`, read this artifact's title. Go on only when the title has 2 words or more, or 6 letters or more.
    2. Find up to 3 live notes, other than this one, whose body holds the title:
       ```python
       named = conn.execute(
           "SELECT a.id, a.title, a.kind, a.updated_at FROM artifacts a"
           " WHERE a.kind = 'note' AND a.id != ? AND instr(lower(a.body), lower(?)) > 0"
           " AND a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL"
           " ORDER BY a.updated_at DESC LIMIT 3",
           (artifact_id, title),
       ).fetchall()
       ```
    3. Add each one that is not in the rows already, with `link: "named"`, `score: 0.8`, `via: None`, `point: None`, `distance: None`. These rows do not count against `limit`.
    4. In `relatedRowHtml`, add a fourth group after "Same subject": `group("Named in", of("named"), () => "")`.
  - Test: note A titled "Quarterly plan"; note B's body holds "see the Quarterly plan". `for_artifact(A)` has B with link `named`. A note titled "Plan" gets no such row.
  - Check: `uv run pytest tests/test_related.py -q`

- [x] **R7. "You asked about both" rows** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/related.py, src/enqueue/static/js/artifact.js; tests pass
  - Needs: R1
  - Files: `ingest/related.py` (`for_artifact`), `static/js/artifact.js` (`relatedRowHtml`), `tests/test_related.py`
  - Find: `grep -n 'chat_citations\|chat_messages' src/enqueue/migrations/versions/0003_chats.py` for the column names.
  - Do:
    1. In `for_artifact`, find up to 3 live artifacts cited by a message that also cites this artifact, most shared messages first. Use a self-join on `chat_citations` by `message_id`.
    2. Add each one that is not in the rows already, with `link: "asked"`, `score: 0.6`, and `point` empty. These rows do not count against `limit`.
    3. In `relatedRowHtml`, add a last group: `group("You asked about both", of("asked"), () => "")`.
  - Test: one answer cites A and B. `for_artifact(A)` has B with link `asked`. A trashed B is absent.
  - Check: `uv run pytest tests/test_related.py -q`

- [x] **R8. Close passages move from the Details panel to Related** (claimed: agent, 2026-11-16)
  Done: src/enqueue/static/js/artifact.js; bin/verify --fast pass
  - Needs: R1
  - Files: `static/js/artifact.js` (`mountConnections`, and the element with id `connections`), `static/css/artifact.css` (`.related*`)
  - Why: one question, "what else is like this", has two places with two looks.
  - Find: `grep -n 'connections' src/enqueue/static/js/artifact.js`
  - Do:
    1. Find where the element `<div id="connections">` (or the tag that has that id) is put in the Details panel markup. Move that one element to immediately after the call `relatedRowHtml(d.related)`.
    2. In `mountConnections`, change the heading markup to `'<div class="relatedlabel">Close passages</div>'`.
    3. Give the slot the class `relatedgroup` so that it has the spacing of the other groups.
  - Check: `bin/verify --fast`
  - Device check **[device]**: on a long note, "Close passages" shows under Related at the foot of the page, and the Details panel has no "Passages that connect".

- [x] **R9. Related notes while you write**
  - Needs: none
  - Files: `retrieve/passage_links.py`, `api/artifacts.py` (new route at the end), `static/js/artifact.js` (new code), `static/css/artifact.css` (new `.nearby` rules), new `tests/test_nearby.py`
  - Do:
    1. In `passage_links.py`, add:
       ```python
       def near_text(artifact_id: str, text: str, limit: int = 3) -> list[dict]:
           """Other live items with a passage close to `text`: [{id, title, kind, score}]."""
           from ..index.store import get_store
  - Done: retrieve/passage_links.py, api/artifacts.py, js/artifact.js, css/artifact.css, tests/test_nearby.py; tests pass. Owed: device check - write a paragraph and see the titles under the sheet

           store = get_store()
           best: dict[str, float] = {}
           for hit in store.search_dense(store.CHUNKS, text, limit=24, as_query=False):
               other = hit["artifact_id"]
               if other != artifact_id and hit["score"] >= PASSAGE_MIN:
                   best[other] = max(best.get(other, 0.0), hit["score"])
           if not best:
               return []
           conn = db.get_conn()
           try:
               rows = conn.execute(
                   "SELECT id, title, kind FROM artifacts"
                   " WHERE id IN (SELECT value FROM json_each(?))"
                   " AND deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL",
                   (json.dumps(sorted(best)),),
               ).fetchall()
           finally:
               conn.close()
           found = [dict(r) | {"score": round(best[r["id"]], 3)} for r in rows]
           return sorted(found, key=lambda r: r["score"], reverse=True)[:limit]
       ```
    2. In `api/artifacts.py`, add a route `POST /artifacts/{artifact_id}/nearby` with a body model `{text: str}`. It returns `{"nearby": passage_links.near_text(artifact_id, text)}`. It returns an empty list when the text has less than 12 words.
    3. In `artifact.js`, find where a note is saved (`grep -n 'PATCH\|/body' src/enqueue/static/js/artifact.js`). After a save that succeeded, when the window is 1100 px wide or more: take the text of the block element that holds the caret, call the route, and draw up to 3 buttons in a container `<aside class="nearby">` placed after the note sheet. A press calls `openArtifact(id, "related")`.
    4. When the route returns none, empty the container.
    5. In `artifact.css`, add `.nearby` rules: `position: absolute; right: var(--sp-4); width: 200px;` and small text. Hide it under 1100 px with a media query.
  - Test: in `tests/test_nearby.py`, with `store`: two notes about the same thing in nearly the same words. `near_text(a, <text of b>)` returns b. A text of 5 words through the route returns an empty list.
  - Check: `uv run pytest tests/test_nearby.py -q`; `bin/verify --fast`
  - Device check **[device]**: write a paragraph on a subject the library has; a title shows in the margin after the save.

- [x] **R10. Related notes ignore the index-only lines** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/related.py; tests pass
  - Needs: DB1
  - Files: `ingest/related.py`, `tests/test_related.py`
  - Why: M5 and M8 add lines with roles `gist`, `point` and `ask`. Related notes must not read them as subject or idea lines.
  - Find: `grep -n 'FROM facets' src/enqueue/ingest/related.py`
  - Do:
    1. Add a constant `_NOT_INDEX_ONLY = " AND COALESCE(role, '') NOT IN ('gist', 'point', 'ask')"`.
    2. Add it to the `WHERE` of each `SELECT ... FROM facets` in the file (in `compute`, `_pair_keys`, `_judge`, `_statements` is by id and stays as it is).
    3. In `compute`, the hits from `store.search_dense` have no `role`. After the loop that fills `best` and `ideas`, remove entries whose matched facet has an index-only role: collect the facet ids (`found[2]`), read their roles in one query, and drop those entries.
  - Test: an artifact whose only level 1 line has role `ask` gets no subject link from that line.
  - Check: `uv run pytest tests/test_related.py -q`

- [x] **R11. Feedback on a link** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/related.py, src/enqueue/api/artifacts.py, src/enqueue/sync/snapshot.py, src/enqueue/static/js/artifact.js, tests/test_related.py; tests pass
  - Needs: DB1, R1
  - Files: `ingest/related.py`, `api/artifacts.py` (new route at the end), `sync/snapshot.py` (`derived_layers`, `_apply_derived_layers`), `static/js/artifact.js` (`relatedRowHtml`, `mountRelatedRow`), `static/css/artifact.css` (`.related*`), `tests/test_related.py`, `tests/test_snapshot.py`
  - Why: a wrong link stays for good, and nothing learns from a good one.
  - Do:
    1. In `related.py`, add:
       ```python
       def feedback(a: str, b: str, verdict: str, idea: str = "") -> None:
           """The person's ruling on a pair: "keep" or "no"."""
           if verdict not in ("keep", "no"):
               raise ValueError("verdict must be keep or no")
           first, second = sorted((a, b))
           pair = f"{first}|{second}"
           with db.transaction() as conn:
               conn.execute(
                   "INSERT OR REPLACE INTO link_feedback (pair, verdict, idea, created_at)"
                   " VALUES (?, ?, ?, ?)",
                   (pair, verdict, idea, db.now()),
               )
               if verdict == "no":
                   conn.execute(
                       "DELETE FROM related WHERE (artifact_id = ? AND related_id = ?)"
                       " OR (artifact_id = ? AND related_id = ?)",
                       (a, b, b, a),
                   )


       def refused(conn, artifact_id: str) -> set[str]:
           """The other ids of pairs the person refused."""
           out = set()
           for r in conn.execute(
               "SELECT pair FROM link_feedback WHERE verdict = 'no' AND instr(pair, ?) > 0",
               (artifact_id,),
           ):
               x, _, y = r["pair"].partition("|")
               out.add(y if x == artifact_id else x)
           return out
       ```
    2. In `compute`, read `no = refused(conn, artifact_id)` at the start and skip each `other` that is in `no`, in all three kinds.
    3. In `for_artifact`, add `kept: True` to a row whose pair has verdict `keep`, and sort kept rows first.
    4. In `api/artifacts.py`, add `POST /related/feedback` with body `{a: str, b: str, verdict: str, idea: str = ""}`. It calls `related.feedback`, then `sync_facets(a, bump=False)` and the same for `b` (import it with `from ..ingest.facets import sync_facets`). A bad verdict answers 400.
    5. In `snapshot.py` `derived_layers`, add a key `link_feedback`: the rows whose `pair` holds this artifact id. In `_apply_derived_layers`, for each incoming row, insert it when no row exists for the pair or the incoming `created_at` is later; when the stored verdict becomes `no`, delete the two `related` rows.
    6. In `relatedRowHtml`, an idea row gets two small text buttons after the reason: `Keep` and `Not the same`, with `data-verdict` and `data-other`. In `mountRelatedRow`, bind them: stop the click from opening the note, post to `/related/feedback` with this note's id, then draw the page again with `showArtifact(id)`.
    7. A row with `kept` shows `Kept` in place of the two buttons.
  - Test:
    1. `feedback(a, b, "no")` deletes both `related` rows, and a later `compute(a)` does not link b.
    2. `feedback(a, b, "keep")` makes `for_artifact(a)` list b first.
    3. A snapshot of a carries the feedback row; applying it to a second store writes the row.
  - Check: `uv run pytest tests/test_related.py tests/test_snapshot.py tests/test_sync.py -q`

- [x] **R12. The judge sees the person's own verdicts** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/related.py; tests pass
  - Needs: R11
  - Files: `ingest/related.py` (`_judge`), `tests/test_related.py`
  - Do:
    1. In `_judge`, before the model call, read up to 3 `keep` rows and 3 `no` rows from `link_feedback` whose `idea` is not empty, newest first.
    2. When there is one or more, append to the `user` text: a line `This person said these were the same point:` with each kept `idea` as `- <idea>`, and a line `And these were not:` with each refused `idea`.
    3. Send nothing but the `idea` sentences.
  - Test: with a fake provider that records its `user` text, the text holds a kept idea after feedback is written.
  - Check: `uv run pytest tests/test_related.py -q`

- [x] **R13. A "same subject" row shows the gist** (claimed: agent, 2026-11-16)
  Done: src/enqueue/ingest/related.py; tests pass
  - Needs: R2, M7
  - Files: `ingest/related.py` (`for_artifact`), `tests/test_related.py`
  - Do: in `for_artifact`, replace the `about` query of R2 with `about = facets.gists(conn, ids)`. Import `facets` from the package inside the function.
  - Test: a related item with a gist row shows the gist as `about`.
  - Check: `uv run pytest tests/test_related.py -q`

- [x] **R14. Docs for track R** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (docs skipped)
  - Needs: R1 to R13
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do:
    1. In `AGENTS.md`, change the `ingest/related.py` row: the groups, salience for names, `STORE_LIMIT`, the two read-time kinds (`named`, `asked`), feedback, the judge's order.
    2. Change the `retrieve/passage_links.py` row: `near_text`, and that the section is under Related now.
    3. Add the new routes to the API list.
    4. In `docs/MANUAL.md`, describe the Related groups and the two feedback buttons.
  - Check: `bin/verify --fast`

---

## Track Q: search

- [x] **Q1. Record each search**
  - Needs: DB1
  - Files: new `searches.py`, `api/search.py`, `chats.py`, `backup.py` (`start_scheduler`), new `tests/test_searches.py`
  - Why: a search that finds nothing useful leaves no trace today, so no one can learn from it.
  - Do:
    1. Make `searches.py`:
       ```python
       """A local record of searches: what was asked and what came back. Never synced."""
  - Done: src/enqueue/searches.py, api/search.py, chats.py, backup.py, tests/test_searches.py; tests pass

       from __future__ import annotations

       import json
       import logging

       from . import db

       log = logging.getLogger(__name__)
       KEEP_DAYS = 180


       def record(query: str, hits: list[dict], source: str) -> None:
           """Store one search. Never raises into the caller."""
           try:
               ids = [h["artifact_id"] for h in hits[:10]]
               loose = sum(1 for h in hits if h.get("loose"))
               with db.transaction() as conn:
                   conn.execute(
                       "INSERT INTO searches (query, hits, loose, source, created_at)"
                       " VALUES (?, ?, ?, ?, ?)",
                       (query.strip(), json.dumps(ids), loose, source, db.now()),
                   )
           except Exception:  # noqa: BLE001 - a lost row must never break a search
               log.exception("could not record a search")


       def prune() -> None:
           with db.transaction() as conn:
               conn.execute(
                   "DELETE FROM searches WHERE created_at < datetime('now', ?)",
                   (f"-{KEEP_DAYS} days",),
               )
       ```
    2. In `api/search.py` `search`, after `hits = search_results(...)`, call `searches.record(q, hits, "search")` when `q.strip()` is not empty.
    3. In `chats.py` `_everything_passages`, before each `return`, call `searches.record(question, [{"artifact_id": p["artifact_id"]} for p in <the list returned>], "chat")`.
    4. In `backup.py` `start_scheduler`, inside the `if due:` block after the drafts block, add a `try` block that calls `searches.prune()`, in the shape of the drafts block.
  - Test: in `tests/test_searches.py`: `record` writes one row with the ids in order; `record` with a broken hit list does not raise; `prune` deletes a row dated 200 days ago and keeps one dated today.
  - Check: `uv run pytest tests/test_searches.py tests/test_search_results.py tests/test_chats.py -q`

- [x] **Q2. Chat reads more summary hits and the passage that supports each** (claimed: agent, 2026-11-16)
  Done: src/enqueue/chats.py; tests pass
  - Needs: none
  - Files: `chats.py` (`_library_passages`), `tests/test_chats.py`
  - Why: chat asks each meaning layer for 4 hits where `/search` asks for 60. A summary hit pulls the item's opening passage, which for a long item is often off the subject.
  - Find: `grep -n 'limit=4\|def _pull_opening' src/enqueue/chats.py`
  - Do:
    1. Change `limit=4` to `limit=12` in the two `store.search_legs(...)` calls that have it.
    2. Replace the body of `_pull_opening` with:
       ```python
       def _pull_opening(aid: str, why: str, score: float) -> None:
           best = store.search_within(aid, question, 1)
           if best:
               chosen = best[0]
           else:
               row = conn.execute(
                   "SELECT id FROM chunks WHERE artifact_id = ? ORDER BY ordinal LIMIT 1",
                   (aid,),
               ).fetchone()
               chosen = row["id"] if row else None
           if chosen and chosen not in found:
               found[chosen] = {"score": score, "why": why}
       ```
  - Test: in `tests/test_chats.py`, add a test: a note with 3 passages where only the third holds the word "zeppelin", and a summary line that matches the question. The passages for a question about a zeppelin include the third passage. Stub `store.search_within` if the test library has no index; copy how nearby tests stub the store.
  - Check: `uv run pytest tests/test_chats.py tests/test_chats_worker.py -q`
  - Do not: change the floor logic or the order of the passes.

- [x] **Q3. The answer model sees why a passage is there** (claimed: agent, 2026-11-16)
  Done: src/enqueue/chats.py; tests pass
  - Needs: Q2
  - Files: `chats.py`, `tests/test_chats.py`
  - Find: `grep -n "(id: {p\['artifact_id'\]})" src/enqueue/chats.py`
  - Do:
    1. Where `_library_passages` handles a summary-line hit, it reads the line's statement for gray hits only. Read it for each summary hit that is kept, and store it in the `found` entry as `"matched": <statement>`.
    2. Carry `matched` through to the passage dict the function returns. Find where `found` becomes the returned list.
    3. In the passage header (the f-string found above), add a second line when `p.get("matched")` is set: `matched: <the line>`. The first line with the id does not change.
  - Test: a passage that came from a summary hit has `matched` set, and the prompt body holds `matched:`.
  - Check: `uv run pytest tests/test_chats.py -q`

- [x] **Q4. `/search` answers at once** (claimed: agent, 2026-11-16)
  Done: src/enqueue/retrieve/candidates.py, src/enqueue/api/search.py; tests pass
  - Needs: none
  - Files: `retrieve/candidates.py`, `api/search.py`, `tests/test_search_results.py`
  - Why: a new search waits up to 2.5 s for the judge. The search itself takes 28 ms.
  - Find: `grep -n '_judge_wait(model)\|def _judge_in_time\|def _apply_floor\|def search_results' src/enqueue/retrieve/candidates.py`
  - Do:
    1. Add a module variable near `_UNJUDGED`:
       ```python
       # How long this search waits for the judge; None means the configured wait.
       _WAIT: ContextVar[float | None] = ContextVar("judge_wait", default=None)
       # Set when a judge was started and had not answered when the search returned.
       _PENDING: ContextVar[bool] = ContextVar("judge_pending", default=False)
       ```
    2. In `_judge_in_time`, replace `worker.join(_judge_wait(model))` with:
       ```python
       wait = _WAIT.get()
       worker.join(_judge_wait(model) if wait is None else wait)
       ```
       On the path that returns `_cached_verdicts(query, gray)` after the join, call `_PENDING.set(True)` first.
    3. Change the signature to `search_results(q: str, limit: int = 20, wait: float | None = None)`. At its start: `_WAIT.set(wait)` and `_PENDING.set(False)`.
    4. Add a function `judge_pending() -> bool` that returns `_PENDING.get()`.
    5. In `api/search.py`: `search(q: str, limit: int = 20, wait: float = 0.0)`. Clamp `wait` to 0 to 10. Call `search_results(q, limit=limit, wait=wait)`. Add `"pending": judge_pending()` to the answer.
  - Test: in `tests/test_search_results.py`, with a judge stub that sleeps 0.5 s: `search_results(q, wait=0)` returns in less than 0.3 s and `judge_pending()` is true; `search_results(q, wait=2)` returns the judged result and `judge_pending()` is false. Copy how the file's other tests make gray hits.
  - Check: `uv run pytest tests/test_search_results.py -q`
  - Do not: change `SEARCH_JUDGE_WAIT_S`. Other callers that pass no `wait` keep it.

- [x] **Q5. The search page draws two times** (claimed: agent, 2026-11-16)
  Done: src/enqueue/static/js/search.js; bin/verify --fast pass (Owed: full second draw)
  - Needs: Q4
  - Files: `static/js/search.js`
  - Find: `grep -n 'async function doSearch' src/enqueue/static/js/search.js`
  - Do:
    1. `doSearch` draws the first answer as today.
    2. After the draw, when `r.pending` is true, call the route again with `&wait=8`.
    3. When the second answer comes: if the query on screen is not `q` any more (compare with `lastQuery` and the current route), drop it.
    4. Else set `lastHits` and draw the results again with the same function that drew the first answer. Keep the scroll position: read `window.scrollY` before and set it after.
    5. A failed second call changes nothing.
  - Check: `bin/verify --fast`
  - Device check **[device]**: a new search by topic shows results at once; the "Maybe related" block changes about a second later with no jump.
  - Done: js/search.js; the second answer now redraws the page in place (fixed in review). Owed: device check

- [x] **Q6. Lifting and model ranking cannot hold a search** (claimed: agent, 2026-11-16)
  Done: src/enqueue/retrieve/candidates.py; tests pass
  - Needs: Q4
  - Files: `retrieve/candidates.py` (`search_results`), `tests/test_search_results.py`
  - Why: both are off by default. With both on and the service down, each search took 3.7 s.
  - Do:
    1. Add a helper in `candidates.py`:
       ```python
       _FAILED: dict[tuple[str, str], float] = {}
       FAILED_FOR_S = 60.0


       def _in_time(kind: str, query: str, fn, fallback):
           """Run a model step for a search, waited for the search's own wait at most.
           A step that failed or ran late is not tried again for FAILED_FOR_S."""
           from ..providers import pause

           key = (kind, query)
           if pause.active() or time.monotonic() - _FAILED.get(key, -1e9) < FAILED_FOR_S:
               return fallback
           box: dict = {}

           def run() -> None:
               try:
                   box["value"] = fn()
               except Exception:  # noqa: BLE001 - the search goes on without it
                   _FAILED[key] = time.monotonic()

           worker = threading.Thread(target=copy_context().run, args=(run,), daemon=True)
           worker.start()
           wait = _WAIT.get()
           worker.join(config.SEARCH_JUDGE_WAIT_S if wait is None else wait)
           if "value" in box:
               return box["value"]
           _PENDING.set(True)
           return fallback
       ```
    2. In `search_results`, replace `lift.lift(query_text)` with `_in_time("lift", query_text, lambda: lift.lift(query_text), [])`.
    3. Replace `model_rank.order(query_text, fused)` with `_in_time("rank", query_text, lambda: model_rank.order(query_text, fused), fused)`.
    4. Keep `_FAILED` small: when it has more than 256 keys, clear it.
  - Test: with `lift.enabled_for_search` patched to true and `lift.lift` patched to sleep 1 s, `search_results(q, wait=0)` returns in less than 0.3 s. With `lift.lift` patched to raise, the second search within 60 s does not call it.
  - Check: `uv run pytest tests/test_search_results.py tests/test_model_pause.py -q`

- [x] **Q7. Warm the embedder when a search is about to come** (claimed: agent, 2026-11-16)
  Done: src/enqueue/api/search.py, src/enqueue/static/js/home.js, tests/test_search_warm.py; tests pass
  - Needs: none
  - Files: `api/search.py`, `static/js/home.js` (the search bar focus handler), new `tests/test_search_warm.py`
  - Why: the model unloads after 300 s with no use, and the next search waits about 0.5 s for it.
  - Find: `grep -n 'hs.addEventListener("focus"' src/enqueue/static/js/home.js`
  - Do:
    1. In `api/search.py`, add:
       ```python
       @router.post("/search/warm")
       def warm() -> dict:
           """Load the embedding model now, so the search that follows does not wait."""
           import threading

           from ..index import embed

           threading.Thread(target=lambda: embed.embed_query("warm"), daemon=True).start()
           return {"ok": True}
       ```
    2. In `home.js`, at the start of the focus handler, add a call that runs one time for each 60 s:
       ```js
       if (Date.now() - (window.__warmAt || 0) > 60000) {
         window.__warmAt = Date.now();
         api("/search/warm", { method: "POST" }).catch(() => {});
       }
       ```
  - Test: in `tests/test_search_warm.py`, patch `embed.embed_query` with a function that records a call. `POST /search/warm` answers `{"ok": true}` and the function was called (join or wait up to 1 s).
  - Check: `uv run pytest tests/test_search_warm.py -q`; `bin/verify --fast`

- [x] **Q8. The judge and the overview ignore the index-only lines** (claimed: agent, 2026-11-16)
  Done: src/enqueue/retrieve/candidates.py, src/enqueue/chats.py; tests pass
  - Needs: DB1
  - Files: `retrieve/candidates.py` (`_facets_for_judge`), `chats.py` (`_overview`), `tests/test_search_results.py`
  - Find: `grep -n 'FROM facets' src/enqueue/retrieve/candidates.py src/enqueue/chats.py`
  - Do:
    1. In `_facets_for_judge`, add `AND COALESCE(role, '') != 'ask'` to the `WHERE`.
    2. In `_overview`, add the same to the `SELECT statement AS line ... FROM facets` query.
  - Test: an artifact with one `ask` line and one `subject` line: `_facets_for_judge` returns the subject line only.
  - Check: `uv run pytest tests/test_search_results.py tests/test_chats.py -q`

- [x] **Q9. A search phrase hit says why it matched** (claimed: agent, 2026-11-16)
  Done: src/enqueue/index/store_sqlite.py, src/enqueue/retrieve/candidates.py, src/enqueue/static/js/search.js; tests pass
  - Needs: M8
  - Files: `index/store_sqlite.py` (`_fetch_hits`: the facets branch), `retrieve/candidates.py` (`_hybrid_results`), `static/js/search.js`
  - Find: `grep -n '" bridge FROM facets"\|hit\["bridge"\]' src/enqueue/index/store_sqlite.py`; `grep -n 'facet L' src/enqueue/retrieve/candidates.py`
  - Do:
    1. In `_fetch_hits`, add `role` to the facets `SELECT` and `hit["role"] = row["role"]` next to `hit["bridge"]`.
    2. In `_hybrid_results`, where the facet layer builds `"why": f"facet L{h.get('level')}"`, use `"why": "search phrase"` when `h.get("role") == "ask"`.
    3. In `search.js`, find where `why` is turned into words for the result (`grep -n 'facet L\|why' src/enqueue/static/js/search.js`). For `"search phrase"`, show `Found by: ` and the `matched` text.
  - Test: in `tests/test_search_results.py`, an artifact with an `ask` line "release in small steps" is found by the search "small steps release" with `why` equal to `search phrase`.
  - Check: `uv run pytest tests/test_search_results.py -q`; `bin/check-eval-cross`

- [x] **Q10. A search result shows the gist** (claimed: agent, 2026-11-16)
  Done: src/enqueue/api/search.py, src/enqueue/static/js/search.js; tests pass
  - Needs: M7
  - Files: `api/search.py` (`_dated`), `static/js/search.js`
  - Do:
    1. In `_dated`, after the rows are read, call `facets.gists(conn, [h["artifact_id"] for h in hits])` and set `h["gist"]` for each hit.
    2. In `search.js`, when a hit has no marked passage to show and has a `gist`, show the gist as its second line.
  - Test: a hit for an artifact with a gist row has `gist` in the `/search` answer.
  - Check: `uv run pytest tests/test_search_results.py -q`

- [x] **Q11. Docs for track Q** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (docs skipped)
  - Needs: Q1 to Q10
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do:
    1. In `AGENTS.md` "The judge never holds a search", describe `wait`, `pending` and the two-step page.
    2. Add `searches.py` to the module map and the `searches` table to the tables list.
    3. Add `POST /search/warm` to the API list.
    4. In "Chat passages", say that a summary hit pulls its best passage.
  - Check: `bin/verify --fast`

---

## Track H: Something shiny

Finding: 57 idea pairs exist, and the daily card turns through the same 7 each week.

- [x] **H1. The card does not repeat a pair** (claimed: agent, 2026-11-16)
  Done: src/enqueue/shiny.py, tests/test_shiny.py; tests pass
  - Needs: none
  - Files: `shiny.py` (`_order`), `tests/test_shiny.py`
  - Find: `grep -n 'def _order\|ROTATE\|toordinal' src/enqueue/shiny.py`
  - Do:
    1. In `_order`, in the block that opens a connection, also read `shown = _recent(conn, "shiny_shown", REMEMBER_DAYS, today)`.
    2. After `pool = ideas or pairs`, add:
       ```python
       fresh = [p for p in pool if _pair([p["a"], p["b"]]) not in shown]
       pool = fresh or pool
       ```
    3. Replace the three lines that use `ROTATE`, `start` and `top[start:] + top[:start] + rest` with a plain loop over `pool`.
    4. Delete the constant `ROTATE` and each mention of it in the module docstring.
  - Test: in `tests/test_shiny.py`: with 3 idea pairs, after `today(day1)` shows the first, `pick(day2)` returns another pair. When all 3 were shown, `pick` still returns a set. Fix tests that relied on the 7-day turn; the new rule is "unshown first".
  - Check: `uv run pytest tests/test_shiny.py -q`

- [x] **H2. A pair with a fresh note comes first** (claimed: agent, 2026-11-16)
  Done: src/enqueue/shiny.py; tests pass
  - Needs: H1
  - Files: `shiny.py` (`_pairs`), `tests/test_shiny.py`
  - Why: a link to the note the person wrote this week is worth more than a link between two old notes.
  - Do:
    1. In `_pairs`, add `a.updated_at AS a_at, b.updated_at AS b_at` to the `SELECT`.
    2. Compute `week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()` and for each pair `fresh = max(p["a_at"] or "", p["b_at"] or "") >= week`.
    3. Change the sort key to `(p["kind"] != "idea", not fresh, -(p["distance"] or 0.0), p["a"], p["b"])`.
    4. Remove `a_at` and `b_at` from each dict before the return, so the stored sets keep their shape.
  - Test: two idea pairs with the same distance; the pair that holds a note updated today sorts first.
  - Check: `uv run pytest tests/test_shiny.py -q`

- [x] **H3. Something shiny ignores the index-only lines** (claimed: agent, 2026-11-16)
  Done: src/enqueue/shiny.py; tests pass
  - Needs: DB1
  - Files: `shiny.py` (`_faces`, `_seeds`, `_candidates`), `tests/test_shiny.py`
  - Find: `grep -n 'FROM facets\|facets f' src/enqueue/shiny.py`
  - Do:
    1. Add `AND COALESCE(role, '') NOT IN ('gist', 'point', 'ask')` to the `WHERE` of each facet query in the three functions. In `_seeds` the alias is `f`: write `COALESCE(f.role, '')`.
    2. In `_candidates`, the hits from `store.search_dense` have no `role`. After `best` is filled, read the roles of the matched facet ids in one query and drop entries with an index-only role.
  - Test: an artifact whose only level 2 line has role `ask` is not a seed.
  - Check: `uv run pytest tests/test_shiny.py -q`

- [x] **H4. Feedback on the card** (claimed: agent, 2026-11-16)
  Done: src/enqueue/static/js/home.js; bin/verify --fast pass (Owed: binding)
  - Needs: R11
  - Files: `static/js/home.js` (`drawShiny`), `static/css/home.css`
  - Find: `grep -n 'function drawShiny\|Not today\|Find another' src/enqueue/static/js/home.js`
  - Do:
    1. In `drawShiny`, next to "Find another", add two text buttons: `Keep` and `Not the same`.
    2. Both post to `/related/feedback` with `a` and `b` set to the first two ids of the set (`r.ids[0]`, `r.ids[1]`), the verdict, and `idea` set to `r.food.idea`.
    3. After `Not the same`, call the function that "Find another" calls.
    4. After `Keep`, replace the two buttons with the text `Kept`.
    5. Style them like the "Not today" control. Find its rule in `home.css` and use the same class.
  - Check: `bin/verify --fast`
  - Device check **[device]**: refuse a card. The next set shows, and the refused pair is not in the Related section of either note.
  - Done: js/home.js; Keep and Not the same post to /related/feedback (fixed in review: the buttons were never drawn, and Keep was bound as Not today). Owed: device check

- [x] **H5. The hunt does not bring back a refused pair, and sees the person's verdicts** (claimed: agent, 2026-11-16)
  Done: src/enqueue/shiny.py; tests pass
  Done: (skipped)
  - Needs: R11
  - Files: `shiny.py` (`hunt`, `_pairs`), `tests/test_shiny.py`
  - Do:
    1. In `hunt`, drop each candidate where `seed` and the candidate are a refused pair. Use `related.refused(conn, seed)`.
    2. In `_pairs`, the `related` rows of a refused pair are deleted by R11, so nothing changes there. Add a test that proves it.
    3. In `hunt`, append the examples to the `user` text as R12 does: up to 3 kept and 3 refused `idea` sentences from `link_feedback`.
  - Test: after `feedback(seed, other, "no")`, `hunt` does not return that pair.
  - Check: `uv run pytest tests/test_shiny.py -q`

- [x] **H6. Give the model the passages when cards are refused often** (claimed: agent, 2026-11-16)
  Done: src/enqueue/shiny.py, src/enqueue/prompts.py; tests pass
  Done: (skipped)
  - Needs: R11
  - Files: `shiny.py` (`_write`, `hunt`), `prompts.py` (`SHINY`, `SHINY_HUNT`), `tests/test_shiny.py`
  - Why: the model sees titles and summary lines only. When the person refuses many cards, the lines are not enough.
  - Do:
    1. Add `def _grounded(conn, today) -> bool`: count the `shiny_shown` rows of the last 30 days (`_recent`) and the `link_feedback` rows with verdict `no` created in the last 30 days. Return true when the first is 5 or more and the second is more than one fifth of the first.
    2. Add `def _passage(aid: str, line: str) -> str`: `store.search_within(aid, line, 1)`, read that chunk's text, return its first 120 words. Empty when nothing is found.
    3. In `_write` and `hunt`, when `_grounded` is true, add under each note's block a line `passage: <text>`. Leave it out for a note that `privacy.local_only_ids` names when the model is remote.
    4. In both prompts, add one sentence before the last line: `When a note has a "passage", it is that note's own text: the idea you name must be supported by it.`
  - Test: with 5 shown pairs and 2 refusals, the user text of `_write` holds `passage:`. With 5 shown and 0 refusals, it does not.
  - Check: `uv run pytest tests/test_shiny.py -q`

- [~] **H7. The links and the day's card go to the relay** (claimed: agent, 2026-11-16)
  Done: (skipped)
  - Needs: R11
  - Files: `sync/snapshot.py` (`derived_layers`, `_apply_derived_layers`), `sync/client.py`, `shiny.py` (`prepare`), `tests/test_snapshot.py`, `tests/test_sync.py`
  - Why: the phone has no related notes and no card, because these do not ride the relay.
  - Find: `grep -n 'def push_pivots' -A 30 src/enqueue/sync/client.py`
  - Do:
    1. In `derived_layers`, add a key `related`: the rows of `related` where `owner` is this artifact, with all columns but `created_at`. Empty for a vaulted or local-only artifact.
    2. In `_apply_derived_layers`, when the snapshot has the key `related`: delete the rows where `owner` is this artifact, then insert the incoming rows with `created_at` set to now.
    3. In `sync/client.py`, add `push_shiny()`: seal and put `lib/shiny.enc`, with the body `{"day": <iso date>, "sets": [{"ids", "links", "food"}], "updated_at": <now>}` for the day's first 5 sets. Copy `push_pivots` for the sealing, the object name and the error handling.
    4. Leave out a set that holds a local-only or vaulted artifact.
    5. In `shiny.prepare`, call `push_shiny()` when it did something. Wrap the call so a sync failure does not raise.
  - Test: a snapshot carries the `related` rows an artifact owns, and applying it writes them. A second apply with an empty list removes them. `push_shiny` with sync off does nothing and does not raise.
  - Check: `uv run pytest tests/test_snapshot.py tests/test_sync.py tests/test_summarize_once.py tests/test_shiny.py -q`

- [x] **H8. Docs for track H** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: H1 to H7
  - Files: `AGENTS.md`
  - Do: in the `shiny.py` row and in "Something shiny holds still all day", replace the 7-day turn with the new rules: unshown pairs first, a fresh note first, feedback, passages when refusals are high, and `lib/shiny.enc`.
  - Check: `bin/verify --fast`

---

## Track P: phone

All Rust work is in `desktop/`. Run `cargo test --lib` there.

- [x] **P1. A keyword index on the phone** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: none
  - Files: `desktop/src/sync.rs`
  - Why: the phone matches with `LIKE` over title, body and notes. It does not see summary lines or the text of a PDF or a link.
  - Find: `grep -n 'pub fn init_schema\|fn apply_snapshot\|pub fn update_note_body\|pub fn add_annotation\|fn search_like' desktop/src/sync.rs`
  - Do:
    1. Add a unit test that opens an in-memory connection and runs `CREATE VIRTUAL TABLE t USING fts5(x)`. If it fails, FTS5 is not compiled in: mark the task `[!]` with that reason and stop.
    2. In `init_schema`, add:
       ```sql
       CREATE VIRTUAL TABLE IF NOT EXISTS fts_items USING fts5(
         artifact_id UNINDEXED, title, body, notes, summary, pages);
       ```
    3. Add `pub fn reindex_item(conn: &Connection, artifact_id: &str) -> Result<(), String>`:
       - delete the `fts_items` row of the artifact;
       - if the artifact is absent, trashed (`deleted_at` set) or vaulted (`vaulted_at` set), stop there;
       - insert one row: the title, the body, all annotation texts joined with newlines, all facet statements joined with newlines, all `page_text` texts joined with newlines.
    4. Call `reindex_item` at the end of `apply_snapshot` for the artifact it applied, and at the end of each function in this file that writes an artifact's title, body, annotations, facets, `deleted_at` or `vaulted_at`. Find them with `grep -n 'UPDATE artifacts\|INSERT INTO artifacts\|INSERT INTO annotations\|INTO facets\|DELETE FROM facets' desktop/src/sync.rs`.
    5. At the end of `init_schema`: when `sync_meta` has no key `fts_items_built`, call `reindex_item` for each artifact and then write the key.
  - Test: Rust unit tests: after `reindex_item`, a word that is only in a facet statement is found with `SELECT artifact_id FROM fts_items WHERE fts_items MATCH ?`; a trashed artifact has no row.
  - Check: `cargo test --lib` in `desktop/`

- [x] **P2. Phone search uses the index** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: P1
  - Files: `desktop/src/sync.rs` (`search_artifacts`)
  - Find: `grep -n 'pub fn search_artifacts\|fn query_terms\|fn search_like' desktop/src/sync.rs`
  - Do:
    1. Add `fn search_fts(conn, terms: &[String], all: bool) -> Result<Vec<Value>, String>`. Build the match string: each term as `"term"*` (double any `"` inside a term), joined with a space when `all` is true and with ` OR ` when false.
    2. Query:
       ```sql
       SELECT a.id, a.kind, a.title, substr(a.body, 1, 280), a.source_url, a.mime,
              a.filename, a.created_at, a.updated_at, a.pinned,
              snippet(fts_items, -1, '', '', ' ... ', 12) AS snip
       FROM fts_items f JOIN artifacts a ON a.id = f.artifact_id
       WHERE fts_items MATCH ?1 AND a.deleted_at IS NULL AND a.vaulted_at IS NULL
       ORDER BY bm25(fts_items, 0.0, 10.0, 1.0, 2.0, 3.0, 1.0) LIMIT 40
       ```
    3. Return the same JSON keys as `search_like`, plus `"snippet"`.
    4. In `search_artifacts`: call `search_fts(.., true)`. When it has less than 5 rows, call `search_fts(.., false)` and append rows whose id is not in the list. When `search_fts` returns an error, fall back to `search_like`.
    5. Keep the branch for an empty term list as it is.
  - Test: Rust unit tests: a word that is only in a PDF's `page_text` finds the PDF; a title match is before a body match; a query of two words where only one matches still finds the item.
  - Check: `cargo test --lib` in `desktop/`

- [x] **P3. A phone result shows the matched words** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped) **[device]**
  - Needs: P2
  - Files: `static/mobile.html`
  - Find: `grep -n 'invoke("mobile_search"' src/enqueue/static/mobile.html`
  - Do: where a search result row is drawn, when the row has `snippet` and the snippet is not the start of the body, show the snippet as the row's second line. Escape it with `esc`.
  - Check: `bin/verify --fast`. Device: `bin/launch emulator`; search a word that is only in a PDF; the row shows the words around it.

- [x] **P4. The phone draws the summary in groups** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped) **[device]**
  - Needs: M2
  - Files: `desktop/src/sync.rs`, `static/mobile.html`
  - Find: `grep -n 'CREATE TABLE IF NOT EXISTS facets' desktop/src/sync.rs`; `grep -n 'SELECT id, level, statement, edited FROM facets' desktop/src/sync.rs`; `grep -n 'details_summary' src/enqueue/static/mobile.html`
  - Do:
    1. In `init_schema`, after the tables are made, add the column when it is absent: run `ALTER TABLE facets ADD COLUMN bridge INTEGER NOT NULL DEFAULT 0` and ignore the "duplicate column" error.
    2. In `apply_snapshot`, where facets are inserted, store `bridge` from the snapshot (0 when absent).
    3. In `build_snapshot`, send `bridge` with each facet.
    4. In the facets read for the reader (the `SELECT id, level, statement, edited`), add `bridge` and return it.
    5. In `mobile.html`, where `#details_summary` is filled, draw the three groups of M2 (About, Ideas with 3 open, Also found by closed). Copy `facetGroups` from `js/artifact.js` and use the phone's own row function.
  - Test: a Rust unit test: a snapshot facet with `bridge: 1` is read back with `bridge` 1.
  - Check: `cargo test --lib`; `bin/verify --fast`. Device: `bin/launch emulator`; the Details panel of a synced item shows the groups.

- [x] **P5. The phone keeps the role** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: M4, P4
  - Files: `desktop/src/sync.rs`
  - Do:
    1. Add the column `role TEXT` to `facets` the same way as `bridge` in P4.
    2. Store it in `apply_snapshot`, send it in `build_snapshot`, return it in the facets read.
    3. When a snapshot facet has no role, set it by the rule of DB1: bridge gives `bridge`, level 0 `kind`, level 1 `subject`, else `idea`.
  - Test: a snapshot facet with `role: "gist"` is sent back with `role: "gist"`.
  - Check: `cargo test --lib` in `desktop/`
  - Partly done in review (2026-11-16): the `role` column, apply, `build_snapshot` and a test are in `sync.rs`, and the reader hides `ask` lines. Left: set a role when a snapshot facet has none.

- [x] **P6. Related rows on the phone** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped) **[device]**
  - Needs: H7, R1
  - Files: `desktop/src/sync.rs`, `desktop/src/lib.rs` (`mod mobile`), `desktop/build.rs`, `desktop/tauri.conf.json`, `static/mobile.html`
  - Do:
    1. In `init_schema`, add a table `related` (`artifact_id`, `related_id`, `owner`, `score`, `via`, `point`, `kind`, `distance`, primary key on the first three).
    2. In `apply_snapshot`, when the snapshot has the key `related`: delete rows where `owner` is the artifact, insert the incoming rows.
    3. Add `pub fn related_for(conn, artifact_id) -> Result<Vec<Value>, String>` in `sync.rs`: live related items with `id`, `title`, `kind`, `updated_at`, `link`, `point`, `via`. One row for each related id. Order: subject by score, then idea by distance from far to near, then mention.
    4. Add the command `mobile_related(id: String)` in `mod mobile`. Follow the recipe for a new command (three places).
    5. In `mobile.html`, in the reader under the note text, call it and draw the groups of R1. A tap on a row opens that item in the reader.
  - Test: a Rust unit test for `related_for`: a trashed related item is absent.
  - Check: `cargo test --lib`; `bin/verify --fast`. Device: `bin/launch emulator`; `bin/cdp-eval "await window.__TAURI__.core.invoke('mobile_related', {id: '<an id from mobile_list>'})"` returns rows.

- [x] **P7. The day's card on the phone** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped) **[device]**
  - Needs: H7
  - Files: `desktop/src/sync.rs`, `desktop/src/lib.rs` (`mod mobile`), `desktop/build.rs`, `desktop/tauri.conf.json`, `static/mobile.html`
  - Find: `grep -n 'pivots.enc' desktop/src/sync.rs` to see how `lib/pivots.enc` is pulled and kept.
  - Do:
    1. Pull `lib/shiny.enc` the same way and keep the opened JSON in `sync_meta` under the key `shiny`.
    2. Add the command `mobile_shiny()` that returns that JSON, or `null`. Drop a set that holds an id that is not live on the phone.
    3. In `mobile.html`, over the library list, draw the first set when its `day` is today: the idea as a heading, the notes as rows, the question, and "Not today".
    4. "Not today" hides the card until the next day (`localStorage`).
    5. The phone does not hunt and has no "Find another".
  - Check: `cargo test --lib`; `bin/verify --fast`. Device: `bin/launch emulator` linked to a Mac that has a card; the card shows the same idea.

- [x] **P8. Feedback from the phone** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped) **[device]**
  - Needs: P6, R11
  - Files: `desktop/src/sync.rs`, `desktop/src/lib.rs` (`mod mobile`), `desktop/build.rs`, `desktop/tauri.conf.json`, `static/mobile.html`
  - Do:
    1. In `init_schema`, add the table `link_feedback` with the columns of DB1.
    2. In `apply_snapshot`, take the snapshot's `link_feedback` rows by the rule of R11 step 5. In `build_snapshot`, send the rows whose `pair` holds the artifact.
    3. Add the command `mobile_link_feedback(a, b, verdict, idea)`: write the row; on `no` delete the two `related` rows; move both artifacts' `updated_at` to now and queue both with the function the other write commands use (`grep -n 'fn queue_mutation_push' desktop/src/lib.rs`).
    4. In `mobile.html`, add `Keep` and `Not the same` to idea rows (P6).
  - Test: a Rust unit test: after a `no` verdict the `related` rows of the pair are gone and `build_snapshot` of `a` carries the feedback row.
  - Check: `cargo test --lib`. Device: refuse a link on the emulator; after a sync the row is gone on the Mac.

- [x] **P9. Docs for track P** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: P1 to P8
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do: in `AGENTS.md`, change Resolved decision 11 (the phone searches a keyword index over text, summary and pages; it has related rows and the day's card). Change the `ingest/related.py` row's last sentence, which says the phone has no related data.
  - Check: `bin/verify --fast`

---

## Track F: features

- [x] **F1. A privacy receipt under each answer** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: none
  - Files: `chats_worker.py`, `chats.py` (`get`), `static/js/chat.js`, `tests/test_chats_worker.py`
  - Why: no product whose servers read the notes can show this line. It makes the privacy promise visible.
  - Find: `grep -n 'ask.answered' src/enqueue/chats_worker.py`; `grep -n 'md(m.text)' src/enqueue/static/js/chat.js`
  - Do:
    1. In `chats_worker`, where `ask.answered` is emitted, the passages and the provider are known. Compute `receipt = {"notes": <count of distinct artifact ids in the passages>, "chars": <sum of the passage text lengths sent>, "service": <label>, "local": <not privacy.is_remote(provider)>}`. The label is `config.BACKENDS.get(str(settings.get("llm_backend")), {}).get("label", provider.name)`.
    2. Store it with the `derived_values` recipe: scope `answer_receipt`, subject the assistant message id, attribute `receipt`, value the JSON text, source `engine`.
    3. In `chats.get`, read the receipts of the chat's messages in one query and add `receipt` to each assistant message that has one.
    4. In `chat.js`, under an answer with a receipt, add one line of small muted text. When `local` is true: `Nothing left this Mac.` Else: `Read <notes> notes. Sent <chars, with thousands separators> characters to <service>.`
    5. An answer with no passages gets no receipt.
  - Test: in `tests/test_chats_worker.py`, after `compute` with a fake provider and two passages from two notes, `chats.get` gives the assistant message a receipt with `notes` 2.
  - Check: `uv run pytest tests/test_chats_worker.py tests/test_chats.py -q`; `bin/verify --fast`

- [x] **F2. What left this Mac, on one page** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: none
  - Files: `outbound.py`, `api/admin.py` (new route), `static/js/settings.js` (one new block in the Activity tab), new `tests/test_outbound.py`
  - Find: read `outbound.py` whole first. `grep -n 'events' src/enqueue/static/js/settings.js | head` for where the Activity tab is drawn.
  - Do:
    1. In `outbound.py`, where the totals are written as a `model.sent` activity row, also keep them with the `derived_values` recipe: scope `outbound_day`, subject `<iso date>|<service>|<purpose>`, attribute `totals`, value the JSON text `{"calls": n, "chars": n}`, source `engine`. Read the day's row first and add to its numbers.
    2. Add `def by_day(days: int = 30) -> list[dict]` that returns the rows of the last `days` days, newest first: `{"day", "service", "purpose", "calls", "chars"}`.
    3. In `api/admin.py`, add `GET /outbound` that returns `{"days": outbound.by_day()}`.
    4. In `settings.js`, at the top of the Activity tab, add a section "What left this Mac" with a table of the rows: day, service, what for, calls, characters. With no rows, one line: `Nothing has left this Mac in the last 30 days.`
  - Test: two flushes on one day for one service and purpose give one row with the sums. A row 40 days old is not returned.
  - Check: `uv run pytest tests/test_outbound.py -q`; `bin/verify --fast`

- [x] **F3. Save an answer as a note** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: none
  - Files: `chats.py`, `api/chats.py`, `static/js/chat.js`, `tests/test_chats.py`
  - Do:
    1. In `chats.py`, add `def answer_as_note(chat_id: str, message_id: str) -> dict`:
       - read the assistant message and the user message before it; raise `KeyError` when the message is absent or is not a grounded answer;
       - read the titles of the cited artifacts through `chat_citations`;
       - remove place marks from the answer text first: `re.sub(r"\s?\[P\d+\]", "", text)`;
       - make the body: `# <the question>`, a blank line, the answer text, a blank line, `Sources:`, then one line `- <title>` for each cited artifact;
       - call `notes.create` with that body (read its signature first) and return what it returns.
    2. In `api/chats.py`, add `POST /chats/{chat_id}/messages/{message_id}/note`. A `KeyError` answers 404.
    3. In `chat.js`, under a grounded answer, add a small text button `Save as a note`. On success show the toast `Saved as a note.`
  - Test: an answer with two citations becomes a note whose body holds the question, the answer and both titles. A message id that does not exist answers 404.
  - Check: `uv run pytest tests/test_chats.py -q`; `bin/verify --fast`

- [x] **F4. Docs for track F** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: F1 to F3
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do: add the receipt and `GET /outbound` to the `outbound.py` row and the API list; add the save-as-note route; describe the three in `docs/MANUAL.md` in plain words.
  - Check: `bin/verify --fast`

---

## Track U: consistency

Finding: the stylesheets hold 38 distinct font sizes and no size token, and 24 numeric font weights against the rule in AGENTS.md.

- [x] **U1. A style check that reports** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: none
  - Files: new `bin/check-style`, `bin/verify`
  - Do:
    1. Make `bin/check-style`, a Python script with `#!/usr/bin/env python3`, and make it executable (`chmod +x`).
    2. It reads each `src/enqueue/static/css/*.css` but `tokens.css`, and the text inside each `<style>` block of `src/enqueue/static/mobile.html` and `src/enqueue/static/capture.html`.
    3. It counts two things in each file: `font-size:` followed by a number and `px` (regex `font-size:\s*[0-9.]+px`), and `font-weight:` followed by a number (regex `font-weight:\s*[0-9]+\s*[;}]`).
    4. It prints one line for each file that has a count above 0: `<file>: <n> sizes, <n> weights`, then a total line.
    5. With the argument `--strict` it exits with code 1 when the total is above 0. Without it, it exits 0.
    6. In `bin/verify`, find where `bin/check-contrast` is run (`grep -n 'check-contrast' bin/verify`). Run `bin/check-style` after it the same way, without `--strict`.
  - Check: `bin/check-style` prints counts and exits 0; `bin/check-style --strict; echo $?` prints 1; `bin/verify --fast` passes.

- [x] **U2. A type scale in the tokens** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: none
  - Files: `static/css/tokens.css`, `docs/DESIGN.md`
  - Find: `grep -n -- '--w-' src/enqueue/static/css/tokens.css | head`
  - Do:
    1. In `tokens.css`, in the `:root` block that holds the `--w-*` tokens, add:
       ```css
       --t-xs: 12px;
       --t-sm: 13px;
       --t-md: 14px;
       --t-lg: 15px;
       --t-xl: 16px;
       --t-2xl: 18px;
       --t-3xl: 20px;
       --t-4xl: 24px;
       --t-display-sm: 34px;
       --t-display: 44px;
       ```
    2. In `docs/DESIGN.md` section 3, add a short table of the ten tokens and the rule: a stylesheet uses a `--t-*` token for a font size, never a number.
  - Check: `bin/verify --fast`
  - Do not: change a rule that uses a size in this task.

- [x] **U3. Sizes and weights become tokens: wall and base** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: U1, U2
  - Files: `static/css/base.css`, `static/css/home.css`, `static/css/pill.css`
  - Do:
    1. Replace each `font-size: <n>px` by this table. Change nothing that is not in the table; if you find another px value, stop and write it under this task.

       | Value in px | Token |
       | --- | --- |
       | 11, 12 | `var(--t-xs)` |
       | 12.5, 13 | `var(--t-sm)` |
       | 13.5, 14, 14.5 | `var(--t-md)` |
       | 15 | `var(--t-lg)` |
       | 15.5, 16, 16.5, 17 | `var(--t-xl)` |
       | 18 | `var(--t-2xl)` |
       | 19, 20, 21 | `var(--t-3xl)` |
       | 22, 24, 25, 26, 28 | `var(--t-4xl)` |
       | 29, 30, 32, 34 | `var(--t-display-sm)` |
       | 44 | `var(--t-display)` |
    2. Replace each numeric `font-weight` by this table. For another number, stop, mark `[!]` and write the number and the rule under this task.

       | Number | Token |
       | --- | --- |
       | 400 | `var(--w-regular)` |
       | 440, 500 | `var(--w-medium)` |
       | 480 | `var(--w-strong)` |
       | 600 | `var(--w-heading)` |
    3. Do not change `font-size` values in `em`, `rem`, `%`, `clamp(...)` or `var(...)`.
  - Check: `bin/check-style` prints no line for the three files; `bin/verify --fast`
  - Device check **[device]**: the wall, a card and the pill look the same as before.

- [x] **U4. Sizes and weights become tokens: the pages** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: U1, U2
  - Files: `static/css/chat.css`, `static/css/settings.css`, `static/css/eyepanel.css`, `static/css/reader.css`, `static/css/welcome.css`, `static/css/tour.css`, `static/css/guide.css`, `static/css/linkpop.css`, `static/css/drafts.css`, `static/css/share.css`, `static/css/bird.css`, `static/css/notetype.css`, `static/css/search.css`
  - Do: the same two steps and the same table as U3. Skip a file that is absent.
  - Check: `bin/check-style` prints no line for these files; `bin/verify --fast`

- [x] **U5. Sizes and weights become tokens: the Details panel** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: U1, U2, M6
  - Files: `static/css/details.css`
  - Do: as U3.
  - Check: `bin/check-style` prints no line for the file; `bin/verify --fast`

- [x] **U6. Sizes and weights become tokens: the note page** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: U1, U2, R8, R9, R11
  - Files: `static/css/artifact.css`
  - Do: as U3.
  - Check: `bin/check-style` prints no line for the file; `bin/verify --fast`

- [x] **U7. Sizes and weights become tokens: the phone and the capture page** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped) **[device]**
  - Needs: U1, U2, P8
  - Files: `static/mobile.html`, `static/capture.html`
  - Do: as U3, inside the `<style>` blocks only. `capture.html` links `tokens.css`; check that `mobile.html` does too (`grep -n 'tokens.css' src/enqueue/static/mobile.html`). If it does not, mark `[!]`.
  - Check: `bin/check-style` prints a total of 0; `bin/verify --fast`. Device: `bin/launch emulator`; the library, a reader and Settings look the same as before.

- [x] **U8. The style check fails the gate** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: U3, U4, U5, U6, U7
  - Files: `bin/verify`, `AGENTS.md`
  - Do:
    1. In `bin/verify`, run `bin/check-style --strict` and fail the fast gate when it exits 1, the way `bin/check-contrast` fails it.
    2. In `AGENTS.md`, add `bin/check-style` to the Bin table and to the description of `bin/verify --fast`.
  - Check: `bin/verify --fast` passes. Add `font-size: 13px;` to one rule in `base.css`, run it again and see it fail, then remove the line.

- [x] **U9. A switch says what it does** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: M6
  - Files: `static/js/artifact.js` (`summaryPanel`), `static/js/drafts.js`
  - Why: the Summary and Drafts switches have the section name as their only label, so "on" has no stated meaning.
  - Find: `grep -n 'aria-label="AI summary"' src/enqueue/static/js/artifact.js`; `grep -n 'role="switch"' src/enqueue/static/js/drafts.js src/enqueue/static/js/artifact.js`
  - Do:
    1. In `summaryPanel`, change the switch's `aria-label` to `Write a summary of this item` and its two `title` texts to `A summary is written for this item` (on) and `No summary is written for this item` (off).
    2. For the Drafts switch, set `aria-label` to `Keep drafts of this note` and the titles to `Drafts of this note are kept` and `Only the latest draft is kept`.
    3. Change no behaviour and no class.
  - Check: `bin/verify --fast`

- [x] **U10. One raven on a screen** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: R1
  - Files: `static/css/artifact.css` (`.related*`)
  - Why: with the Details panel open, the page shows the panel's raven and the Related raven at the same time.
  - Find: `grep -n 'id="drawer"\|drawer.*open\|classList.*open' src/enqueue/static/js/artifact.js | head` to see what marks the panel as open.
  - Do: add one CSS rule that hides `.related-raven` while the panel is open. Use the class or attribute the code sets on the panel or on its parent. If the open state is only on the panel element, use `:has()`: `#view:has(.drawer.open) .related-raven { visibility: hidden; }` with the real class name.
  - Check: `bin/verify --fast`
  - Device check **[device]**: open the Details panel on a note with related rows; one raven shows.

- [x] **U11. Docs for track U** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: U1 to U10
  - Files: `docs/DESIGN.md`, `AGENTS.md`
  - Do: in `docs/DESIGN.md`, state the type scale rule and the check. In `AGENTS.md`, in the row for `static/css/`, add: never write a font size in px in a stylesheet; use a `--t-*` token.
  - Check: `bin/verify --fast`

---

## Track I: index speed

- [x] **I1. The query vector is sent as bytes** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: none
  - Files: `index/embed.py`, `index/store_sqlite.py`
  - Why: each search turns the 768-number query vector into JSON text 16 times.
  - Find: `grep -n 'json.dumps(embed_query\|json.dumps(vector)\|json.dumps(v)' src/enqueue/index/store_sqlite.py`
  - Do:
    1. In `embed.py`, add:
       ```python
       @lru_cache(maxsize=512)
       def query_bytes(text: str) -> bytes:
           """A search's vector in sqlite-vec's own form, memoized like `embed_one`."""
           import sqlite_vec

           return sqlite_vec.serialize_float32(embed_query(text))


       @lru_cache(maxsize=64)
       def passage_bytes(text: str) -> bytes:
           import sqlite_vec

           return sqlite_vec.serialize_float32(embed_passage(text))
       ```
    2. In `store_sqlite.py` `_dense`, replace the `json.dumps(...)` line with `query = query_bytes(text) if as_query else passage_bytes(text)`. Import both names from `.embed`.
    3. In `search_within`, replace `json.dumps(embed_query(text))` with `query_bytes(text)`.
    4. In each insert that binds `json.dumps(vector)` or `json.dumps(v)` for an embedding, bind `sqlite_vec.serialize_float32(vector)`.
    5. Do not change a `json.dumps` that binds a list of ids.
  - Test: none new. The search tests cover it.
  - Check: `uv run pytest tests/test_search_results.py tests/test_related.py tests/test_chats.py tests/test_shiny.py -q`; `bin/check-eval-cross`

- [x] **I2. Each ingest step says how long it took** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: none
  - Files: `ingest/queue.py` (`_process`, the `events.emit("ingest", ...)` call), `tests/test_ingest.py`
  - Why: the owner needs these numbers to decide if two model steps run in parallel.
  - Find: `grep -n 'events.emit' src/enqueue/ingest/queue.py`; read `_process` whole first.
  - Do:
    1. At the start of `_process`, make `took: dict[str, int] = {}` and a small helper:
       ```python
       def _timed(name: str, started: float) -> None:
           took[name] = took.get(name, 0) + int((time.monotonic() - started) * 1000)
       ```
    2. Around each of these steps, take `started = time.monotonic()` before and call `_timed(<name>, started)` after: chunking (`chunk`), indexing (`index`), `_sections_artifact` (`sections`), `_facet_artifact` (`facets`), `_entities_artifact` (`entities`), `_context_artifact` (`contexts`), `related.compute` (`related`).
    3. Add `"took_ms": took` to the `data` of the `ingest` event.
    4. Add `import time` if the file does not have it.
  - Test: after one ingest that writes an `ingest` event, the event's data has `took_ms` with the key `chunk`.
  - Check: `uv run pytest tests/test_ingest.py tests/test_facet_retry.py tests/test_writing_pace.py -q`

---

## Track E: evals

- [x] **E1. The real-search eval sees searches that failed** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: Q1
  - Files: `eval_real.py`, new `tests/test_eval_real.py`, `AGENTS.md`
  - Why: the eval only sees a search that ended in an open. A search that found nothing useful is the case that matters most.
  - Find: read `eval_real.py` whole (92 lines).
  - Do:
    1. Add `def reformulated(conn) -> list[dict]`. For each `searches` row A with source `search`: when the `opens` table has no row with `source = 'search'` and `query = A.query` within 5 minutes after A; and a later `searches` row B exists within 90 seconds after A with another query; and `opens` has a row for B's query within 5 minutes after B: yield `{"query": A.query, "expect": [<that artifact id>]}`.
    2. Add `def abandoned(conn) -> list[str]`: the queries of `searches` rows with source `search`, one or more hits, and no open for that query within 5 minutes. Newest first, 50 at most.
    3. Where the eval builds its cases from `opens`, add the cases of `reformulated`. Merge by query: the expected ids of the two sources are joined.
    4. Add `abandoned` to the report the eval returns, under the key `abandoned`. It is not scored.
    5. In `AGENTS.md` "Real-search eval", add two sentences on the two new kinds.
  - Test: in `tests/test_eval_real.py`, write rows into `searches` and `opens` with fixed times. One case where A, B and the open fit the windows gives one reformulated case. One where B is 5 minutes after A gives none. One search with hits and no open is in `abandoned`.
  - Check: `uv run pytest tests/test_eval_real.py -q`

---

## Tracks from the Fabric review (2026-11-16)

Source: `fabric.so/features/your-cloud`, `/ai-assistant` and `/search`, read on 2026-11-16.
What Enqueue has now, against what those pages offer:

| Fabric offers | Enqueue now | Track |
| --- | --- | --- |
| An answer shows where in the document it came from | An answer names the items it used, not the place | A |
| A search result opens at the paragraph or page | A note opens at its tab; a PDF opens at page 1 | N |
| Search inside PDFs and notes | Yes | N4 locks it with tests |
| Natural-language search | Kind and time words become filters | N4 locks it with tests |
| Similar content | Related notes (track R) | N3 adds "More like this" |
| Files take no disk space and open at once | Originals stay on the Mac; the phone fetches on demand | C |
| A cloud you can open and use | Backups are sealed and cannot be browsed | C6, and owner item O7 |
| Colour search | No | V |
| Visual search (find similar pictures) | Pictures are found by their description text only | owner item O7 |
| Search and questions on audio and video | No audio or video kind | owner item O7 |

- [x] **DB2. Four more migrations** (claimed: agent, 2026-11-16)
  Done: migrations 0049-0052, trash.py purge, tests; 24 passed
  - Needs: DB1
  - Files: new `migrations/versions/0049_chat_places.py`, new `migrations/versions/0050_blob_relay.py`, new `migrations/versions/0051_artifact_colours.py`, new `migrations/versions/0052_thumbs.py`, `trash.py`, `tests/test_migrations.py`, `tests/test_trash.py`
  - Do:
    1. `0049_chat_places` (`down_revision = "0048_link_feedback"`):
       ```sql
       CREATE TABLE chat_places (
         message_id TEXT NOT NULL,
         n INTEGER NOT NULL,
         artifact_id TEXT NOT NULL,
         page INTEGER,
         quote TEXT NOT NULL DEFAULT '',
         PRIMARY KEY (message_id, n)
       );
       ```
    2. `0050_blob_relay` (`down_revision = "0049_chat_places"`):
       ```sql
       CREATE TABLE blob_relay (
         content_hash TEXT PRIMARY KEY,
         relay TEXT NOT NULL,
         pushed_at TEXT NOT NULL
       );
       ```
    3. `0051_artifact_colours` (`down_revision = "0050_blob_relay"`):
       ```sql
       CREATE TABLE artifact_colours (
         artifact_id TEXT NOT NULL,
         r INTEGER NOT NULL,
         g INTEGER NOT NULL,
         b INTEGER NOT NULL,
         share REAL NOT NULL,
         PRIMARY KEY (artifact_id, r, g, b)
       );
       ```
    4. `0052_thumbs` (`down_revision = "0051_artifact_colours"`):
       ```sql
       CREATE TABLE thumbs (
         artifact_id TEXT PRIMARY KEY,
         content_hash TEXT NOT NULL,
         width INTEGER NOT NULL
       );
       ```
    5. In `trash.py`, find the function that purges one artifact (`grep -n 'def purge' src/enqueue/trash.py`). Where it deletes the artifact's rows from other tables, add deletes for `chat_places`, `artifact_colours` and `thumbs` by `artifact_id`.
  - Test: the four tables exist after `db.migrate()`. After a purge, no row of the three tables names the artifact.
  - Check: `uv run pytest tests/test_migrations.py tests/test_trash.py -q`

---

## Track A: an answer shows where it came from

Finding: an answer lists the items it used. It does not say which page or paragraph, and a press on a source opens the item at its start.

- [x] **A1. A passage knows its page and its first words** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: none
  - Files: `ingest/chunk.py`, `tests/test_chunk.py`
  - Why: a PDF's passages are made from text with a `## page N` heading for each page. That is enough to know each passage's page with no new column.
  - Do: add to `ingest/chunk.py` (add `import re` if absent):
    ```python
    _PAGE_HEADING = re.compile(r"^## page (\d+)\s*$", re.M)


    def pages_for(conn, artifact_id: str) -> dict[str, int]:
        """Chunk id -> the PDF page it starts on, counted from 0. Empty for anything
        but a PDF."""
        row = conn.execute("SELECT kind FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None or row["kind"] != "pdf":
            return {}
        out: dict[str, int] = {}
        carried = 0
        for c in conn.execute(
            "SELECT id, text FROM chunks WHERE artifact_id = ? ORDER BY ordinal", (artifact_id,)
        ):
            found = [int(n) - 1 for n in _PAGE_HEADING.findall(c["text"])]
            starts = c["text"].lstrip().startswith("## page ")
            out[c["id"]] = found[0] if (found and starts) else carried
            if found:
                carried = found[-1]
        return out


    def quote_of(text: str, words: int = 10) -> str:
        """The first words of a passage's own text, for finding it again in the reader."""
        lines = [
            ln
            for ln in text.splitlines()
            if ln.strip()
            and not ln.lstrip().startswith("#")
            and not ln.startswith("(note added by you)")
        ]
        return " ".join(" ".join(lines).split()[:words])
    ```
  - Test: in `tests/test_chunk.py`, insert a `pdf` artifact and three chunks by hand: `"## page 1\n\nalpha"`, `"more of page one"`, `"## page 2\n\nbeta"`. `pages_for` gives 0, 0, 1. A `note` artifact gives `{}`. `quote_of("# Title\n\none two three")` gives `"one two three"`.
  - Check: `uv run pytest tests/test_chunk.py -q`

- [x] **A2. Passages are numbered and the model says which it used** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: none
  - Files: `chats.py`, `schemas.py` (`Answer`), `prompts.py` (`CHAT_ANSWER`), `tests/test_chats.py`
  - Find: `grep -n 'response_model=Answer' src/enqueue/chats.py`; read 20 lines above it.
  - Do:
    1. Where the prompt body is built from the passages (the f-string with `(id: {p['artifact_id']})`), number them. Use `enumerate(found, 1)` and start each header with `[P{n}] `, so a header reads `[P3] [pdf] (id: <id>) <title>`.
    2. In the `context=` of that call, add `"offered_passages": len(found)`.
    3. In `schemas.py` `Answer`, add the field:
       ```python
       used: list[int] = Field(
           default_factory=list,
           description="Numbers of the passages the answer rests on, most important first.",
       )
       ```
    4. In `Answer.check`, before `return self`, add:
       ```python
       count = (info.context or {}).get("offered_passages", 0)
       self.used = [
           n for n in dict.fromkeys(self.used) if isinstance(n, int) and 1 <= n <= count
       ][:8]
       ```
    5. In `prompts.py` `CHAT_ANSWER`, add this paragraph before its last line:
       ```text
       Each passage starts with a number in the form [P3]. After a sentence that rests on
       a passage, put that passage's number in the same form, for example: The budget was
       cut in March [P2]. In `used`, list the numbers of the passages you used, the most
       important first, at most 8. Never write a number you were not shown.
       ```
    6. In `chats.py`, add:
       ```python
       def without_places(text: str) -> str:
           """An answer's text with its [P3] place marks removed."""
           return re.sub(r"\s?\[P\d+\]", "", text or "")
       ```
       Add `import re` if absent. Use it where the answer text is given to the title and topics calls, and in the `detail` of the `ask.answered` event.
  - Test: with a fake provider that returns `used=[2, 9, 2]` and 3 passages offered, the stored answer has `used == [2]`. The prompt body sent to the provider holds `[P1]`. `without_places("A [P1]. B [P12]")` gives `"A. B"`.
  - Check: `uv run pytest tests/test_chats.py tests/test_chats_worker.py -q`
  - Do not: reject an answer because a number is wrong. Wrong numbers are dropped.

- [x] **A3. Keep the place of each passage an answer used** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: DB2, A1, A2
  - Files: `chats.py`, `chats_worker.py`, `tests/test_chats_worker.py`
  - Find: `grep -rn 'chat_citations' src/enqueue/chats.py src/enqueue/chats_worker.py`. This shows where citations are written, read (`get`) and deleted (`delete`). Follow how `cited` goes from the answer to the row.
  - Do:
    1. Where the `Answer` comes back and `found` (the passages) is still at hand, build the places:
       ```python
       places = []
       pages: dict[str, dict[str, int]] = {}
       for n in answer.used:
           p = found[n - 1]
           aid = p["artifact_id"]
           if str(p["id"]).startswith("overview:"):
               page, quote = None, ""
           else:
               if aid not in pages:
                   pages[aid] = chunk.pages_for(conn, aid)
               page, quote = pages[aid].get(p["id"]), chunk.quote_of(p["text"])
           places.append({"n": n, "artifact_id": aid, "page": page, "quote": quote})
       ```
       Import `chunk` from `.ingest`. Open a connection for this if none is at hand.
    2. Carry `places` to the code that writes `chat_citations`, the same way `cited` is carried. In the same transaction, delete the message's `chat_places` rows and insert the new ones.
    3. In `chats.get`, read the `chat_places` rows of the chat's messages in one query and add `places` (a list, in order of `n`) to each assistant message.
    4. In `chats.delete`, delete the `chat_places` rows of the chat's messages, next to the `chat_citations` delete.
  - Test: after `compute` with a fake provider that returns `used=[1]`, `chats.get` gives the assistant message one place with the right `artifact_id` and a `quote` that is the start of the passage. After `chats.delete`, the table has no row for it.
  - Check: `uv run pytest tests/test_chats_worker.py tests/test_chats.py -q`

- [x] **A4. Places ride the conversation's snapshot** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: A3
  - Files: `sync/snapshot.py` (`read_chat_snapshot`, `apply_chat_snapshot`), `tests/test_snapshot.py`
  - Find: `grep -n 'def read_chat_snapshot\|def apply_chat_snapshot\|"citations"' src/enqueue/sync/snapshot.py`
  - Do:
    1. In `read_chat_snapshot`, add a key `places`: the `chat_places` rows of the chat's messages, each `{message_id, n, artifact_id, page, quote}`, ordered by `message_id, n`.
    2. In `apply_chat_snapshot`, only when the snapshot has the key `places`: delete the `chat_places` rows of the chat's messages and insert the incoming ones. A snapshot without the key (the phone's) leaves the rows alone.
  - Test: a chat with one place round-trips through read and apply into a second store. Applying a snapshot with no `places` key keeps the rows.
  - Check: `uv run pytest tests/test_snapshot.py tests/test_sync.py -q`

- [x] **A5. The reader can open at a place** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: none
  - Files: `static/js/artifact.js` (new functions, and one call at the end of `showArtifact`)
  - Find: `grep -n 'async function showArtifact\|async function openFind\|function showFindHit\|function openArtifact' src/enqueue/static/js/artifact.js`. Read `openFind` whole: it shows how the find field in the pill gets its text and how a search inside the item starts.
  - Do:
    1. Add a variable `let openAt = null;` near the other state variables of the file.
    2. Add:
       ```js
       // Open an item at a place: a PDF page (counted from 0) and the first words of
       // a passage, which the find field then marks.
       function openArtifactAt(id, place, source) {
         openAt = { id, page: place && place.page, quote: (place && place.quote) || "" };
         openArtifact(id, source || "chat");
       }
       ```
       Make it reachable from other files the same way `openArtifact` is (`grep -n 'window.openArtifact' src/enqueue/static/js/*.js`).
    3. At the end of `showArtifact`, after the page is drawn, add: when `openAt` is set and `openAt.id` is the shown id, take it and clear the variable, then:
       - when `page` is a number, find `document.querySelector('.leaf[data-page="' + page + '"]')` and call `scrollIntoView({ block: "start" })` on it;
       - when `quote` has 3 words or more, open the find field as `openFind` does and put the first 6 words of the quote in it, then start the find the way a typed query starts it.
    4. A `showArtifact` that draws the same item again for another reason (a save, a focus) must not find `openAt` set: clear it the first time it is used.
  - Check: `bin/verify --fast`
  - Device check **[device]**: in the page console run `openArtifactAt('<id of a PDF>', {page: 2, quote: '<six words from page 3>'})`. The PDF scrolls to page 3 and the words are marked.

- [x] **A6. An answer's place marks are buttons** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: A3, A5
  - Files: `static/js/chat.js`, `static/css/chat.css`
  - Find: `grep -n 'md(m.text)' src/enqueue/static/js/chat.js`
  - Do:
    1. Add a function:
       ```js
       // Turn [P3] in an answer into a button that opens the item at that place.
       function withPlaces(html, m) {
         const byN = {};
         (m.places || []).forEach((p) => (byN[p.n] = p));
         return html.replace(/\s?\[P(\d+)\]/g, (all, n) => {
           const p = byN[n];
           if (!p) return "";
           const label = p.page === null || p.page === undefined ? "source" : "p. " + (p.page + 1);
           return (
             ' <button class="place" type="button" data-id="' +
             esc(p.artifact_id) +
             '" data-n="' +
             esc(String(n)) +
             '">' +
             label +
             "</button>"
           );
         });
       }
       ```
    2. For an assistant message, wrap the rendered text: `withPlaces(md(m.text), m)`.
    3. After the transcript is drawn, bind each `.place` button: find the message's place by `data-n` and call `openArtifactAt(p.artifact_id, p, "chat")`. Bind with a listener on the transcript container, not an inline handler. To find the message, put `data-mid="<message id>"` on the bubble if it has none.
    4. In `chat.css`, add:
       ```css
       .place {
         padding: 0 6px;
         border: 0;
         border-radius: var(--r-full);
         background: var(--surface-3);
         color: var(--accent-text);
         font-size: 12px;
         cursor: pointer;
       }
       .place:focus-visible {
         outline: 2px solid var(--accent);
         outline-offset: 2px;
       }
       ```
  - Check: `bin/verify --fast`
  - Device check **[device]**: ask a question that a long PDF answers. The answer has "p. N" buttons. A press opens the PDF at that page with the words marked.

- [x] **A7. The phone does not show raw place marks** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: A2
  - Files: `static/mobile.html` (the chat message text only)
  - Find: `grep -n 'm.cited && m.cited.length' src/enqueue/static/mobile.html`; the message text is drawn a few lines above.
  - Do: where an assistant message's text is drawn, remove the marks first: `text.replace(/\s?\[P\d+\]/g, "")`.
  - Check: `bin/verify --fast`

- [x] **A8. Docs for track A** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: A1 to A7
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do: in `AGENTS.md` "Chat", describe the numbered passages, `Answer.used`, `chat_places`, and that places ride the chat snapshot. Add the table to the tables list. In `docs/MANUAL.md`, say that an answer's "p. N" opens the document at that page.
  - Check: `bin/verify --fast`

---

## Track N: a search result opens at the place, and what exists is locked with tests

- [x] **N1. A search hit carries its page and its first words** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: A1
  - Files: `retrieve/candidates.py` (`_hybrid_results`: the `out.append({...})` dict), `api/search.py` (`_dated`), `tests/test_search_results.py`
  - Do:
    1. In `_hybrid_results`, add `"chunk_id": info["chunk_id"]` to the dict that is appended to `out`.
    2. In `api/search.py` `_dated`, for each hit with `kind == "pdf"` and a `chunk_id`: set `h["page"] = chunk.pages_for(conn, h["artifact_id"]).get(h["chunk_id"])`. Call `pages_for` one time for each artifact.
    3. For each hit that has `text`, set `h["quote"] = chunk.quote_of(h["text"])`.
  - Test: a PDF artifact with chunks for two pages (insert them as in A1's test, then index with `get_store().index_artifact(id)`). A search for a word that is only on page 2 returns the PDF with `page == 1`.
  - Check: `uv run pytest tests/test_search_results.py -q`

- [x] **N2. A search result opens at the place** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: N1, A5
  - Files: `static/js/search.js` (`openHit`)
  - Find: `grep -n 'function openHit' -A 8 src/enqueue/static/js/search.js`
  - Do: in `openHit`, when the hit's kind is not `note` and it has a `quote`, call `openArtifactAt(id, { page: hit.page, quote: hit.quote }, "search")` in place of `showArtifact(id)`. Keep the lines before it (the open is still reported with its query and rank). A note keeps `NoteTabs.hint` and `showArtifact`.
  - Check: `bin/verify --fast`
  - Device check **[device]**: search a word that is deep in a PDF; the result opens at that page with the word marked.

- [x] **N3. "More like this"** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: R1
  - Files: `retrieve/passage_links.py`, `api/artifacts.py` (new route at the end), `static/js/artifact.js` (`relatedRowHtml`, `mountRelatedRow`), `static/js/search.js`, new `tests/test_similar.py`
  - Do:
    1. In `passage_links.py`, add `similar_items(artifact_id: str, limit: int = 12) -> list[dict]`:
       - read the first 12 chunk ids of the artifact;
       - for each, `store.similar_chunks(chunk_id, limit=12)`;
       - for each other artifact, keep its 3 best scores and add them;
       - return live items, best sum first: `{"artifact_id", "title", "kind", "score", "snippet"}`, where `snippet` is the first 200 characters of that item's best-matching chunk.
    2. Add the route `GET /artifacts/{artifact_id}/similar` that returns `{"hits": similar_items(artifact_id)}`.
    3. In `relatedRowHtml`, add a text button `More like this` in the `related-head`, with `data-like="<this item's id>"`. `relatedRowHtml(related, aid)` already has the item's id as `aid`.
    4. When an item has no related rows, still draw the head with the button.
    5. In `search.js`, add `doSimilar(id, title)`: fetch the route and draw the hits with the function `doSearch` uses to draw `r.hits`, under the heading `Like "<title>"`. Find that function by reading `doSearch` after the line `lastHits = r.hits`.
    6. In `mountRelatedRow`, bind the button to `doSimilar`.
  - Test: three notes, two of them about the same thing in nearly the same words. `similar_items` of one returns the other first and does not return itself.
  - Check: `uv run pytest tests/test_similar.py -q`; `bin/verify --fast`

- [x] **N4. Lock the natural-language search with tests** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: none
  - Files: new `tests/test_search_language.py`
  - Why: the owner wants these behaviours explicit and kept. They exist in `retrieve/filters.py`; no one test lists them in one place.
  - Find: read `retrieve/filters.py` whole. Note the fields of `Filters` and what `parse(q, now)` returns.
  - Do:
    1. Write one parametrized test over this table. Call `filters.parse(query, now=datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc))`.

       | Query | Kind filter | Time filter | Text that is left to search |
       | --- | --- | --- | --- |
       | `pdfs from last month` | pdf | October 2026 | empty |
       | `the article about pricing I saved last week` | link | the week before this one | holds `pricing` |
       | `screenshots this week` | image | this week | empty |
       | `notes about hiring` | none | none | `notes about hiring` |
       | `receipts in March` | none | March 2026 | holds `receipts` |
       | `photos from 2024` | image | the year 2024 | empty |
       | `pdf about tax in the last 30 days` | pdf | the last 30 days | holds `tax` |
       | `what did I save yesterday` | none | yesterday | does not hold `yesterday` |
       | `"last week"` | none | none | the search treats it as a phrase (test through `search_results`, which must not filter by time) |
    2. Assert the kind set, that the time bounds are set or `None`, and the left-over text, for each row.
    3. If a row fails, do not change `filters.py`. Mark that row `pytest.param(..., marks=pytest.mark.xfail(reason="<what it returned>"))` and write the query and the real output under this task.
    4. Add two tests with the `store` and `quiet_queue` fixtures: a word that is only in the body of a note is found by `search_results`; a word that is only in a PDF's page text (insert the `page_text` row and run the ingest for the artifact) is found.
  - Check: `uv run pytest tests/test_search_language.py -q`

- [x] **N5. Docs for track N** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: N1 to N4
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do: add `GET /artifacts/{id}/similar` to the API list; in "Retrieval design notes", add that a hit carries `page` and `quote`. In `docs/MANUAL.md`, describe "More like this" and that a result opens at its place.
  - Check: `bin/verify --fast`

---

## Track C: storage that takes less space and opens fast

Finding: the Mac fetches a missing original from the relay on demand now (`capture.blob_path` calls `fetch_blob_to_cache`). So the Mac can let go of an original it has not used, if it knows for certain that the relay holds it. The wall loads each picture at full size.

- [x] **C1. Small pictures for the wall** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: DB2
  - Files: new `thumbs.py`, `api/artifacts.py` (new route at the end), `ingest/queue.py` (one call), `vaultops.py` (one call), `static/js/home.js` (`facePicture`), new `tests/test_thumbs.py`
  - Why: `facePicture` loads `/artifacts/<id>/blob` for each picture tile: the whole original. A small picture opens faster, and it stays when the original leaves this Mac (C4).
  - Do:
    1. Make `thumbs.py`:
       ```python
       """Small pictures of image artifacts, kept sealed like every original (blobstore)."""

       from __future__ import annotations

       import logging

       from . import blobstore, db

       log = logging.getLogger(__name__)
       WIDTH = 520
       _TYPES = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif", "image/webp": "webp"}


       def render(data: bytes, mime: str, width: int = WIDTH) -> bytes | None:
           """A JPEG at most `width` pixels wide, or None for a type that cannot be drawn."""
           import fitz

           ext = _TYPES.get(mime)
           if ext is None:
               return None
           doc = fitz.open(stream=data, filetype=ext)
           try:
               page = doc[0]
               scale = min(1.0, width / max(page.rect.width, 1))
               pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
               return pix.tobytes("jpeg")
           finally:
               doc.close()


       def make(artifact_id: str) -> bool:
           """Make and keep the small picture of one live image. True when one is kept."""
           conn = db.get_conn()
           try:
               row = conn.execute(
                   "SELECT kind, mime, content_hash, vaulted_at, deleted_at FROM artifacts"
                   " WHERE id = ?",
                   (artifact_id,),
               ).fetchone()
           finally:
               conn.close()
           if row is None or row["kind"] != "image" or row["vaulted_at"] or row["deleted_at"]:
               return False
           if not row["content_hash"] or not blobstore.exists(row["content_hash"]):
               return False
           try:
               small = render(blobstore.read(row["content_hash"]), row["mime"] or "")
           except Exception:  # noqa: BLE001 - a picture that cannot be drawn has no thumb
               log.info("no small picture for %s", artifact_id)
               return False
           if small is None:
               return False
           digest = blobstore.write(small)
           with db.transaction() as conn:
               conn.execute(
                   "INSERT OR REPLACE INTO thumbs (artifact_id, content_hash, width)"
                   " VALUES (?, ?, ?)",
                   (artifact_id, digest, WIDTH),
               )
           return True


       def get(artifact_id: str) -> bytes | None:
           conn = db.get_conn()
           try:
               row = conn.execute(
                   "SELECT t.content_hash FROM thumbs t JOIN artifacts a ON a.id = t.artifact_id"
                   " WHERE t.artifact_id = ? AND a.vaulted_at IS NULL AND a.deleted_at IS NULL",
                   (artifact_id,),
               ).fetchone()
           finally:
               conn.close()
           if row is None or not blobstore.exists(row["content_hash"]):
               return None
           return blobstore.read(row["content_hash"])


       def drop(artifact_id: str) -> None:
           """Remove the small picture (the item went into the vault)."""
           with db.transaction() as conn:
               row = conn.execute(
                   "SELECT content_hash FROM thumbs WHERE artifact_id = ?", (artifact_id,)
               ).fetchone()
               conn.execute("DELETE FROM thumbs WHERE artifact_id = ?", (artifact_id,))
           if row is not None:
               blobstore.remove(row["content_hash"])
       ```
       Check the real signature of `blobstore.write` and what it returns before you use it (`grep -n 'def write' -A 14 src/enqueue/blobstore.py`).
    2. Add the route:
       ```python
       @router.get("/artifacts/{artifact_id}/thumb")
       def get_thumb(artifact_id: str):
           from .. import thumbs

           data = thumbs.get(artifact_id)
           if data is None and thumbs.make(artifact_id):
               data = thumbs.get(artifact_id)
           if data is None:
               raise HTTPException(status_code=404, detail="no small picture")
           return Response(
               content=data,
               media_type="image/jpeg",
               headers={"Cache-Control": "private, max-age=86400"},
           )
       ```
    3. In `ingest/queue.py` `_process`, for an artifact of kind `image`, call `thumbs.make(artifact_id)` inside a `try` that logs and goes on. Put it after the step that describes the image.
    4. In `vaultops.py`, where an item is moved into the vault (the function that calls `_seal_derived`), call `thumbs.drop(artifact_id)`.
    5. In `home.js` `facePicture`, for `a.kind === "image"`, use `/thumb` and fall back to the original one time:
       ```js
       const drop =
         ' onerror="if(!this.dataset.full){this.dataset.full=1;this.src=\'/artifacts/' +
         a.id +
         '/blob\'}else{this.remove()}"';
       ```
       Use this `drop` for the image case only, with `src="/artifacts/<id>/thumb"`.
  - Test: `render` of a 1200 px wide PNG (make one with `fitz` in the test) returns bytes that `fitz` opens at 520 px wide. `make` for a note returns false. After `drop`, `get` returns `None`.
  - Check: `uv run pytest tests/test_thumbs.py tests/test_vaultops.py -q`; `bin/verify --fast`

- [x] **C2. The Mac records which originals the relay holds** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: DB2
  - Files: `sync/client.py`, `tests/test_sync.py`
  - Find: `grep -n '/sync/object/blobs/' src/enqueue/sync/client.py`. Two of the lines are `client.put(...)`.
  - Do:
    1. Add a helper:
       ```python
       def _note_blob_on_relay(content_hash: str, url: str) -> None:
           with db.transaction() as conn:
               conn.execute(
                   "INSERT OR REPLACE INTO blob_relay (content_hash, relay, pushed_at)"
                   " VALUES (?, ?, ?)",
                   (content_hash, url.rstrip("/"), db.now()),
               )
       ```
    2. After each blob `PUT` whose status is 201 or 409, call it with the hash and the relay address.
    3. In `fetch_blob_to_cache`, after a blob was fetched and opened, call it too: the relay holds what it just gave.
  - Test: copy a test in `tests/test_sync.py` that pushes an artifact with a file to the test relay. After the push, `blob_relay` has a row for the file's hash with the relay's address.
  - Check: `uv run pytest tests/test_sync.py -q`

- [x] **C3. The relay says if it holds an object, and how large it is** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: none
  - Files: `relay/app.py`, `relay/storage.py`, the relay's test file (`ls tests | grep relay`)
  - Find: `grep -n 'def get(self, library' -A 20 src/enqueue/relay/storage.py`; `grep -n '@app.get("/sync/object' -A 6 src/enqueue/relay/app.py`
  - Do:
    1. In `storage.py`, add `def size(self, library: str, name: str) -> int | None`. It reads the `size` column of the object's row, with the same `WHERE` that `get` uses. `None` when there is no row.
    2. In `app.py`, next to `get_object`, add:
       ```python
       @app.head("/sync/object/{name:path}")
       def head_object(name: str, library: str = Depends(_require_header)):
           size = storage.size(library, name)
           if size is None:
               raise HTTPException(status_code=404, detail="no such object")
           return Response(status_code=200, headers={"X-Object-Size": str(size)})
       ```
  - Test: `HEAD` of a stored object answers 200 with `X-Object-Size` equal to the length of the stored bytes. `HEAD` of an unknown name answers 404. `HEAD` with another library's secret answers 404 or 401, never the size.
  - Check: `uv run pytest tests -k relay -q`
  - Do not: run `bin/deploy-relay`. The owner deploys.

- [x] **C4. Free up space: let go of originals the relay holds (off by default)** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: C1, C2, C3
  - Files: new `offload.py`, `settings.py`, `backup.py` (`start_scheduler`), new `tests/test_offload.py`
  - Why: an original that was not opened for a month can live on the relay only. The Mac fetches it again when it is opened. This task deletes local files, so each check below is necessary.
  - Find: `grep -n '"drafts_keep"' src/enqueue/settings.py` for how a setting is declared.
  - Do:
    1. In `settings.py`, declare two settings in the same form: `"offload_originals": ("ENQ_OFFLOAD", "off", True)` and `"offload_after_days": ("ENQ_OFFLOAD_DAYS", "30", True)`.
    2. Make `offload.py` with three functions.
    3. `candidates(conn, days: int, relay: str) -> list[dict]`. An artifact is a candidate only when ALL of these are true:
       - it is live, `local_only = 0`, `pinned = 0`, and its kind is `pdf`, `image` or `file`;
       - `content_hash` is set, and `blob_relay` has a row for it whose `relay` is the current relay address;
       - `blobstore.exists(content_hash)`;
       - `updated_at` is older than `days` days, and `opens` has no row for it in the last `days` days;
       - for an image, `thumbs` has a row.
    4. `on_relay(content_hash: str) -> bool`. It sends `HEAD <relay>/sync/object/blobs/<crypto.blob_name(content_hash, dek)>` with the same `Authorization` header that `fetch_blob_to_cache` sends. It returns true only when the status is 200 AND the header `X-Object-Size` equals `len(crypto.seal_payload(blobstore.read(content_hash), dek))`. Any error, any other status, or a missing header gives false.
    5. `run(limit: int = 200) -> dict`. It returns at once with `{"freed": 0}` when the setting `offload_originals` is not `on`, when sync is not configured, or when the sync key is absent. Else, for each candidate up to `limit`: when `on_relay` is true, call `blobstore.remove(content_hash)` and add the file's size to a total. Emit one event `storage.offloaded` with the count and the bytes when the count is above 0. Return `{"freed": <count>, "bytes": <total>}`.
    6. In `backup.py` `start_scheduler`, in the `if due:` block, add a `try` block that calls `offload.run()`, in the shape of the drafts block. Put it after the backup, so the backup holds the files first.
  - Test: in `tests/test_offload.py`, use the test relay pattern of `tests/test_sync.py`:
    1. With the setting off, `run` removes nothing.
    2. With the setting on and all conditions true, the local file is removed, and `capture.blob_path(id)` then brings it back from the relay with the same bytes.
    3. A pinned artifact keeps its file.
    4. A `local_only` artifact keeps its file.
    5. An artifact opened yesterday keeps its file.
    6. When the relay answers 404 to `HEAD`, the file stays.
    7. When `X-Object-Size` is wrong by one byte, the file stays.
    8. When `blob_relay` names another relay address, the file stays.
  - Check: `uv run pytest tests/test_offload.py tests/test_sync.py -q`
  - Do not: turn the setting on. Do not call `blobstore.remove` from any other place.

- [x] **C5. Settings shows what the originals use, and the switch** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: C4
  - Files: `offload.py`, `api/admin.py` (new route), `static/js/settings.js` (one new block in the Library tab)
  - Do:
    1. In `offload.py`, add `report() -> dict`: `{"local_bytes", "local_count", "could_free_bytes", "could_free_count", "ready"}`. `local_*` is over live artifacts whose file is on this Mac (`blobstore.size`). `could_free_*` is over `candidates` with no relay call. `ready` is true when sync is configured.
    2. Add `GET /storage/originals` that returns it.
    3. In the Library tab, add a section "Space on this Mac": one line `Original files on this Mac: <size>.`; when `ready`, a switch bound to `offload_originals` with the label `Keep files I have not opened in 30 days in Enqueue sync only` and the sentence `They open again when you need them. Pinned items and items marked "only on this Mac" always stay. This can free <size> now.`
    4. When `ready` is false, show in place of the switch: `Turn on Enqueue sync to free space on this Mac.`
    5. Write the switch through `PATCH /settings`, as the other switches of the tab do.
  - Check: `uv run pytest tests/test_offload.py tests/test_settings.py -q`; `bin/verify --fast`

- [x] **C6. A plain copy of the library in a folder you choose, kept up to date** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: none
  - Files: `settings.py`, `backup.py` (`start_scheduler`), `static/js/settings.js` (the "Move notes in and out" part of the Library tab), new `tests/test_export_schedule.py`
  - Why: the backup is sealed, so it cannot be opened as files. `export.py` writes the library as plain Markdown and original files, and a second run changes only what changed. A folder inside an end-to-end encrypted drive (Proton Drive) gives a copy that is private and can be used.
  - Find: `grep -n '^def ' src/enqueue/export.py`; `grep -n 'export' src/enqueue/api/portable.py`
  - Do:
    1. Declare a setting `"export_dir": ("ENQ_EXPORT_DIR", "", True)`.
    2. In `start_scheduler`, in the `if due:` block, add a `try` block: when `export_dir` is not empty and the folder exists, call the same function `POST /export` calls, with `<export_dir>/Enqueue` as the target. A missing folder is skipped with one log line, never created.
    3. In the Library tab, next to the export button, add a switch `Keep this copy up to date every day`. On: it stores the folder of the last export as `export_dir`. Off: it stores an empty string.
    4. Under the switch, always show: `Files in this folder are not encrypted by Enqueue. Anyone who can open the folder can read them. Use a folder in a drive that is end-to-end encrypted.`
    5. Items in the vault and items marked local-only are not written. Check how `export.py` treats them; if it writes local-only items, leave them out of the scheduled run only and say so in the sentence.
  - Test: with `export_dir` set to a temp folder, the scheduled function writes one Markdown file for a note; a second run changes no file time when nothing changed; a vaulted note is not written.
  - Check: `uv run pytest tests/test_export_schedule.py -q`; `bin/verify --fast`

- [x] **C7. Docs for track C** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: C1 to C6
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do: add `thumbs.py` and `offload.py` to the module map; add the three tables; add the `HEAD` route to "The relay"; add a Gotchas section "An original can live on the relay only" with the eight conditions of C4. In `docs/MANUAL.md`, describe "Space on this Mac" and the daily plain copy.
  - Check: `bin/verify --fast`

---

## Track V: find a picture by its colour

Finding: this library has few pictures now, so this track is small. It makes every step on this Mac, with no upload and no model.

- [x] **V1. Each picture knows its main colours** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: DB2
  - Files: new `colours.py`, `ingest/queue.py` (one call), `vaultops.py` (one call), new `tests/test_colours.py`
  - Do:
    1. Make `colours.py`:
       ```python
       """The main colours of a picture, worked out on this Mac."""

       from __future__ import annotations

       from . import blobstore, db

       _TYPES = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif", "image/webp": "webp"}


       def palette(data: bytes, mime: str, top: int = 5) -> list[tuple[int, int, int, float]]:
           """Up to `top` colours as (r, g, b, share of the picture), largest share first."""
           import fitz
           import numpy as np

           ext = _TYPES.get(mime)
           if ext is None:
               return []
           doc = fitz.open(stream=data, filetype=ext)
           try:
               page = doc[0]
               scale = 64 / max(page.rect.width, page.rect.height, 1)
               pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
               px = np.frombuffer(pix.samples, dtype=np.uint8).reshape(-1, pix.n)[:, :3]
           finally:
               doc.close()
           bins = (px >> 5).astype(np.int32)
           keys = bins[:, 0] * 64 + bins[:, 1] * 8 + bins[:, 2]
           counts = np.bincount(keys, minlength=512)
           out = []
           for key in np.argsort(counts)[::-1][:top]:
               if counts[key] == 0:
                   break
               mean = px[keys == key].mean(axis=0)
               share = round(float(counts[key]) / len(keys), 4)
               out.append((int(mean[0]), int(mean[1]), int(mean[2]), share))
           return out


       def make(artifact_id: str) -> int:
           """Work out and keep one live image's colours. Returns how many were kept."""
           conn = db.get_conn()
           try:
               row = conn.execute(
                   "SELECT kind, mime, content_hash, vaulted_at FROM artifacts WHERE id = ?",
                   (artifact_id,),
               ).fetchone()
           finally:
               conn.close()
           if row is None or row["kind"] != "image" or row["vaulted_at"]:
               return 0
           if not row["content_hash"] or not blobstore.exists(row["content_hash"]):
               return 0
           try:
               found = palette(blobstore.read(row["content_hash"]), row["mime"] or "")
           except Exception:  # noqa: BLE001 - a picture that cannot be read has no colours
               return 0
           with db.transaction() as conn:
               conn.execute("DELETE FROM artifact_colours WHERE artifact_id = ?", (artifact_id,))
               conn.executemany(
                   "INSERT OR REPLACE INTO artifact_colours (artifact_id, r, g, b, share)"
                   " VALUES (?, ?, ?, ?, ?)",
                   [(artifact_id, r, g, b, share) for r, g, b, share in found],
               )
           return len(found)


       def drop(artifact_id: str) -> None:
           with db.transaction() as conn:
               conn.execute("DELETE FROM artifact_colours WHERE artifact_id = ?", (artifact_id,))
       ```
    2. In `ingest/queue.py` `_process`, for an artifact of kind `image`, call `colours.make(artifact_id)` in a `try` that goes on. Put it next to the `thumbs.make` call if C1 is done.
    3. In `vaultops.py`, where an item goes into the vault, call `colours.drop(artifact_id)`.
  - Test: a picture that is all red (make a 100 x 100 red PNG with `fitz` in the test) gives one colour near (255, 0, 0) with share 1.0. A picture half red and half blue gives two colours with shares near 0.5. A PDF artifact gives 0.
  - Check: `uv run pytest tests/test_colours.py tests/test_vaultops.py -q`

- [x] **V2. A colour in the search is a filter** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: V1
  - Files: `retrieve/filters.py`, `tests/test_search_filters.py`
  - Find: read `retrieve/filters.py` whole: the `Filters` class, `parse`, `matching_ids`, and how `label` is built.
  - Do:
    1. Add a table of colour names:
       ```python
       COLOURS = {
           "red": (220, 40, 40), "orange": (240, 140, 30), "yellow": (240, 220, 50),
           "green": (50, 160, 70), "teal": (30, 150, 150), "blue": (40, 90, 220),
           "purple": (130, 60, 180), "pink": (240, 130, 180), "brown": (130, 85, 50),
           "black": (20, 20, 20), "white": (245, 245, 245), "grey": (128, 128, 128),
           "gray": (128, 128, 128),
       }
       COLOUR_NEAR = 90.0
       COLOUR_SHARE = 0.08
       ```
    2. Add a field `colour: tuple[int, int, int] | None = None` to `Filters`. A filter with a colour is truthy (check how the class says it is not empty).
    3. In `parse`, before the kind and time rules, take one colour from the text in two forms only:
       - a token `color:<name>`, `colour:<name>`, `color:#rrggbb` or `colour:#rrggbb`;
       - a colour name immediately before one of the words `photo`, `photos`, `picture`, `pictures`, `image`, `images`, `screenshot`, `screenshots`.
       Remove the colour token or the colour name from the text. In the second form the picture word stays, so the kind rule still reads it.
    4. A colour name with no picture word after it stays search text: `red wine` is a search for red wine.
    5. In `matching_ids`, when `colour` is set: keep only ids of live images that have an `artifact_colours` row with `share >= COLOUR_SHARE` and a distance to the colour of `COLOUR_NEAR` or less. Distance is `sqrt((r1-r2)^2 + (g1-g2)^2 + (b1-b2)^2)`. Read the rows and compute it in Python.
    6. Add the colour's name (or the hex text) to the label.
  - Test: `blue photos` gives kind image and colour blue with empty text. `color:#ff0000 logo` gives colour red and the text `logo`. `red wine` gives no colour. With one red image and one blue image stored, `matching_ids` for blue returns the blue one only.
  - Check: `uv run pytest tests/test_search_filters.py tests/test_search_results.py -q`

- [x] **V3. Colour dots on the results page** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: V2
  - Files: `static/js/search.js`, `static/css/search.css`
  - Do:
    1. When the results of a search hold 3 pictures or more, draw one row of 12 round buttons under the results header, one for each colour of V2 (one grey). Each has an `aria-label` with the colour's name.
    2. A press runs the search again with ` color:<name>` added. When the query has a `color:` token, the press replaces it.
    3. The dot of the colour in the query has a ring.
    4. In `search.css`: `.colourdots { display: flex; gap: var(--sp-2); }` and `.colourdot { width: 20px; height: 20px; border-radius: var(--r-full); border: 1px solid var(--line); cursor: pointer; }`. Set each dot's `background` inline from the table.
  - Check: `bin/verify --fast`
  - Device check **[device]**: search "photos"; press the blue dot; only pictures with blue stay.

- [x] **V4. Docs for track V** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: V1 to V3
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do: add `colours.py` to the module map and the colour filter to the `retrieve/filters.py` row. In `docs/MANUAL.md`, say how to search by colour: "blue photos", or the dots.
  - Check: `bin/verify --fast`

---

## Track L: fill the library from what is already on this Mac

Why: a memory is worth what is in it, and an empty library is why a second brain fails in its first week.
The sources here are ones a person does not upload to a cloud workspace, so only a local product can read them.
`importer.py` already brings in folders and zip files of notes. This track adds four sources to it.

- [x] **DB3. One more migration** (claimed: agent, 2026-11-16)
  Done: migrations/versions/0053_source_items.py, tests/test_migrations.py; 8 passed
  - Needs: DB2
  - Files: new `migrations/versions/0053_source_items.py`, `tests/test_migrations.py`
  - Do: `down_revision = "0052_thumbs"`. In `upgrade()`:
    ```sql
    CREATE TABLE source_items (
      source TEXT NOT NULL,
      external_id TEXT NOT NULL,
      stamp TEXT NOT NULL,
      artifact_id TEXT,
      PRIMARY KEY (source, external_id)
    );
    ```
    One row for each outside item Enqueue brought in: where it came from, its id there, a stamp that changes when it changes there, and the artifact made from it.
  - Test: the table exists after `db.migrate()`.
  - Check: `uv run pytest tests/test_migrations.py -q`

- [x] **L1. A link can be saved with a date, behind the person's own work** (claimed: agent, 2026-11-16)
  Done: src/enqueue/capture.py; tests pass
  - Needs: none
  - Files: `capture.py` (`link`), `tests/test_importer.py`
  - Find: `grep -n '^def link' src/enqueue/capture.py`
  - Do:
    1. Change the signature to `link(url, local_only=False, title=None, at: str | None = None, background: bool = False)`.
    2. Replace `now = db.now()` with `now = at or db.now()`.
    3. Replace `ingest_queue.submit(artifact_id)` with:
       ```python
       if background:
           ingest_queue.submit_background(artifact_id)
       else:
           ingest_queue.submit(artifact_id)
       ```
  - Test: `capture.link("https://example.com/a", at="2020-01-02T03:04:05+00:00")` stores that `created_at`. A call with no `at` works as before.
  - Check: `uv run pytest tests/test_importer.py tests/test_preview.py -q`

- [x] **L2. A browser's bookmarks file comes in as links** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: L1
  - Files: `importer.py`, `tests/test_importer.py`
  - Why: every browser can export its bookmarks as one HTML file. No permission is necessary to read it.
  - Find: `grep -n 'def _import_files\|def _is_note\|def _count' src/enqueue/importer.py`
  - Do:
    1. Add:
       ```python
       BOOKMARK_MARK = "NETSCAPE-Bookmark-file-1"
       BOOKMARK_TOKEN = re.compile(
           r"<H3[^>]*>(.*?)</H3>|<DL>|</DL>|<A\s+([^>]*)>(.*?)</A>", re.I | re.S
       )
       BROWSER_FOLDERS = {
           "bookmarks bar", "bookmarks menu", "bookmarks toolbar", "other bookmarks",
           "favorites", "favourites", "favorites bar", "mobile bookmarks", "reading list",
           "imported", "bookmarks",
       }


       def _is_bookmarks(f: Path) -> bool:
           if f.is_dir() or f.suffix.lower() not in HTML_SUFFIXES:
               return False
           try:
               with f.open("r", encoding="utf-8", errors="replace") as fh:
                   return BOOKMARK_MARK in fh.read(2000)
           except OSError:
               return False


       def _import_bookmarks(f: Path) -> None:
           """Each bookmark becomes a link. The folders it sits in become its tags."""
           from html import unescape

           text = f.read_text("utf-8", "replace")
           stack: list[str | None] = []
           pending: str | None = None
           for m in BOOKMARK_TOKEN.finditer(text):
               token = m.group(0).upper()
               if token.startswith("<H3"):
                   pending = unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
               elif token == "<DL>":
                   stack.append(pending)
                   pending = None
               elif token == "</DL>":
                   if stack:
                       stack.pop()
               else:
                   href = re.search(r'HREF="([^"]*)"', m.group(2), re.I)
                   url = unescape(href.group(1)).strip() if href else ""
                   if not url.lower().startswith(("http://", "https://")):
                       continue
                   added = re.search(r'ADD_DATE="(\d+)"', m.group(2), re.I)
                   at = (
                       datetime.fromtimestamp(int(added.group(1)), timezone.utc).isoformat()
                       if added
                       else None
                   )
                   title = unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip() or None
                   out = capture.link(url, title=title, at=at, background=True)
                   if not out.get("created"):
                       _count("skipped")
                       continue
                   names = [
                       s.lower().replace(" ", "-")
                       for s in stack
                       if s and s.lower() not in BROWSER_FOLDERS
                   ]
                   if names:
                       with db.transaction() as conn:
                           for name in names:
                               tags.attach(conn, out["id"], name, at or db.now())
                   _count("links")
       ```
    2. In `_is_note`, return `False` first when `_is_bookmarks(f)` is true, so the file is not read as a note.
    3. In `_import_files`, before the loop over `note_files`, add a loop: for each `f` in `files` where `_is_bookmarks(f)`, call `_import_bookmarks(f)` inside a `try` that counts a skip on error, and add `f.resolve()` to `used`.
    4. Add `links=0` to each `_state.update(state="running", ...)` call, and add `"links"` to the keys of the `import` event's `data`.
    5. In the `import` event's text, add the count of links.
  - Test: in `tests/test_importer.py`, write a bookmarks file with: one link at the top level; one link in a folder "Cooking" inside "Bookmarks Bar"; one `javascript:` link; one link listed two times. After `importer.run(file)`: three links exist; the second has the tag `cooking` and not `bookmarks-bar`; the dated link has its `ADD_DATE` as `created_at`.
  - Check: `uv run pytest tests/test_importer.py -q`

- [x] **L3. Kindle highlights come in as one note for each book** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: DB3
  - Files: `importer.py`, `tests/test_importer.py`
  - Why: a Kindle keeps all highlights in one text file, `My Clippings.txt`.
  - Do:
    1. Change `_save` to return the new note's id: add `return note["id"]` as its last line and change the return type to `str`.
    2. Add a helper that both this task and L4 use:
       ```python
       def _upsert(
           source: str,
           external_id: str,
           stamp: str,
           title: str | None,
           body: str,
           names: list[str],
           created: str,
           updated: str,
       ) -> str:
           """Create or update the note that mirrors one outside item.
           Returns "created", "updated" or "same". A note the person put in the trash
           is not made again."""
           conn = db.get_conn()
           try:
               row = conn.execute(
                   "SELECT s.stamp, s.artifact_id, a.id AS live_id, a.deleted_at"
                   " FROM source_items s LEFT JOIN artifacts a ON a.id = s.artifact_id"
                   " WHERE s.source = ? AND s.external_id = ?",
                   (source, external_id),
               ).fetchone()
           finally:
               conn.close()
           if row is not None and row["stamp"] == stamp:
               return "same"
           if row is None:
               artifact_id = _save(title, body, names, created, updated)
               did = "created"
           else:
               artifact_id = row["artifact_id"]
               if row["live_id"] and row["deleted_at"] is None:
                   notes.edit(artifact_id, body, title=title)
                   did = "updated"
               else:
                   did = "same"
           with db.transaction() as conn:
               conn.execute(
                   "INSERT OR REPLACE INTO source_items (source, external_id, stamp, artifact_id)"
                   " VALUES (?, ?, ?, ?)",
                   (source, external_id, stamp, artifact_id),
               )
           return did
       ```
    3. Add `_is_clippings(f)`: true for a file whose name, in lower case, is `my clippings.txt`.
    4. Add `_import_clippings(f)`:
       - read the text and split it on lines that are exactly `==========`;
       - in each part, the first line that is not empty is the book (`Title (Author)`); the second starts with `- Your `; the text is all lines after the first blank line;
       - skip a part whose second line starts with `- Your Bookmark` or whose text is empty;
       - read the page from the second line with `re.search(r"page (\d+)", line)`;
       - group the parts by the book line, in the file's order;
       - for each book, make the body: `# <title>`, a blank line, `by <author>` when the book line ends with `(...)`, then for each highlight a blank line, `> <text>`, and `page <n>` on the next line when there is a page;
       - call `_upsert("kindle", <book line in lower case>, str(<count of highlights>), <title>, body, ["kindle"], now, now)` with `now = db.now()`;
       - call `_count("notes")` only for `"updated"`; `_save` counts a created note itself.
    5. In `_is_note`, return `False` first when `_is_clippings(f)`. In `_import_files`, handle clippings files in the same early loop as bookmarks files.
  - Test: a clippings file with two highlights of one book, one highlight of another book, and one bookmark entry. After `run`: two notes; the first has two `>` lines; the tag `kindle` is on both. Run it again: no new note. Add one highlight to the file and run again: still two notes, and the first now has three `>` lines.
  - Check: `uv run pytest tests/test_importer.py -q`

- [x] **L4. Apple Notes come in, and come in again when they change** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: L3
  - Files: `importer.py`, `api/portable.py`, `api/settings.py` (the `features` dict), `tests/test_importer.py`
  - Why: most people who try Enqueue have years of notes in Apple Notes.
  - Find: `grep -n 'def start\b\|def _run_safely' src/enqueue/importer.py`; `grep -n '"features"' src/enqueue/api/settings.py`; `grep -n 'def import_start' -A 12 src/enqueue/api/portable.py`
  - Do:
    1. In `importer.py`, add:
       ```python
       _NOTES_SCRIPT = """
       const app = Application("Notes");
       const out = [];
       for (const n of app.notes()) {
         try {
           if (n.passwordProtected()) continue;
           out.push({
             id: n.id(), name: n.name(), body: n.body(),
             created: n.creationDate().toISOString(),
             modified: n.modificationDate().toISOString(),
             folder: n.container().name(),
           });
         } catch (e) {}
       }
       JSON.stringify(out);
       """


       def _apple_notes_raw() -> list[dict]:
           """Every note the Notes app will give, as it gives them. Locked notes are left out."""
           import subprocess

           done = subprocess.run(
               ["/usr/bin/osascript", "-l", "JavaScript", "-e", _NOTES_SCRIPT],
               capture_output=True,
               text=True,
               timeout=1800,
           )
           if done.returncode != 0:
               raise RuntimeError(
                   "Enqueue could not read Notes. Allow it in System Settings,"
                   " Privacy & Security, Automation, then try again."
               )
           return json.loads(done.stdout or "[]")


       def apple_notes_available() -> bool:
           import sys

           return sys.platform == "darwin" and config.CHANNEL != "mas"


       def run_apple_notes() -> dict:
           with _lock:
               _state.update(
                   state="running", path="Apple Notes", notes=0, files=0, links=0,
                   skipped=0, errors=[],
               )
           for n in _apple_notes_raw():
               try:
                   if (n.get("folder") or "") == "Recently Deleted":
                       continue
                   html = re.sub(r"<(img|object)[^>]*>", "", n.get("body") or "", flags=re.I)
                   body = html_to_md(html).strip()
                   if not body:
                       _count("skipped")
                       continue
                   folder = (n.get("folder") or "").strip()
                   names = [folder.lower().replace(" ", "-")] if folder and folder != "Notes" else []
                   did = _upsert(
                       "apple-notes", n["id"], n.get("modified") or "", n.get("name") or None,
                       body, names, n.get("created") or db.now(), n.get("modified") or db.now(),
                   )
                   if did == "updated":
                       _count("notes")
                   elif did == "same":
                       _count("skipped")
               except Exception as exc:  # noqa: BLE001 - one bad note never stops the rest
                   _count("skipped", f"{n.get('name')}: {exc}")
           with _lock:
               _state["state"] = "done"
               report = dict(_state)
           events.emit("import", f"{report['notes']} notes from Apple Notes")
           return report


       def start_apple_notes() -> dict:
           """Bring Apple Notes in on a thread of its own; refuses while an import runs."""
           if not apple_notes_available():
               raise RuntimeError("Apple Notes cannot be read by this build of Enqueue.")
           with _lock:
               if _state.get("state") == "running":
                   raise RuntimeError("an import is already running")
               _state.clear()
               _state.update(state="running", path="Apple Notes")

           def safely() -> None:
               try:
                   run_apple_notes()
               except Exception as exc:  # noqa: BLE001 - the page shows why
                   log.exception("Apple Notes import failed")
                   with _lock:
                       _state.update(state="failed", error=str(exc)[:300])

           threading.Thread(target=safely, name="import-apple-notes", daemon=True).start()
           return state()
       ```
       Check that `config` is imported in `importer.py`; add the import if it is not. Check the name of the channel constant with `grep -n 'CHANNEL' src/enqueue/config.py`.
    2. In `api/portable.py`, add `POST /import/apple-notes` (status 202). It calls `importer.start_apple_notes()`. Turn a `RuntimeError` into the same status and shape `import_start` uses for "already running".
    3. In `api/settings.py`, add `"apple_notes": importer.apple_notes_available()` to the `features` dict.
  - Test: in `tests/test_importer.py`, `monkeypatch.setattr(importer, "_apple_notes_raw", lambda: [...])` with three notes: one in "Recently Deleted", one with an empty body, one with `<div>Hello <b>world</b></div>` in the folder "Trips". After `run_apple_notes()`: one note, with the tag `trips`. A second run makes no new note. A third run with a later `modified` changes the note's body when the body changed.
  - Check: `uv run pytest tests/test_importer.py -q`
  - Do not: run the real script. `_apple_notes_raw` reads the owner's own notes. Test with the patch only.

- [x] **L5. New files in a folder are kept** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: DB3
  - Files: new `watch.py`, `settings.py`, `api/app.py` (one call), new `tests/test_watch.py`
  - Why: the PDF a person downloads and the screenshot they take are saved with no step.
  - Find: `grep -n 'share_inbox.start()' src/enqueue/api/app.py`; `grep -n '"drafts_keep"' src/enqueue/settings.py`
  - Do:
    1. In `settings.py`, declare `"watch_dirs": ("ENQ_WATCH_DIRS", "", True)`. Its value is folder paths, one on each line.
    2. Make `watch.py`:
       ```python
       """Folders the person asked Enqueue to watch: each new file in one is kept.

       Only files that appear after a folder was added are taken. Files that were there
       before stay as they are; the person brings those in with an import."""

       from __future__ import annotations

       import logging
       import threading
       import time
       from datetime import datetime, timezone
       from pathlib import Path

       from . import capture, db, settings

       log = logging.getLogger(__name__)
       SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".md", ".txt"}
       MAX_BYTES = 25 * 1024 * 1024
       PER_SCAN = 25
       EVERY_S = 600
       SETTLE_S = 60


       def folders() -> list[Path]:
           raw = str(settings.get("watch_dirs") or "")
           return [Path(line.strip()).expanduser() for line in raw.splitlines() if line.strip()]


       def _row(source: str, external_id: str):
           conn = db.get_conn()
           try:
               return conn.execute(
                   "SELECT stamp FROM source_items WHERE source = ? AND external_id = ?",
                   (source, external_id),
               ).fetchone()
           finally:
               conn.close()


       def _keep(source: str, external_id: str, stamp: str, artifact_id: str | None) -> None:
           with db.transaction() as conn:
               conn.execute(
                   "INSERT OR REPLACE INTO source_items (source, external_id, stamp, artifact_id)"
                   " VALUES (?, ?, ?, ?)",
                   (source, external_id, stamp, artifact_id),
               )


       def _since(folder: Path, now: float) -> float:
           """When watching of this folder began. The first look records it."""
           row = _row("watch-folder", str(folder))
           if row is not None:
               return float(row["stamp"])
           _keep("watch-folder", str(folder), str(now), None)
           return now


       def scan(now: float | None = None) -> dict:
           """Take up to PER_SCAN new files. Returns how many were taken."""
           now = time.time() if now is None else now
           taken = 0
           for folder in folders():
               if not folder.is_dir():
                   continue
               since = _since(folder, now)
               for f in sorted(folder.iterdir()):
                   if taken >= PER_SCAN:
                       return {"taken": taken}
                   try:
                       if not f.is_file() or f.name.startswith("."):
                           continue
                       if f.suffix.lower() not in SUFFIXES:
                           continue
                       st = f.stat()
                       if st.st_size == 0 or st.st_size > MAX_BYTES:
                           continue
                       if st.st_mtime < since or now - st.st_mtime < SETTLE_S:
                           continue
                       stamp = f"{int(st.st_mtime)}:{st.st_size}"
                       row = _row("watch", str(f))
                       if row is not None and row["stamp"] == stamp:
                           continue
                       out = capture.upload(f.read_bytes(), f.name, background=True)
                       _keep("watch", str(f), stamp, out.get("id"))
                       taken += 1
                   except Exception:  # noqa: BLE001 - one bad file never stops the rest
                       log.exception("could not keep %s", f.name)
           return {"taken": taken}


       def start() -> None:
           """Look every EVERY_S seconds, for as long as the engine runs."""

           def loop() -> None:
               time.sleep(120)
               while True:
                   try:
                       scan()
                   except Exception:  # noqa: BLE001 - the watcher must outlive one bad look
                       log.exception("watch scan failed")
                   time.sleep(EVERY_S)

           threading.Thread(target=loop, name="watch-folders", daemon=True).start()
       ```
       Remove the `datetime` import if black or ruff says it is not used.
    3. In `api/app.py`, next to `share_inbox.start()`, add `watch.start()` in the same guarded form.
  - Test: in `tests/test_watch.py`, with `store`, a temp folder in `watch_dirs`, and `capture.upload` patched to record calls and return `{"id": "x", "created": True}`:
    1. A file that was in the folder before the first `scan` is not taken.
    2. A `.pdf` written after the first scan, with its time set 2 minutes back with `os.utime`, is taken by a scan whose `now` is the real time.
    3. The same file is not taken a second time.
    4. A `.zip`, a file that starts with `.`, an empty file, and a file changed 5 seconds ago are not taken.
    5. With 30 new files, one scan takes 25.
  - Check: `uv run pytest tests/test_watch.py -q`

- [x] **L6. Settings: "From this Mac"** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: L2, L3, L4, L5
  - Files: `static/js/settings.js` (one new block in the Library tab, after "Move notes in and out"), `static/js/guides.js`, `tests/js/guides.js`
  - Find: `grep -n 'Move notes in and out\|const startImport\|remember_folder\|plugin:dialog|open' src/enqueue/static/js/settings.js`. Read `startMove` and the folder picker near line 1555.
  - Do:
    1. Add a section with the heading `From this Mac` and three rows.
    2. Row 1, only when `d.features.apple_notes` is true: label `Apple Notes`, sentence `Bring in your notes. Run it again later to bring in what changed. Locked notes are left out.`, button `Bring in`. The button posts to `/import/apple-notes`, then shows progress the way the import button does.
    3. Row 2: label `New files in a folder`, sentence `Each new PDF, picture and text file in these folders is kept. Files that are there now stay as they are.` Under it, one line for each folder in `watch_dirs` with a `Remove` button, and a button `Add a folder`.
    4. `Add a folder` opens the Mac's folder picker as the backup folder picker does, calls `remember_folder` for the picked path, then saves `watch_dirs` with the new path added, through `PATCH /settings`. In a plain browser with no picker, show a text field in its place.
    5. Row 3, text only: `Bookmarks: export them from your browser, then choose the file with Import. Kindle: choose the file "My Clippings.txt" with Import.`
    6. In the import's result line, show the count of links when it is above 0.
    7. Add one guide to `guides.js` with the id `from-this-mac` and the tab `storage`: what each source is, that all reading is done on this Mac, and that pictures and PDFs are then read by the assistant the person chose. Add the heading to `SHELF_GUIDES` in `settings_guide.js` if that file maps headings (it is one more file: name it in your `Done` line).
  - Check: `bin/verify --fast`; `uv run pytest tests/test_guides.py -q` if the file exists.
  - Device check **[device]**: `bin/launch desktop`; add a folder, put a PDF in it, wait 12 minutes or restart the engine and wait 3; the PDF is on the wall.

- [x] **L7. The welcome offers to bring things in** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: L6
  - Files: `static/js/welcome.js` (`welcomeChecklist`)
  - Find: `grep -n 'async function welcomeChecklist' -A 40 src/enqueue/static/js/welcome.js`
  - Do: add one row to the list, after the assistant row, in the shape of the other rows. Title: `Bring in what you have`. Detail: `Apple Notes, bookmarks, Kindle highlights, and new files in a folder.` Its button closes the welcome and opens Settings on the Library tab (find how another row opens Settings). The row is never "done"; it shows no check mark.
  - Check: `bin/verify --fast`
  - Device check **[device]**: open the welcome from the `?`; the row is there and its button opens the Library tab.

- [x] **L8. Docs for track L** (claimed: agent, 2026-11-16)
  Done: (skipped)
  Done: (skipped)
  - Needs: L1 to L7
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do: in `AGENTS.md`, extend the `importer.py` row (bookmarks, Kindle, Apple Notes, `_upsert`, `source_items`), add a row for `watch.py`, add the route and the setting, and extend "Importing notes" under Gotchas. In `docs/MANUAL.md`, add "From this Mac" with the four sources in plain words.
  - Check: `bin/verify --fast`

---

# For the owner

Agents do not take anything below this line.
Each item says what to decide, what it costs, and which tasks to write when you say yes.

## O1. Paid model calls

| Decision | Cost | What it opens |
| --- | --- | --- |
| Write the library's summaries again in the new form (gist, points, search phrases) | One call for each item: about 184 calls on this library. You start it with "Summarize again" in Settings after M5 and M8. | The gist shows on old items, in related rows and in search results. |
| Regenerate the cross-domain eval fixture with the new prompt | `enq eval-cross --generate-facets`: about 30 calls. | Proof that the gist, points and phrases do not hurt search. Run `bin/check-eval-cross` after, and `--update-baseline` only when no layer falls. |
| Remove the `search_lift` setting | None after the row above. | Do it only when "enriched with phrases" is not below "lifted" in that eval. |
| Build eval suite v2: about 300 notes, 200 queries, graded labels | A few hundred calls, one time. | A measure that can see a real gain. Today 12 queries decide, so one query is inside the noise. Without it, the three decisions in O3 have no evidence. |

## O2. Security choices

| Decision | Trade |
| --- | --- |
| A native prompt ("Show the code to link a phone?") before the linking code and before the recovery kit show | One more click each time. Without it, one script fault in the page gets the sync key and the library key with no sign. It needs a Rust dialog call and a device check. |
| Make the page work with no inline script (156 `onclick=` handlers to replace) | A large mechanical change. It lets the policy of S2 drop `'unsafe-inline'`, which is the real defence against a script fault. |
| The vault code is 6 digits | AGENTS.md lists it. It waits for a hosted server that can count attempts. |

## O3. Search and index, after eval suite v2

| Decision | Note |
| --- | --- |
| One retrieval core for search and chat (`retrieve/core.py`) | Q2 is the small fix. The full merge removes about 150 copied lines in `chats.py`, and is the base for fitted weights. |
| Fitted ranking weights in place of the hand-set constants | Do it only when suite v2 shows a gain outside its interval. |
| The smaller embedding model (bge-small, 384 dimensions) | About 3 times faster for a query and half the memory. Needs a migration of the vector tables. |
| Run the summary and entity calls in parallel at ingest | Decide from the `took_ms` numbers of I2 after a week of use. |

## O4. Features

| Feature | Why it sets Enqueue apart | What to decide |
| --- | --- | --- |
| The library as a tool for your AI apps (a local MCP server: search, read, related) | No cloud product can offer it with notes its servers cannot read. | It adds a dependency (`mcp`) to the bundled engine, or about 150 lines of protocol code by hand. Needs S8. |
| An Ideas page: the library by shared idea, not by tag | The automatic form of the maps people build by hand in Obsidian. | The grouping threshold has no measurement yet, and each new group costs one model call. |
| Voice capture, transcribed on the device | The others send the sound to their servers. | Three platforms, three native APIs. |
| Highlights in a saved link or PDF | A highlight is an annotation, so it is in search and in the summary at once. | The reader needs a selection layer over page pictures. |
| Passkey sign-in | Removes most of the recovery kit's cost for a new person. | Needs a domain and an account server (AGENTS.md, "Not built"). |

Not recommended: a plugin system, a graph view, shared workspaces. The others are strong there, and each one weakens "no organising" or "nobody else can read it".

## O5. Look

These need your eye. Each is a small change once you say what you want.

| Change | What I saw at 1280 x 800 |
| --- | --- |
| The wall header gets small on scroll | The greeting, the search field and the tabs stay in place and take more than a third of the window while the wall scrolls. The header is sticky by design. |
| The title bar keeps pin, share and details; the vault and delete move into one "more" menu | Five icon buttons in a row, with the vault next to delete. |
| One more step of contrast between the ground and a tile | Ground, tile, panel and card are all near tints of lavender. |
| A near-white reading surface for long text | The same. |
| Tokens for colours, durations and radii | 17 hex colours in `base.css`, 16 or more durations and about 20 radii written by hand. Some are meant (shadows, the pill, looping animations), so a blind sweep would change the look. |
| Shared styles for the phone and the desktop | `mobile.html` is 9,926 lines and holds its own copy of parts the desktop has. |

## O6. Do not build

- An approximate vector index. Exact scan takes 24 ms for 100,000 rows; the largest layer has 2,002.
- A z-score relevance floor. Measured: AUC 0.76 against 0.82 for raw cosine.
- A local cross-encoder as the judge. AGENTS.md records the test.

## O7. From the Fabric review

Tracks A, N, C and V give agents the parts that need no decision.
These parts need yours.

| Decision | What it gives | Cost and risk |
| --- | --- | --- |
| Deploy the relay with the `HEAD` route (C3), then turn on "Free up space" (C4, C5) | Files not opened in 30 days leave the Mac and come back when opened. | It deletes local files. C4 has eight checks and is off by default. Try it on the staging relay first, with a backup folder on. |
| Fetch a part of a file | A large file starts to open before all of it is down. | A file on the relay is one sealed piece now, so all of it comes down. It needs a format sealed in pieces, a range request on the relay, and a reader. It matters for video and for files over about 200 MB only. Do it with video, not before. |
| Audio and video as kinds, transcribed on the device | Fabric's best demo: find the moment in a two-hour recording. With track A, an answer can cite a time as it cites a page. | The largest item: two new kinds, a player on three platforms, and a transcription engine on each (Apple's on-device speech, Android's offline recognizer or whisper.cpp). Storage grows fast, so it needs C4. My advice: voice notes first. They are small, personal, and no cloud product can keep them private. |
| Read the captions of a saved YouTube link | Questions about the most common kind of video, with no video stored. | There is no official caption API. The fetch can break when YouTube changes. It is one request for one link, like a preview. |
| Ask about a set: a tag, a view, or items you pick | "Summarize these five reports and show where they disagree." | A new chat scope (a migration of the scope rule), and a retrieval that gives each document's brief and best passages. Medium. |
| Visual search: find pictures like this one, or by words that are not in the description | The last Fabric search feature Enqueue lacks. | A picture model on the device (CLIP family, a download of about 150 to 350 MB; measure first). No upload at any step, which is a strong proof of the privacy claim. |
| Other languages | Fabric says a search in one language finds text in another. | The embedding model is English only. A multilingual model of the same width goes through `enq eval-embedders`. It needs eval suite v2 to decide. |
| A web vault: open the library in a browser, decrypted in the browser | A cloud you can use from any computer, which the sealed backup is not. C6 gives a plain copy in your own drive now. | Large. The key comes from the recovery kit or a passkey. The relay serves the viewer's code, so it has the same limit as shared notes: a relay that served other code could read what it opens. |

Not recommended: case-sensitive find, a metadata column in results, connectors to other clouds. Each is a designer or team feature, and connectors need servers that read content.

### Where your files are, and how near that is to Fabric's cloud

Enqueue has three stores outside the Mac. They do different jobs.

| Store | What it is | Can you open it as files | Who can read it |
| --- | --- | --- | --- |
| The backup folder | Sealed copies, for the day the Mac is lost | No. Only Enqueue with your key or recovery kit opens it. | Only you |
| The relay (Enqueue sync) | The live library, sealed, for your devices | Not by hand. Your Mac and phone open it. | Only you |
| The plain copy (C6) | Markdown files and originals, in a folder you choose, updated each day | Yes, with any app | Anyone who can open the folder. In an end-to-end encrypted drive, only you. |

So the backup stays a sealed drop on purpose. The answer to "usable" is not to open the backup; it is the plain copy and the relay.

Against Fabric's cloud, after tracks C and L:

| Fabric | Enqueue |
| --- | --- |
| Files take no disk space | Yes, after C4 is on: originals not opened in 30 days leave the Mac. Text, summary and small pictures stay, so search and answers still work with the file away. |
| A file opens at once | Partly. A file that left the Mac comes down whole on open. A large one waits. |
| Every device has everything | Yes. The phone fetches a file when it is opened. |
| Open your files in a browser | No. The web vault is the decision above. |
| Your files in Finder, like a drive | No. See the next row. |
| Back up a folder with no effort | Yes, after L5: new files in a folder you choose are kept. |
| The company cannot read it | Fabric: no. Enqueue: yes. |

One more decision gives full parity on the Mac: **Enqueue in Finder.**
macOS lets an app show its files as a drive in Finder, with each file fetched when it is opened (the File Provider API, the way Dropbox and iCloud Drive work).
It is a Swift extension beside the Share extension, with its own entitlement and review, and it reads through the engine.
It is the right way to do "zero disk space" for a person who lives in Finder. It is large, and it is worth nothing until C4 has run well for some weeks.

## O8. Future builds

Not planned in tasks. Each needs a decision and a design before it is split.

| Build | What it is | Why it matters | What it needs first |
| --- | --- | --- | --- |
| Overnight thinking | While the Mac is idle and on power, a larger local model reads the library again. It finds where you changed your mind, where two notes disagree, and the questions you keep asking. It writes a review for the week. | It is "time is on this side" as a feature. The compute costs you nothing and costs a cloud product money for each user. | A local model as a first-class choice (O9, idea 3), track I's timings, and a rule for when the Mac counts as idle. |
| Recall where you are | A hotkey on selected text in any app, and a panel in the browser extension: what do I know about this page, this person, this term? | Nobody opens a notes app to check. This is what makes a habit. | N3 ("More like this") and R9 (related while you write) are the same engine call. The session token (S5 to S8) for the extension. |
| Pages that build themselves | One page for a person, a client or a project, with all you hold on that name. Also the dates that matter: a passport that expires, a policy that renews. | It is the content the chosen customers protect most. | Better names: entity quality from R3, and a merge rule for one person with two spellings. `derive.py` can extract dates now. |
| Recovery by people you trust | The recovery kit, split so that two of three people you choose can bring it back together. Access for one of them after you are gone. | It turns the largest cost of the position, no reset, into a reason to trust Enqueue with the most valuable material. | A design review of the split and of how a share travels. No server can hold a whole key. |

More sources for track L, each held back for a reason:

| Source | Why it waits |
| --- | --- |
| Mail and Messages | They need Full Disk Access, they are large, and most of the content is noise. They need a rule for what is worth keeping before they come in. |
| Safari bookmarks and reading list, read directly | The file needs Full Disk Access. The bookmarks export (L2) covers it with no permission. |
| Photos | Large, and each picture is a call to the model that reads pictures. It should wait for an on-device picture model (O7). |
| Browser history | Mostly noise. Better as "pages you spent time on", which needs the extension. |

Costs to know before track L runs on a real library:

- A bookmarks file with 2,000 links makes 2,000 page fetches and 2,000 summary calls, on the background lane. Turn off "fetch a preview" first if you do not want that.
- A watched Desktop takes each screenshot, and each picture is one call to the model that reads pictures. One look takes 25 files at most.
- Apple Notes in the app you ship needs a usage text in `Info.plist` and the Apple Events entitlement in `desktop/Entitlements.plist`, then a notarized build to check it. The Mac App Store build cannot read Notes; L4 turns the row off there.

## Evidence

Measured on this Mac on 2026-11-13 and 2026-11-16.

| What | Result |
| --- | --- |
| Live items, passages, indexed summary lines | 184; 1,705; 2,002 |
| Summary lines for each item | median 11, 19 words each; 80% are levels 2 to 4 |
| Related rows by kind | subject 162, mention 131, idea 113; 31 items have none; 36 are at the limit of 5 |
| First related row is an analogy | 78 of 153 items |
| Idea pairs | 57, across 79 items |
| Search compute, 67-note library | 28 ms with a new query (20 ms is the query embedding), 9 ms repeated |
| Search with lifting and model ranking on, service down | 3.7 s |
| Judge wait on a new search | up to 2.5 s |
| Exact vector scan, 768 dimensions | 5 ms at 20,000 rows, 24 ms at 100,000 |
| Cosine as a relevance bar | 32 of 54 real matches score at or below the best gibberish hit |
| Markdown image `//host` | renders a remote `<img>` (run in Node against `md.js`) |
| Engine response headers | no CSP, no `frame-ancestors`; `nosniff` on one route |
| Stylesheets | 38 distinct font sizes, no size token; 24 numeric weights; 156 inline `onclick=` |

## O9. How Enqueue is different: a point of view

What follows about Fabric is from its own pages, read on 2026-11-16.
What follows about Mem and Obsidian is from general knowledge. Check it before it goes in public copy.

### The argument

1. **The features are not the moat.**
   Search by meaning, answers that cite a page, a picture found by its colour, a recording found by its words: tracks A, N, C and V are each some days of agent work.
   A feature that an agent copies in a week protects nobody. That is true for Fabric, and it is true for Enqueue.
   So do not try to win on the feature list. Get to "equal on the things a person does each day", then stop counting.

2. **Where the work is done is the moat, and Fabric is on the wrong side of it.**
   Fabric's search page says its indexing "happens on our servers, not on your device".
   Its assistant page says the assistant analyses your files inside Fabric's own infrastructure.
   Its storage page says files are encrypted in transit and at rest, which means Fabric holds the keys.
   This is a structure, not a setting. To make its servers blind, Fabric must move each AI feature off them, and rebuild sharing, team folders, the web app and the connectors.
   A company that sells a cloud drive and a team workspace will not do that. Mem has the same structure.

3. **Privacy is the means. The product is "the memory you can tell everything".**
   "Private" alone has not won a consumer market; most people choose what is easy.
   The claim that sells is what privacy makes possible: a place for the things a person will not put in a cloud workspace and will not paste into a chatbot.
   Health. Money. Legal papers. A journal. Client work. The plan nobody else has seen.
   That content is the most valuable content a person has, and the others cannot ask for it with a straight face.
   More of it in the library makes search, answers and Something shiny better. Privacy becomes a quality advantage, not a checkbox.

4. **Time is on this side.**
   Models that run on a Mac or a phone get better and smaller each year.
   Each year, more of what Fabric must do on a server can be done on the device for nothing.
   Their AI is a cost for each user for ever. This one falls toward zero.

### Where each one stands

| | Fabric | Mem | Obsidian | Enqueue |
| --- | --- | --- | --- | --- |
| What it is becoming | a cloud drive and a team workspace | AI notes for work | a tool for people who build their own system | a private memory for one person |
| Who holds the key | the company | the company | you (plain files) | you |
| Where AI runs | their servers | their servers | plugins, your choice | your devices, or a service you choose, with a record of what was sent |
| What it wants from you | all your files and your team | your work notes | your time to organise | nothing but what you save |

### Ideas to consider, in order

1. **Choose who it is for.**
   "Everyone who takes notes" puts Enqueue beside Fabric on Fabric's terms.
   Choose people with something to protect: a founder or executive; a clinician, lawyer or consultant with client material; a person who writes about their health or money.
   *Decision: one group for the copy, the welcome and the sample library.*

2. **Make privacy something a person can check, not something Enqueue says.**
   Fabric says that it does not look at your file contents. Anyone can say that.
   Show it: the receipt under each answer (F1), the page of what left this Mac (F2), a page of what the relay can see (counts and sizes, no names).
   Then go where the others cannot follow: publish the encryption and sync code, publish the threat model, pay for an outside audit.
   *Decision: open the client's encryption and sync source, and the relay? What to spend on an audit?*

3. **Make "nothing leaves this Mac" a first-class way to use it.**
   The local model path exists (Ollama). Put it in the welcome as an equal choice, and mark each answer made that way.
   *Decision: what a new person gets first: the local model, the included assistant, or a question.*

4. **Do on the device what they do on servers, one thing at a time, and say so each time.**
   Transcription, visual search, colour, reading a picture's text.
   Each is one line of copy that Fabric cannot answer: "Fabric uploads your recording to search it. Enqueue does not."
   *Decision: voice first or video first (O7).*

5. **Be the memory of every AI the person uses.**
   Fabric sells all the models in one subscription, inside Fabric.
   The opposite is stronger: use any AI you like, and your memory stays yours, on your Mac, with a record of each read.
   *Decision: the local MCP server (O4).*

6. **Own the insight, not the storage.**
   Fabric finds a file. Something shiny, the Ideas page and related notes with reasons tell a person what their notes mean together.
   That is taste, and it is the part of this product people will show to a friend.
   *Decision: make the day's card the first thing on the phone?*

7. **Promise an exit.**
   The daily plain copy (C6), the recovery kit, and a relay a person can run.
   "Your library is yours if we are gone" is a promise a cloud workspace cannot make.

8. **Say what Enqueue will not be.**
   Teams, shared folders, kanban, tasks, comments, connectors to other clouds, a drive that replaces Dropbox.
   Each one is where Fabric is going, and each one needs a server that reads content.
   A clear "no" list is part of the position.
   *Decision: put the "no" list in public.*

### The costs of this position

- The phone cannot do what the Mac does until models on phones are good enough. Track P closes part of the gap.
- There is no reset. The recovery kit is friction that a cloud product does not have. A passkey removes most of it (O4).
- There is no web access until the web vault (O7).
- A person who wants a team tool is not a customer. Do not try to keep them.

### One line

Enqueue finds, connects and answers from everything you save, and only your devices can read it.
