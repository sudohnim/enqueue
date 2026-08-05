# Feature: Tags — implementation plan

This file is the whole plan for adding user tags. It is written to be implemented by an
LLM that does not know this codebase. Do not improvise. Do every step in order. The design
rationale is in `docs/decisions/tags-analysis.md`; you do not need to read it to implement,
but do not contradict it.

(The previous contents of this file were a historical progress log; it lives in git.)

---

## 0. The one rule you must never break

**Never prompt for a tag at capture time. Never make a tag required.** Tags are an
optional, later act on an artifact that already exists. If any step seems to require asking
for a tag before saving something, you did it wrong: stop and re-read.

## 1. Orientation

Enqueue is a local-first macOS app. A Python engine (FastAPI) serves an HTML interface and
binds to `127.0.0.1:8787` only. You will touch:

| Path | What it is |
| --- | --- |
| `src/enqueue/migrations/versions/` | Alembic migrations. You add one. |
| `src/enqueue/tags.py` | NEW. All tag read/write logic. You create it. |
| `src/enqueue/api.py` | FastAPI endpoints. You add tag endpoints and one filter param. |
| `src/enqueue/retrieve/candidates.py` | `search_results()` — the search path. |
| `src/enqueue/static/museum.html` | The entire UI. One file, inline `<style>` + `<script>`. |
| `tests/` | Pytest. Mirror `tests/test_trash.py` for style and the `store` fixture. |

### Running and checking

```bash
bin/relaunch        # rebuild + launch the app; refuses to start if the HTML fails to parse
uv run pytest -q    # tests must stay green; the baseline is 226 passing
uv run black src/ tests/   # Python formatting; must be clean
```

`museum.html` contains NUL bytes. `rg` treats it as binary and prints nothing unless you
pass `-a`. **Always use `rg -a` on it.**

### How to work these steps

- **One checkbox per commit. Never batch.** Commit message: `tags: <what the step did>`.
- After every checkbox: `uv run pytest -q` is green and `bin/relaunch` still starts.
- Every step is idempotent. If the target state already exists, tick the box and move on.
- `[AGENT]` = do it. `[HUMAN]` = stop and hand over.
- No em dashes in code, comments, or copy. Use a plain dash.
- Never commit unless a step says the human commits; here the human commits after review.
  Leave each step as a clean working change.

### House rules that are easy to violate

- Tags are user-authored and permanent (they survive `enq rebuild`), so they are SOURCE
  tables, never derived. Do not put tags in `chunks`, `facets`, `fts_*`, or `vec_*`.
- Store one canonical tag name: lowercased and trimmed. Match is exact. No fuzzy matching.
- Conversations (`chats`) cannot be tagged in this feature. Only rows in `artifacts`.

---

## PHASE T1 — Data model (two source tables)

- [x] `[AGENT]` Create `src/enqueue/migrations/versions/0011_tags.py`. Copy the exact shape
      of `0010_sqlite_vec.py` (module docstring, `from __future__ import annotations`,
      `from alembic import op`, the four module vars). Set `revision = "0011"` and
      `down_revision = "0010"`. In `upgrade()` run these two statements, each with
      `IF NOT EXISTS`:

      ```sql
      CREATE TABLE IF NOT EXISTS tags (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL UNIQUE,   -- canonical: lowercased, trimmed
        created_at  TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS artifact_tags (
        artifact_id TEXT NOT NULL REFERENCES artifacts(id),
        tag_id      TEXT NOT NULL REFERENCES tags(id),
        created_at  TEXT NOT NULL,
        PRIMARY KEY (artifact_id, tag_id)
      );
      ```

      In `downgrade()`: `DROP TABLE IF EXISTS artifact_tags;` then `DROP TABLE IF EXISTS tags;`
      (child first). Use `op.execute("...")` for each statement, one call per statement.
- [x] `[AGENT]` Verify the migration applies: `bin/relaunch` then
      `uv run python -c "from enqueue import db; c=db.get_conn(); print([r[1] for r in c.execute('PRAGMA table_info(tags)')]); print([r[1] for r in c.execute('PRAGMA table_info(artifact_tags)')])"`.
      Expect `['id','name','created_at']` and `['artifact_id','tag_id','created_at']`.

---

## PHASE T2 — Tag logic module (`src/enqueue/tags.py`)

Create the file. Import pattern: `from __future__ import annotations`, `import uuid`,
`from datetime import datetime, timezone`, `from . import db`. Add a private
`def _now() -> str: return datetime.now(timezone.utc).isoformat()`.

- [x] `[AGENT]` `def normalize(name: str) -> str`: return `name.strip().lower()`. Raise
      `ValueError("a tag needs a name")` if the result is empty.
- [x] `[AGENT]` `def add(artifact_id: str, name: str) -> dict`: normalize the name; in one
      `db.transaction()`: confirm the artifact exists (raise `KeyError(artifact_id)` if not);
      `INSERT OR IGNORE INTO tags (id, name, created_at) VALUES (?,?,?)` with a new uuid4;
      select the tag's id by name; `INSERT OR IGNORE INTO artifact_tags (artifact_id, tag_id, created_at) VALUES (?,?,?)`;
      then `UPDATE artifacts SET updated_at = ? WHERE id = ?` (tagging is touching it, and
      the wall is ordered by last touch). Return `{"artifact_id": artifact_id, "name": name}`.
- [x] `[AGENT]` `def remove(artifact_id: str, name: str) -> dict`: normalize; in one
      transaction delete the `artifact_tags` row for that (artifact, tag name); if the tag is
      now referenced by no artifact, delete the orphan `tags` row; bump the artifact's
      `updated_at`. Return `{"artifact_id": artifact_id, "name": name, "removed": True}`.
- [x] `[AGENT]` `def for_artifact(artifact_id: str) -> list[str]`: return the artifact's tag
      names ordered by name, using a read connection (`db.get_conn()`, close in `finally`).
- [x] `[AGENT]` `def cloud() -> list[dict]`: return every tag with its count, most-used first:
      `SELECT t.name, COUNT(at.artifact_id) AS n FROM tags t JOIN artifact_tags at ON at.tag_id = t.id GROUP BY t.id ORDER BY n DESC, t.name`.
      Return a list of `{"name": ..., "count": ...}`.
- [x] `[AGENT]` `def ids_with_all(names: list[str]) -> set[str]`: given normalized tag names,
      return the set of artifact ids that carry ALL of them (AND semantics). Empty input
      returns an empty set and the caller treats that as no filter. SQL:
      `SELECT artifact_id FROM artifact_tags at JOIN tags t ON t.id = at.tag_id WHERE t.name IN (<one ? per name>) GROUP BY artifact_id HAVING COUNT(DISTINCT t.name) = <len(names)>`.
- [x] `[AGENT]` Tests in `tests/test_tags.py` (use the `store` fixture from `conftest.py`,
      mirror `tests/test_trash.py`). Each is one commit or grouped in one commit for this file:
      - add then `for_artifact` returns `["work"]`.
      - add the same tag twice; `for_artifact` still returns one entry (idempotent).
      - add normalizes: `add(id, "  Work ")` then `for_artifact` returns `["work"]`.
      - `remove` deletes the link and orphan tag; `cloud()` no longer lists it.
      - `remove` a tag still used by another artifact leaves the `tags` row intact.
      - `ids_with_all(["a","b"])` returns only artifacts carrying both, not either.
      - `add` on a missing artifact id raises `KeyError`.
      - `add("")` raises `ValueError`.
- [x] `[AGENT]` Verify: `uv run pytest -q tests/test_tags.py` green; `uv run black src/enqueue/tags.py tests/test_tags.py`.

---

## PHASE T3 — API endpoints

All in `src/enqueue/api.py`. Put the tag endpoints near the annotation endpoints (search the
file for `annotations` to find the neighbourhood). Follow the existing endpoint style:
`@app.<verb>("...")`, a small Pydantic body model where a body is needed, translate
`KeyError` to `HTTPException(404)` and `ValueError` to `HTTPException(400)`.

- [x] `[AGENT]` `POST /artifacts/{artifact_id}/tags` with body `{"name": str}`: call
      `tags.add(...)`. 404 on `KeyError`, 400 on `ValueError`. Return the dict from `add`.
- [x] `[AGENT]` `DELETE /artifacts/{artifact_id}/tags/{name}`: call `tags.remove(...)`. Return
      its dict.
- [x] `[AGENT]` `GET /artifacts/{artifact_id}` already returns the artifact detail. Add its
      tags to the response: include `"tags": tags.for_artifact(artifact_id)`. Find the function
      behind that route (search `def get_artifact` or the `/artifacts/{` route) and add the field
      to the returned dict. Do not remove any existing field.
- [x] `[AGENT]` `GET /tags`: return `{"tags": tags.cloud()}`.
- [x] `[AGENT]` Tests in `tests/test_api_tags.py` using the FastAPI `TestClient` pattern
      already used in the test suite (search tests for `TestClient` to copy the setup): POST a
      tag, GET the artifact shows it in `tags`, GET `/tags` shows it with count 1, DELETE
      removes it. `uv run pytest -q tests/test_api_tags.py` green.

---

## PHASE T4 — Search: tag filter with a no-embed fast path

Search enters at `api.py` route `def search` -> `retrieve/candidates.py` `search_results(q, limit)`.
Tags are a FILTER, not text to rank. Do not put tags into the index or the embedding.

- [x] `[AGENT]` Add `def parse_tags(q: str) -> tuple[str, list[str]]` to `src/enqueue/tags.py`:
      split the query on whitespace; any token that is `#word` or `tag:word` is a tag (strip the
      `#` or `tag:` prefix, then `normalize`); everything else rejoins into the free-text query.
      Return `(free_text, tag_names)`. Test it: `parse_tags("kubernetes #work tag:urgent")`
      returns `("kubernetes", ["work", "urgent"])`; `parse_tags("#work")` returns `("", ["work"])`;
      `parse_tags("plain query")` returns `("plain query", [])`.
- [x] `[AGENT]` In `search_results(q, limit)` (in `candidates.py`): call `parse_tags(q)` first.
      Compute `tag_ids = tags.ids_with_all(tag_names)` when `tag_names` is non-empty.
      - **Pure tag query** (free_text is empty and `tag_names` non-empty): do NOT embed and do
        NOT call `store.search`. Build results directly from `tag_ids`: for each id, read title
        and kind from `artifacts`, snippet from the artifact text, and return them ordered by
        `updated_at DESC`. This is the fast path (about 1 ms; no model call).
      - **Mixed query** (free_text non-empty AND `tag_names` non-empty): run the existing hybrid
        search on `free_text`, then keep only results whose `artifact_id` is in `tag_ids`.
      - **No tags** (`tag_names` empty): unchanged behaviour, search on `q` as today.
      Do not change the shape of a returned hit (same keys the wall already consumes).
- [x] `[AGENT]` Tests in `tests/test_search_tags.py` (use `store` fixture): tag two artifacts,
      leave one untagged; assert a pure `#tag` query returns exactly the tagged ones; assert a
      mixed query returns only results that both match the text and carry the tag; assert a
      plain query is unaffected. `uv run pytest -q tests/test_search_tags.py` green, and the full
      `uv run pytest -q` stays green (226+ passing).
- [x] `[AGENT]` Confirm retrieval quality did not move: `uv run enq eval` and check the Pass /
      Recall@1 / MRR line is unchanged from before this phase (tags are a filter, so an eval with
      no tag tokens must be byte-identical). If it moved, you changed the non-tag path by mistake;
      revert and redo.

---

## PHASE T5 — Wall filtering (`list_artifacts`)

`list_artifacts` in `api.py` builds the wall. It UNIONs `artifacts` with `chats`
(conversations). A tag filter applies to artifacts only; conversations cannot be tagged, so a
tag filter must EXCLUDE the chats limb entirely.

- [x] `[AGENT]` Add a parameter `tags: str = ""` to `list_artifacts` (comma-separated tag names,
      empty means no filter). Parse it into a normalized list with `tags_mod.normalize` per item,
      dropping empties.
- [x] `[AGENT]` When the tag list is non-empty: compute `ids = tags_mod.ids_with_all(names)`;
      add to the artifacts `where` a clause restricting to those ids (bind the id set with the
      existing `json_each` pattern the codebase uses for id lists, or an `IN` list of named
      params); and replace the `UNION ALL ... FROM chats ...` limb with nothing (no chats when
      filtering by tag). When the tag list is empty, the query is exactly as it is today. Keep
      the `total` count consistent with whichever limbs ran.
- [x] `[AGENT]` Expose the parameter on the `GET /artifacts` route so the client can pass
      `?tags=work,urgent`.
- [x] `[AGENT]` Tests: `list_artifacts(tags="work")` returns only tagged artifacts and zero
      chats; `list_artifacts()` (no tags) is unchanged and still includes chats. `uv run pytest -q`
      green.

---

## PHASE T6 — UI (`museum.html`)

Product register: inline, no sidebar, hierarchy through space and weight. Reuse existing
tokens (`--surface-2`, `--accent`, `--text-mute`, `--r-full`, `--sp-*`). Do not invent colours.
Parse-check after every edit: `bin/relaunch` runs `node --check` on the inline script and
refuses to start on a syntax error.

- [x] `[AGENT]` **Tag chips on the artifact page.** In `showArtifact(...)`, render a `.tagrow`
      on a `.tagrail` beside the body (the body and rail sit in a `.bodygrid`, the rail on the
      right; under 900px it stacks below the body). One chip per tag from the artifact's `tags`
      array (each chip shows the name and a small `x` calling a `removeTag`
      handler), then a small "add tag" text input that on Enter calls an `addTag` handler.
      `addTag` POSTs `/artifacts/{id}/tags`, `removeTag` DELETEs
      `/artifacts/{id}/tags/{name}`; both re-render the artifact on success and `toast(...)` on
      failure (never a silent `.catch`). Style chips with `--surface-2` fill, `--r-full`,
      `--sp-1 --sp-2` padding, `--text` label; keep the row tight to the meta line, generous gap
      to the body.
- [x] `[AGENT]` **Tag bar on the home wall.** In `home(...)`, after the `.searchbar` inside
      `.homehead` and before the first shelf, fetch `GET /tags` and render a `.tagbar`: the top
      8 tags as chips (muted `--surface-2` at rest). Clicking a chip runs the search for `#name`
      (call the same path the searchbar uses, e.g. set the input to `#name` and trigger the
      existing search). If there are more than 8 tags, add a small "all tags" chip that shows the
      rest. If there are zero tags, render nothing (no empty bar). The searchbar stays visually
      primary; chips are secondary and smaller.
- [x] `[AGENT]` **Active-filter header.** When a tag filter is active (the search ran for a
      `#tag`), the results header reads `Tagged #work` with a clear-filter control that returns to
      the wall. Reuse the existing search-result header built in `doSearch(q)` (it renders a
      `" result" ... for ...` header) rather than inventing a new one.
- [x] `[AGENT]` Do NOT add tags to the wall card face. Cards stay as they are (kind dot, title,
      date). Tags are a filter and a detail-page concern only.
- [x] `[AGENT]` Verify by looking: `bin/relaunch`, open the app, add a tag on an artifact, see
      the chip; go home, see the tag bar, click a chip, see the wall filter and the "Tagged"
      header; clear it and see the full wall return. Confirm keyboard focus is visible on chips
      and the add-tag input.

---

## Done

- [x] `[AGENT]` `uv run pytest -q` green (was 226, now higher), `uv run black --check src/ tests/`
      clean, `bin/relaunch` starts, `uv run enq eval` unchanged from the pre-tags number.
- [ ] `[HUMAN]` Review: confirm no tag prompt appears at capture time anywhere, a pure `#tag`
      search is instant, and the wall filter excludes conversations.

## Out of scope (do not build unless a later plan says so)

- Renaming or merging tags.
- Showing tags on the wall card face.
- A full dedicated "all tags" page (the top-8 bar plus overflow is enough).
- Folding tags into the search index for un-prefixed ranking (Option A in the analysis).
- OR-semantics multi-tag filtering (AND only for now).
