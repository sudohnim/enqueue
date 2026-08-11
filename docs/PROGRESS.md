# Enqueue Progress - Phases R, C, M, P (search correctness + retrieval quality, capture overlay fix + polish, museum -> home rename + file split, deletion-first refactor, performance)

This file is the agent's work queue.
Do one task per turn, in order, and verify each with its "Done when" line before checking the box.
Do not implement anything that is not listed below.
Line numbers are approximate; earlier tasks shift them, so re-anchor on surrounding code before every edit.
Technical decisions in this file prefer quality, simplicity, robustness, scalability, and long-term maintainability over development cost.

Global rules for every task:

- Python formatting is `black`, line-length 100. Run `uv run black --check src/ tests/` before finishing any task that touches Python.
- The full gate is `bin/verify` (JS parse check + pytest + contrast). It must pass at the end of every phase and after any task that touches `src/enqueue/static/`.
- Bug fixes start from a failing end-to-end reproduction, never from reading code alone.
- Never use the em dash character. Use a plain dash.
- When a task renames or moves anything listed in `AGENTS.md`, update `AGENTS.md` in the same change.

Repo root for all commands: `~/enqueue`.

---

## Ground truth (already derived; do not re-derive)

### GT.1 - The Chopper bug is an indexing-coverage bug, not a ranking bug

Repro path: an image was captured, and the text "tony tony chopper" was added as a note on it.
Searching "tony tony chopper" returns nothing. Searching "any one piece character" returns nothing.

Root causes, verified in code:

1. **Annotations are never indexed.**
`notes.annotate()` (`src/enqueue/notes.py:136-170`) inserts into the `annotations` table and bumps `updated_at`, but never calls `ingest_queue.submit()`.
Even if it did, `chunk_artifact()` (`src/enqueue/ingest/chunk.py:146-190+`) builds chunk text only from `artifacts.body`, `page_text`, and link preview text.
The string "tony tony chopper" therefore never reaches `chunks`, `fts_chunks`, `vec_chunks`, facets, or entities.
Nothing in `ingest/`, `index/`, or `retrieve/` references the `annotations` table at all.
2. **An image whose vision describe failed has zero searchable text.**
`_describe_image_if_needed()` (`src/enqueue/ingest/queue.py:144-191`) swallows every exception (`except Exception`, line 180) and leaves `body` NULL.
With no body, `chunk_artifact` returns 0, so `process()` drops the artifact's index points (queue.py:111-115) and skips facets and entities (queue.py:123,131).
The artifact is then invisible to every retrieval layer, and the failure is silent: `status` is not changed and nothing surfaces it.
The default backend is ollama with a text-only model, so this failure is the common case, not the edge case.
3. **"any one piece character" is a conceptual query with nothing to grab.**
Facets and entities are only generated when chunks exist (queue.py:123,131), so the invisible image has no conceptual layer either.

### GT.2 - The capture overlay dismiss regression is a Tauri ACL gap

The overlay is dismissed on outside click by a JS focus listener (`src/enqueue/static/capture.html:301-320`) that calls `window.__TAURI__.window.getCurrentWindow().onFocusChanged(...)`.
In Tauri v2, `listen` requires the `core:event:allow-listen` permission.
The capture window's capability in `desktop/tauri.conf.json` (the `capture-overlay` entry) grants only `allow-capture-dismiss` and `allow-capture-drag`.
The listen call is rejected at runtime, the rejection is not a sync throw so the surrounding `try/catch` never sees it, and no listener is ever registered.
Result: clicking outside never dismisses the overlay.

### GT.3 - Token drift between capture.html and museum.html (measured)

| Token/rule | capture.html | museum.html | Verdict |
| --- | --- | --- | --- |
| `--bg`, `--surface`, `--surface-2`, `--line`, `--line-strong`, `--text*`, `--accent` | same values | same values | match |
| card radius | `--r-sm` 6px (line 73, 107) | floating surfaces use `--r-lg` 12px | drift |
| card shadow | `--shadow-1` card-level (line 75) | floating surfaces use `--shadow-lifted` | drift |
| placeholder | `--text-mute` #686b82 (line 170) | `--ink-faint` #6c6f84 | drift |
| error text | `--pink` #8f4273, the image-kind hue (line 68, 147-149) | danger is #b4332b | drift, wrong semantics |
| focus ring | none, `outline: none` (line 160) | mandated lavender ring on inputs | drift |
| kind hues | absent | `--kind-note/link/pdf/image` tokens | missing |

### GT.4 - Detector + design review findings

`node ~/.config/opencode/skills/impeccable/scripts/detect.mjs --json src/enqueue/static/museum.html` reports one warning: bounce easing `cubic-bezier(0.34, 1.56, 0.64, 1)` at museum.html:1882.
That overshoot is deliberate (press-release pop, documented at museum.html:1877-1882).
Decision: keep it, no task.
capture.html and museum-plain.html scan clean.
The design review additionally found: dead CSS variables in use (`var(--surface-1)` at museum.html:712,771,804, `var(--text-2)` at 985,988), undefined `--sp-sm` used by `.card` at museum.html:1416 (cards silently get padding 0; the intended value is `--sp-3`), hover-only card controls (recognition problem), and a silent capture success (no confirmation beat).

### GT.5 - Second-brain search research (what mem.ai, fabric.so, and peers actually do)

Sources: mem.ai blog (<https://get.mem.ai/blog/building-mem-the-ai-notes-app-(feat-pinecone)>, <https://get.mem.ai/blog/search-just-got-a-whole-lot-smarter>), Fabric developer docs (<https://developers.fabric.so/developer-guide/resources/searching-resources>), Notion engineering (<https://www.notion.so/blog/two-years-of-vector-search-at-notion>), Obsidian Smart Connections docs (<https://smartconnections.app/smart-connections/settings/>), Rewind teardown (<https://kevinchen.co/blog/rewind-ai-app-teardown/>), mymind docs (<https://mymind.com/how-does-it-work>).

Convergent techniques, in order of adoption value for a local single-user app with a small corpus:

1. **Index everything user-visible.** mem, Fabric, mymind, Rewind all index OCR text, captions, transcripts, titles, and metadata. Indexing gaps, not ranking, cause headline failures. This is the Chopper bug class. Adopted in R.2/R.3.
2. **Hybrid lexical + vector, always.** Nobody ships vector-only. We already fuse dense + FTS5 with RRF; keep it.
3. **Typo-tolerant lexical leg.** Fabric ships it explicitly. Local equivalent: FTS5 trigram tokenizer for substring/partial matching plus an app-level fuzzy match over short fields (titles, annotation lines, entity names). Adopted in R.6/R.7.
4. **Field weighting.** Titles and tags outweigh body text (bm25 column weights). Adopted in R.5.
5. **RRF k=60 is the canonical constant** (Cormack et al., SIGIR 2009). Our k=1 exists only to keep scores on the lens threshold's scale; once the lens surface is gone, k=1 has no justification. Adopted in M.5g.
6. **Over-fetch + rerank.** Smart Connections Pro reranks a small candidate set with a cross-encoder. Local equivalent: BAAI/bge-reranker-base via fastembed. Adopted as optional R.9.
7. **Recency/frecency signals.** Every app exposes time weighting. Adopted in R.8.
8. **Exact-needle escape hatch.** Fabric's double quotes force exact match. Adopted in R.10.
9. **Golden-set eval before tuning.** Notion treats retrieval eval as the multiplier on all other work. Adopted in R.1/R.4.
10. **Skip at our scale:** ANN indexes (brute-force kNN over 768d x ~10k items is milliseconds), learned sparse retrievers, ColBERT, cloud rerank APIs.

### GT.6 - Deletion and split inventories

The full verified inventory is summarized inside each M task.
Key facts: `museum-plain.html` (3951 lines) and `capture-plain.html` (516 lines) have zero references anywhere in the repo.
museum.html carries ~330 lines of dead JS and ~250 lines of dead CSS (rail, bucket, h1row, pin, dead tokens).
Four Qdrant eval result files in `evals/results/` describe a removed engine.
`chonkie` is a declared dependency with zero imports.
The museum.html split constraint: `api.py:70-72` serves `GET /` by reading one file; `api.py:59-67` already serves any file under `static/` at `/static/{name:path}`, so a split into `home.html` + `css/*.css` + `js/*.js` needs no new plumbing, only ordered plain `<script>` tags (the file is already one global scope).

---

## Phase R - Search and retrieval

The product priority: be measurably better at search and retrieval for a small personal corpus.
Every ranking change is validated against the golden set from R.4 before it is considered done.

### R.1 - Failing end-to-end reproductions of the Chopper bug

- [x] **R.1 [AGENT]** Add `tests/test_annotation_search.py` with three failing tests that encode the reported bug exactly.

  Pattern to follow: `tests/test_search_results.py` (direct DB seeding + `sqlite_store` fixture) and `tests/test_image_vision.py:21-86` (`FakeVisionProvider`, `_fake_vision` monkeypatch of `providers_base.get_vision_provider`, `_quiet_derived` stubbing facets/entities).
  Use the `store` and `quiet_queue` fixtures from `tests/conftest.py` so ingest runs inline.

  Test 1 `test_annotation_text_is_searchable`: insert a link artifact (`kind='link'`, `body` NULL, content_hash unique), insert one annotation row with text `tony tony chopper`, run `ingest_queue.process(artifact_id)`, then assert `search_results("tony tony chopper")` contains the artifact id.
  Today this fails: no chunks exist for the artifact.

  Test 2 `test_vision_described_image_matches_conceptual_query`: create an image artifact, monkeypatch the vision provider to return `A Tony Tony Chopper plush figure from One Piece, a small reindeer with a pink hat`, process, assert `search_results("one piece character")` contains the artifact.
  Today this passes only when the fake is in place; it documents the intent that described images answer conceptual queries.

  Test 3 `test_image_without_body_and_annotation_only`: monkeypatch the vision provider to raise, process the image with an annotation `tony tony chopper`, assert search finds it.
  Today this fails twice over (no body, annotation unindexed).

  Do not fix any code in this task. Commit the red tests.

  Done when: `uv run pytest tests/test_annotation_search.py -q` shows tests 1 and 3 failing and the file is committed.

### R.2 - Index annotations

- [x] **R.2a [AGENT]** Include current annotation text in the chunk source.

  Anchor: `chunk_artifact()` in `src/enqueue/ingest/chunk.py:146`+.
  After `body` is resolved for every kind (the existing link/file/pdf fallbacks), append the artifact's current annotations:

  ```python
  notes = conn.execute(
      "SELECT a.text FROM annotations a"
      " WHERE a.artifact_id = ?"
      " AND NOT EXISTS (SELECT 1 FROM annotations b WHERE b.supersedes_id = a.id)"
      " ORDER BY a.created_at",
      (artifact_id,),
  ).fetchall()
  if notes:
      body = (body + "\n\n" if body.strip() else "") + "\n\n".join(n["text"] for n in notes)
  ```

  Superseded annotations are excluded by the `NOT EXISTS` clause, matching the `current` flag logic in `notes.get()` (`notes.py:191`).
  Do not touch the `artifacts.body` column; this is index-source text only.

  Done when: R.1 test 1 and test 3 pass; `uv run pytest tests/test_annotation_search.py tests/test_ingest.py -q` is green.

- [x] **R.2b [AGENT]** Re-queue ingest when an annotation is written.

  Anchor: `notes.annotate()` at `src/enqueue/notes.py:136-170`.
  After the transaction commits (after line 168's block, before the `return`), add `ingest_queue.submit(artifact_id)`.
  `ingest_queue` is already imported at notes.py:19.
  Add a test in `tests/test_annotation_search.py`: with the `quiet_queue` fixture replaced by a spy list (pattern: `tests/conftest.py:26` `quiet_queue`), assert that calling `notes.annotate()` appends the artifact id to the submitted list.
  Also add a supersede test: annotate `tony tony chopper`, then supersede it with `chopper the reindeer`, process, assert a search for the superseded string returns nothing and the new string hits.

  Done when: `uv run pytest tests/test_annotation_search.py -q` is fully green, including the submit-spy and supersede tests.

- [x] **R.2c [AGENT]** Backfill existing annotations.

  Anchor: `submit_all()` in `src/enqueue/ingest/queue.py` (near line 358) already re-queues every artifact.
  No new code: the existing `POST /reprocess` / `enq index` path rebuilds chunks, which now include annotations.
  Verify by hand against a real database: start the engine, `uv run enq reindex`, then search for a string that exists only in an old annotation.

  Done when: the manual search returns the annotated artifact; note the checked string in the commit body.

### R.3 - Images without a body stay findable

- [x] **R.3a [AGENT]** Surface describe failures instead of swallowing them silently.

  Anchor: `_describe_image_if_needed()` at `src/enqueue/ingest/queue.py:176-182`.
  In the `except` branch, after the existing `log.warning`, also mark the artifact: `UPDATE artifacts SET status = 'failed' WHERE id = ?` inside a `db.transaction()`.
  `'failed'` is already an allowed status value (migration 0001 status comment: `ok | pending | text_only | failed`).
  Extend the doctor payload: in the `/doctor` handler region of `api.py` (near line 855) add `images_without_body`, computed as `SELECT COUNT(*) FROM artifacts WHERE kind='image' AND deleted_at IS NULL AND (body IS NULL OR body = '')`.
  Add a test: vision provider raises, process an image, assert `status = 'failed'` on the row.

  Done when: `uv run pytest tests/test_annotation_search.py tests/test_doctor.py -q` is green and the new doctor field appears in `uv run enq doctor` output against a dev database.

- [x] **R.3b [AGENT]** Index title and filename for bodyless captures.

  Anchor: `chunk_artifact()` in `src/enqueue/ingest/chunk.py`, after the body fallbacks and the R.2a annotation append.
  If `body` is still empty and the artifact kind is not `note`, set the chunk source to `row["title"]` plus `filename` when present (select `filename` in the initial query at chunk.py:148-150).
  This guarantees every artifact has at least one chunk, so it is reachable by its name and by future annotations, and so facet/entity generation (gated on chunks existing) can run.
  Add a test: an image artifact titled `chopper-plush.png` with a failing vision provider is returned by `search_results("chopper plush")`.

  Done when: `uv run pytest tests/test_annotation_search.py -q` green including the new test.

### R.4 - Golden-set search eval harness

- [x] **R.4 [AGENT]** Add a deterministic recall harness for `/search`, then record the baseline.

  Create `scripts/search_eval.py`: loads `evals/search/queries.json` (new file, create it), runs each query through `retrieve.candidates.search_results`, and prints recall@10 and MRR, exiting non-zero if the file is missing.
  Seed `evals/search/queries.json` with 12-16 cases as `{"query": ..., "expect_id_substring": ...}` pairs covering: the evals/corpus notes (reuse known content from `evals/queries.yaml`), plus three needle cases for the Chopper class: an exact annotation string, a one-edit typo (`tony tony copper`), and a conceptual query against a fake-vision-described image.
  Because the harness must be deterministic offline, drive it against a fixture database built by a `scripts/seed_search_eval.py` that inserts artifacts directly (same pattern as `tests/test_search_results.py::_note`) and fakes the vision provider.
  Run it now and record the baseline numbers in the commit body.

  Done when: `uv run python scripts/search_eval.py` exits 0 and prints per-query hit/miss plus recall@10; baseline numbers are in the commit body.

### R.5 - Title-weighted keyword branch

- [x] **R.5 [AGENT]** Give FTS5 a separate title column and weight it.

  Anchors: `_DDL["fts_chunks"]` at `src/enqueue/index/store_sqlite.py:68-71`, `CHUNK_INDEX_TEXT` at line 162, `upsert_chunks` at 241-246, `index_artifact` at 294-341, the `keyword` SQL at 111-114.
  Change `fts_chunks` to `USING fts5(chunk_id UNINDEXED, title, text)`.
  Change the keyword query to `bm25(fts_chunks, 10.0, 1.0)`.
  Keep the dense branch embedding `title\n\ntext` (the current CHUNK_INDEX_TEXT behavior is correct for vectors).
  `index_artifact` and `_rebuild` must write title and text as separate columns; title comes from the existing join to artifacts in both select queries.
  Add a test in `tests/test_search_results.py`: note A titled `Tony Tony Chopper` with unrelated body, note B with an unrelated title and body mentioning `tony tony chopper` once; assert A ranks above B for query `tony tony chopper`.
  `enq index` rebuilds the table, and `bootstrap.ensure_index()` recreates it on shape change; confirm the doctor sync check still passes.

  Done when: `uv run pytest tests/test_search_results.py tests/test_store_sqlite.py -q` green, new title-weight test included.

### R.6 - Substring matching via a trigram FTS table

- [x] **R.6 [AGENT]** Add a trigram branch and fuse it.

  Guard first: `uv run python -c "import sqlite3; print(sqlite3.sqlite_version)"` must be >= 3.34; if older, stop and report before touching code.
  Anchors: `_DDL` and `_COLLECTION_TABLES` at `store_sqlite.py:57-92`, `search()` at 511-539.
  Add `fts_chunks_tri` as `USING fts5(chunk_id UNINDEXED, text, tokenize='trigram')`, populated everywhere `fts_chunks` is written (rebuild, `index_artifact`, `drop_artifact`).
  In `search()`, build a third ranked list from the trigram table: tokens of length >= 3 joined with ` OR ` (recall branch; RRF does the ranking), skipped entirely when no token reaches 3 chars.
  Fuse all three lists in the existing `rrf_scored` call.
  Add `fts_chunks_tri` to `counts()`.
  Tests: a note containing `tony tony chopper` is found by `tony chopp` (prefix of a word, unicode61 prefix handles it) and by `hopper` (infix, only trigram handles it); a two-char query still works and exercises only the dense + unicode61 branches.

  Done when: `uv run pytest tests/test_store_sqlite.py tests/test_search_results.py -q` green including the `hopper` infix test; `uv run python scripts/search_eval.py` recall@10 is >= the R.4 baseline (record both).

  **Deviations from the literal spec** (both forced by the committed gates):
  - Not fused into the RRF call. Pure three-list fusion regressed the R.5 title-weight test (a2's body trigrams outrank a1's title-only match) AND the eval: appended hits carried flipped-bm25 scores of 5-20, and the /search rollup re-sorts by score, so substring noise ("grow" matching half the corpus) displaced real hits (recall@10 fell 14/15 -> 12/15). The branch is a recall net: hits the hybrid missed are appended after it with score 0.0, so they sort below every fused hit and only surface when the hybrid returned fewer than the limit.
  - The trigram table indexes `text` only (not title), per the spec's DDL; a bodyless capture whose title is the only text is covered by the R.3b title+filename chunk source.
  - `_search_trigram` tolerates a missing table (upgraded DBs that have not rebuilt yet); the write path creates it via `ensure()`.

  Eval (R.4 harness, same 15 queries): R.6 -> recall@10 14/15 (0.933), MRR 0.782, bit-identical ranks to R.5 (the append-only recall net cannot move a fused hit).

### R.7 - Typo tolerance over short fields

- [x] **R.7 [AGENT]** Add a fuzzy branch over titles, entity names, and annotation lines.

  Rationale: trigram covers substring, not one-edit typos (`copper` vs `chopper` share too few trigrams for FTS5 phrase semantics).
  Full-corpus fuzzy over chunk text is too slow, so scope the branch to short fields only: artifact titles, `entities.entity` values, and current annotation texts (same `NOT EXISTS` filter as R.2a).
  Implementation: in `retrieve/candidates.py`, a helper `_fuzzy_hits(q, limit)` that loads those short strings in three small queries (corpus is hundreds to low thousands of rows; this stays single-digit milliseconds), scores each with `difflib.SequenceMatcher(None, q.lower(), candidate.lower()).ratio()` plus `partial`-style best-window matching over words, keeps candidates at ratio >= 0.75, and returns them as artifact hits with `why="fuzzy"` and a modest score (below a strong lexical hit).
  Stdlib only; do not add a dependency.
  Call it from `search_results` after the hybrid rollup and merge by artifact id, keeping the higher score.
  Tests: artifact annotated `tony tony chopper` is returned for query `tony tony copper` with `why="fuzzy"`; an unrelated artifact below the threshold is not returned.

  Done when: `uv run pytest tests/test_annotation_search.py -q` green including the typo test; `scripts/search_eval.py` recall@10 >= R.6 numbers (record both).

  **Deviations/decisions** (forced by the committed unit tests):
  - The annotations query uses chunk.py's exact R.2a filter (`NOT EXISTS supersedes_id`); the annotations table has no `deleted_at` column.
  - Merge rule is score-wins, not why-wins: a fuzzy match overrides an artifact's entry only when its score beats the hybrid's. This keeps the R.5 story intact (an exact title match stays `why="chunk"` at 0.83) while a typo query (dense-only, 0.5) yields to `why="fuzzy"` at 0.6 x ratio. The first draft (why flips on any fuzzy match) broke `test_six_chunks` (rooftops/rooftop is a real singular-plural fuzzy match) and mislabeled Hypatia's title match.
  - `FUZZY_BASE_SCORE = 0.6`: above a single-branch rank-1 hit (0.5, all a typo query can muster) but below a dual-branch rank-1 hit (1.0, a strong lexical hit).

  Eval (R.4 harness, same 15 queries): R.7 -> recall@10 14/15 (0.933), MRR 0.782, bit-identical ranks to R.6; `tony tony copper` is now the fuzzy branch's hit (why="fuzzy") at the same rank 1.

### R.8 - Recency weighting

- [x] **R.8 [AGENT]** Apply a small time-decay multiplier to free-text search scores.

  Anchor: `_hybrid_results()` at `src/enqueue/retrieve/candidates.py:253-291`.
  Fetch `updated_at` for the ranked artifacts in one batched query (use the `json_each` IN pattern from `store_sqlite.py:550`), then compute `final = score * (1 + RECENCY_WEIGHT * exp(-age_days / RECENCY_TAU_DAYS))` with `RECENCY_WEIGHT = 0.5` and `RECENCY_TAU_DAYS = 30` as module constants.
  Do not touch `_all_results` or `_results_for_ids` (they are already newest-first listings, not ranked searches).
  Test: two notes with identical bodies, one `updated_at` now and one 180 days ago; the newer one ranks first for a matching query; with `RECENCY_WEIGHT` monkeypatched to 0 the order ties out to the base score.

  Done when: `uv run pytest tests/test_search_results.py -q` green including the recency test; `scripts/search_eval.py` recall@10 not regressed (record).

  Recorded: commit `8c14a7a` (worktree: `1e296ca` R.5 / `90695b4` R.6 / `2250643` R.7). `_hybrid_results` now fetches `updated_at` for every rolled-up artifact in one `json_each` IN query (same pattern as `store_sqlite.py:550`), then multiplies the fused score by `1 + RECENCY_WEIGHT * exp(-age_days / RECENCY_TAU_DAYS)` BEFORE the final sort, so a fresh artifact can overtake a stale one with a comparable base score. `_age_days` parses both sqlite `datetime('now')` strings and ISO-with-offset timestamps (naive parsed as UTC), clamps at zero, and never penalizes an undatable row. `_all_results`/`_results_for_ids` untouched.
  Eval (R.4 harness, same 15 queries): R.8 -> recall@10 14/15 (0.933), MRR 0.782, identical ranks to R.7. The seeded corpus is uniformly "now", so the multiplier is a constant 1.5x across every artifact - relative order is bit-identical.

  Deviation from the literal test spec (documented, same discipline as R.5/R.6/R.7): the "fully identical notes" scenario cannot flip at k=1 RRF. A rank-1-vs-rank-2 fused gap is a 1.5x ratio (1.0 vs 0.667), and the maximum recency boost is also 1.5x (age 0 vs infinity) - the older note's multiplier never drops below 1.0, so `old * (1 + 0.5 * e^-6) = 1.00124 > new * 1.5 = 1.0` always wins. The test therefore uses distinct-but-neutral titles ("Field notes" / "City farming") with identical bodies: the dense branch (embedding similarity) ranks old first, the keyword branch ranks new first (the rebuild's select_all follows `idx_artifacts_live`'s (deleted_at, created_at DESC) order, so the freshly-created note's FTS row sorts first and wins the body-only bm25 tie), fusing to equal 0.8333/0.8333 - a genuine tie that recency then breaks toward the newer note. The spec's "updated_at 180 days ago" is set on both created_at and updated_at (created_at participates in that index order; a note that old naturally has both). With `RECENCY_WEIGHT` zeroed, the order ties out to the base score (old first).

### R.9 - Optional cross-encoder rerank

- [x] **R.9 [AGENT]** Add an opt-in rerank stage over the fused candidates.

  Skip this task until R.1-R.8 are done and the R.4 harness numbers are recorded.
  In `retrieve/candidates.py::search_results`, when `config.SEARCH_RERANK` is on (new setting, default off, env `ENQ_SEARCH_RERANK`), rerank the top 30 fused artifacts with `fastembed.rerank.cross_encoder.TextCrossEncoder("BAAI/bge-reranker-base")` against their `artifact_text` (truncate to 1200 words, existing helper), and order by reranker score.
  Tests stub the reranker; no model download in tests.
  Measure with `scripts/search_eval.py` before/after and keep the flag whichever way wins; record both numbers in the commit body.

  Done when: flag off path is byte-identical in behavior to R.8 (test proves it), flag on path passes tests, eval numbers recorded.

  Recorded: commit `bfdf1a7`. `config.SEARCH_RERANK` (default off, env `ENQ_SEARCH_RERANK`, any of 1/true/yes/on). In `search_results`, the free-text path reranks a `max(limit, 30)`-wide fused window with `_rerank(q, fused)` and truncates; the mixed-tag path deliberately does not rerank (tags are a filter, the free text is ranked, then the tag set is carved out). `_rerank` scores each artifact against `artifact_text` (the existing 1200-word helper), sorts by reranker score descending with a stable sort, keeps the fused order for ties, and degrades to the fused order unchanged on any model failure - reranking is an enhancement, never a gate.
  Two deviations, both verified empirically:
  - **CPU providers only for the reranker.** `_providers()` (CoreML) is used by the embedding model; loading a SECOND CoreML model in the same process leaks CoreML contexts until the OS SIGKILLs the process (exit 137, "Context leak detected"). Probe: CoreML embedder + CPU reranker coexist fine, scores sane (rooftops doc -1.83 vs unrelated -10.19). The reranker is an occasional opt-in pass over ~30 docs, so CPU is not the hot path.
  - **Window wider than limit.** The spec says "top 30"; with `limit=5` the reranker could never promote a candidate outside the top 5, so the window is `max(limit, 30)`.
  Tests (`TestRerank`, stubbing `_cross_encoder`): flag-off never constructs the model (stub raises; fused order is exactly the R.8 order - this file's pre-R.9 tests run flag-off and pass unchanged), flag-on reorders per the stub's inversion of the fused list, flag-on promotes a rank-21-of-30 note with `limit=5` (proves the wider window), reranker crash degrades to the fused order.

  Eval numbers (recorded in the commit body): flag OFF recall@10 14/15 (0.933) MRR 0.782 (bit-identical to R.8); flag ON recall@10 14/15 (0.933) MRR 0.776. The reranker rescued the baseline's known miss (`grit` -> paraphrase_0001, now rank 7) but pushed "building things with your hands" (rank 9 -> outside top 10), a net recall tie and a small MRR loss. **Flag stays OFF by default** - recall ties, MRR favors off.

### R.10 - Exact-needle escape hatch

- [x] **R.10 [AGENT]** Pin quoted-phrase matches.

  Anchor: `search_results()` at `src/enqueue/retrieve/candidates.py:162-200`.
  When the free-text query is wrapped in double quotes, run a phrase match against `fts_chunks_tri` (trigram substring semantics) and the unicode61 table, and pin those artifacts at the top with `why="exact"`, above the hybrid results, deduped by artifact id.
  Test: two notes, one containing the exact phrase `tony tony chopper`, one containing the words scattered; the quoted query `"tony tony chopper"` returns the exact note first.

  Done when: `uv run pytest tests/test_search_results.py -q` green including the quoted-phrase test.

### R.11 - Phase gate

- [x] **R.11 [AGENT]** Full verification and measurement.

  Done when: `bin/verify` passes; `uv run black --check src/ tests/` passes; `uv run python scripts/search_eval.py` final numbers are recorded in the phase-close commit body alongside the R.4 baseline; `AGENTS.md` retrieval and ingest sections reflect annotation indexing, the trigram branch, the fuzzy branch, and the new status semantics.

---

## Phase C - Quick-capture overlay

Surface: `src/enqueue/static/capture.html` (512 lines, standalone by design) plus its Tauri capability.
Mode: Operate. Color strategy: restrained; one lavender accent; dosage is a single disc at rest, a kind-hue dot on detection, and one accent flash on success.
Delight thesis: the overlay should feel like tearing a slip off the same pad as the main app - instant, certain, branded.

### C.1 - Fix the outside-click dismiss regression

- [x] **C.1 [AGENT]** Grant the event permission the focus listener needs.

  Anchor: `desktop/tauri.conf.json`, the `capture-overlay` capability `permissions` array (currently `["allow-capture-dismiss", "allow-capture-drag"]`).
  Add `"core:event:allow-listen"` and `"core:event:allow-unlisten"`.
  Rebuild: `cd desktop && cargo build`, then `bin/relaunch --build`.
  Manual verification, in order: press the hotkey, type nothing, click on another app's window; the overlay must hide. Press the hotkey again; it must reappear with the previous text intact (Escape-preserves-text behavior lives at capture.html:389-396 and must not regress). Press the hotkey, type a note, press Enter; it must keep and dismiss.
  If the overlay still persists after the permission change, open the webview inspector on the capture window, read the exact `not allowed` error, and add the permission it names; only if no permission resolves it, move the dismiss to Rust (an `on_window_event` `Focused(false)` arm for label `capture` mirroring the `hasHeldFocus` guard with an `AtomicBool`) and delete the JS listener at capture.html:301-320.

  Done when: the three-step manual path passes on the rebuilt shell, and `rg -n "core:event:allow-listen" desktop/tauri.conf.json` finds the permission.

### C.2 - Align overlay tokens with the app

- [x] **C.2 [AGENT]** Fix the five drifted values from GT.3.

  All in `capture.html`:
  (a) `#card` border-radius (line ~107): `var(--r-sm)` -> `var(--r-lg)`, and add `--r-lg: 12px` to the overlay `:root`.
  (b) `#card` box-shadow (line ~108): replace `--shadow-1` with a new `--shadow-lifted: 0 8px 28px rgba(16, 17, 20, 0.08)` token, matching the museum pill.
  (c) `#field::placeholder` (line ~170): `var(--text-mute)` -> `var(--ink-faint)`, adding `--ink-faint: #6c6f84` to `:root`.
  (d) `.label.problem` (lines ~147-149): color `var(--pink)` -> `var(--danger)`, adding `--danger: #b4332b` to `:root`. The pink stays only as the image-kind hue if C.3 adds it.
  (e) Focus: remove `outline: none` from `#field` (line ~160) and give `#card:focus-within` the app's ring: `border-color: var(--accent-strong)` plus `box-shadow: 0 0 0 3px var(--lavender-subtle)` with `--lavender-subtle: rgba(113, 50, 245, 0.16)` added to `:root`.
  Keep every other token byte-identical to museum.html's `:root` values.

  Done when: `bin/check-contrast` passes; `rg -n "ink-faint|danger|shadow-lifted|r-lg" src/enqueue/static/capture.html` shows the new tokens; the overlay visually matches a museum floating surface (manual check via hotkey).

### C.3 - Colorize + delight pass

- [x] **C.3a [AGENT]** Brand mark at rest.

  In the `#bar` (capture.html:194-197), add a 10px lavender disc before the `Enqueue` label: a `<span>` with `background: var(--accent)`, `border-radius: 50%`, matching the keep disc language at museum.html:1863.
  Static element, no animation, no layout shift to the 30px bar.

  Done when: hotkey shows the disc; `bin/verify` passes.

^- [x] **C.3b [AGENT]** Kind-hue dot on detection.

  In `paint()` (capture.html:259-275), when `kindLabel` shows `Note`, `Link`, `Link + note`, or a file count, prefix the label with a 6px dot in the matching kind hue: `--kind-note: #30804b`, `--kind-link: #376899`, `--kind-image: #8f4273`, `--kind-file: #755c12` (add these tokens to `:root`; values from museum.html:191-201).
  Implement as a `dot` span whose `background` is set from a small `KIND_HUES` map; file drops use `--kind-file` unless every item is an image, then `--kind-image`.
  Empty field hides the dot.

  Done when: typing a URL shows a blue dot, plain text a green dot, dropping an image a pink dot; `bin/verify` passes.

^- [x] **C.3c [AGENT]** The "kept" beat.

  In `keep()` (capture.html:344-385), after successful save and before `dismiss()`: set status text to `Kept.`, set `#card` border-color to `var(--accent-strong)`, wait 200ms, then dismiss.
  Total added latency must stay at or under 250ms.
  Wrap the beat in a `matchMedia("(prefers-reduced-motion: reduce)")` guard: reduced motion skips the flash and dismisses immediately.
  Apply the same beat to the paste-image and drop paths after `keepFiles` succeeds (lines ~434 and ~484).

  Done when: manual hotkey run shows the flash on keep, paste, and drop; reduced-motion (macOS Reduce Motion on) dismisses with no flash; `bin/verify` passes.

^- [x] **C.3d [AGENT]** Keycap hint.

  Render the footer hint `Return to keep` (capture.html:204-207) as a keycap plus text: `<kbd>Return</kbd> to keep`, styled to match the museum keycap at museum.html:424 (copy the rule into the overlay stylesheet; it is small and the overlay is standalone on purpose).

  Done when: visual check against the museum keycap shows the same treatment; `bin/verify` passes.

### C.4 - Trim dead overlay tokens

^- [x] **C.4 [AGENT]** Delete what the overlay does not use.

  In capture.html: remove the `@font-face` block for weight 700 (grep the file first: if `700` or `wght..700` appears only in that block, delete it; museum.html is handled separately in M.2, not here).
  Remove unused `:root` tokens after C.2/C.3 land; the known-dead set today is `--accent` (unused, `--accent-strong` carries the hover), `--mono`, `--r-full`, `--surface-2`, `--text-dim`.
  Verify each with `rg -n "var\(--TOKEN\)" src/enqueue/static/capture.html` returning zero before deleting it.

  Done when: the five greps return zero and the tokens are gone; `bin/verify` passes.

---

## Phase M - Delete, rename, split

Order matters: delete dead code first so the rename and the split carry no corpses.

### M.1 - Delete dead files

^- [x] **M.1 [AGENT]** Delete, verifying zero references first.

  For each: run the given grep, expect no matches outside `desktop/target/`, then `git rm`:
  (a) `src/enqueue/static/museum-plain.html` and `src/enqueue/static/capture-plain.html` (`rg -n "plain" src/ desktop/src desktop/tauri.conf.json bin/ scripts/ tests/ | rg -v target`).
  (b) `evals/results/lens-qdrant.json`, `evals/results/qdrant-ablation.json`, `evals/results/qdrant-baseline.json`, `evals/results/qdrant-via-interface.json` (`rg -n "qdrant" bin/ scripts/ evals/*.md` - `bin/check-eval` reads only `sqlite-vec.json`).
  (c) The byte-identical `_review_artifacts` pairs: keep `02-main-full.png` and `a2-settings.png`, delete `02-full-page.png` and `02-settings-view.png` (confirm with `md5` first).
  (d) `assets/logo.png` versus `assets/enqueue-logo.png`: grep both names repo-wide; if both are unreferenced, keep `enqueue-logo.png` and delete `logo.png`.
  (e) The tracked `desktop/icons/__pycache__/make_icon.cpython-314.pyc`: `git rm --cached` it and append `__pycache__/` to the desktop section of `.gitignore` if not already covered.

  Done when: all greps return empty, the files are gone, and `bin/verify` passes.

### M.2 - Delete dead JS and CSS in museum.html

^- [x] **M.2a [AGENT]** Dead JS functions. For each, verify with `rg -n "NAME" src/enqueue/static/museum.html` that the only matches are the definition and the call sites listed, then delete both:
  `doCurate` (~9663-9765, zero callers), `showChatList` (~8476-8505), `togglePin` (~8606-8617), `toAccelerator` (~8944-8983), `bucket` + `MONTHS` (~5504-5541), the empty `showRail` stub (~8445) plus its three call sites (~8154, 8676, 8769), the shadowed `toggleRail` stub (~8446), the real `toggleRail` + `#btnRail` button + its media rule (~8621-8630, 3755-3758), the never-assigned `eyeTimer` (~5841, 5928-5931).
  After deleting `doCurate`, simplify `back(chatId)` (~9767-9773): the `chatId` parameter is only used by `doCurate`; make `back()` take no argument and update its remaining callers.

  Done when: each name greps to zero; `bin/verify` passes; the wall, a chat, a saved view, and settings all still open (manual smoke).

- [x] **M.2b [AGENT]** Dead CSS. Verify zero usage in the JS region before deleting each block:
  the rail family (`.rail`, `.threadrow`, `.thread`, `.rowbtn`, `.kept`, `.railfoot`, ~3034-3177), `.rail-h` rules (~1634-1664), `.when` (~1619-1632), the `.h1row` family (~2124-2168), `.pin`/`.pin.lit`/`@keyframes kept` (~2649-2673), `.leaf.hit` (~3014-3016), dead tokens `--accent-quiet` (~112), `--lavender`, `--lavender-hover` (~130-133), `--focus` (~210-213), `--info`, `--success`, `--warning` (~155-160; their `--tint-*`/`--badge-*` derivatives stay), `--r-xs`, `--r-xl` (~233, 238).
  Also fix the live bugs in the same pass: replace `var(--surface-1)` with `var(--surface)` at ~712, 771, 804; replace `var(--text-2)` with `var(--text-mute)` at ~985, 988; change `.card { padding: var(--sp-sm) }` (~1416) to `var(--sp-3)`; replace the four literal NUL bytes in the markdown fence placeholder (~3837-3845) with the two-character escape `\x00` inside the JS string.

  Done when: `bin/verify` passes (this is the contrast gate too); wall cards above the 1280px breakpoint visibly regain 12px padding; `rg -c $'\x00' src/enqueue/static/museum.html` returns 0.

  ^= Note (kept tokens): `--lavender`, `--info`, `--success`, `--warning` stayed in `:root`
  despite the delete list: `bin/check-contrast` hardcodes them as contract tokens
  (`BOUNDARY_RULES`, `TEXT_RULES`, `FILL_ONLY`) and the done-when requires the contrast
  gate to pass - the spec's own zero-usage guardrail applied to tokens finds them
  referenced by the checker, exactly like M.2a keeping `--accent`/`--mono`. The truly
  dead tokens `--accent-quiet`, `--lavender-hover`, `--focus`, `--r-xs`, `--r-xl` were
  deleted. Verified via CDP: 5-up >1280px cards show 12px padding, 4-up/3-up below show
  16px; all 4 NUL bytes now the `\x00` escape (file reads as text, `rg` clean).

### M.3 - Delete dead Python

- [x] **M.3 [AGENT]** Verified dead code removal:
  (a) `redact()` in `ingest/secrets.py:57-61` (zero callers).
  (b) Unused imports: `re` and `db` in `ingest/entities.py:25,30`; `json` and `uuid` plus the stale `noqa` comments in `derive.py:29-30`; drop the stale `noqa` on `derive.py:36` and the stale comment in `pivot.py:25`.
  (c) `_stub()` in `assistant.py:43-44`.
  (d) `greeting.ensure()` in `greeting.py:93-98` and its one caller at `api.py:1389`, plus the stale "generated in the background" comment at api.py:1386-1388.
  (e) `chonkie` from `pyproject.toml` dependencies and the `index` extra (zero imports repo-wide); run `uv sync` after.
  (f) `enq reindex` (cli.py:122-150): it touches the database directly, violating cli.py's own boundary rule, and duplicates `enq index`; delete the command.
  (g) `_run_verify()` in cli.py:535-577: replace its body with a call to the real `verify()` catching `typer.Exit`.
  (h) The six copied `_now()` helpers (notes.py:25, capture.py:38, chats.py:55, tags.py:21, pivots_saved.py:24, chats_worker.py:55): add `def now()` to `db.py` and delete five copies.
  (i) `secret_report()` at api.py:1106-1115 is deleted together with the M.4a route fix.
  (j) `_consume_lens()` at api.py:462-546 is only called by tests: leave it in place; M.5a deletes it outright along with the lens surface.

  Done when: `uv run pytest -q` passes; `uv run black --check src/ tests/` passes; `uv run enq --help` no longer lists `reindex`; `rg -n "chonkie" pyproject.toml uv.lock` is clean after `uv sync`.

### M.4 - Fix the small bugs found in the sweep

- [x] **M.4a [AGENT]** `/secrets` route shadowing.
  Anchor: api.py:1095-1097 stacks `@app.get("/secrets")` and `@app.get("/greeting")` on `get_greeting()`, so `GET /secrets` returns the greeting.
  Fix: attach `@app.get("/secrets")` to `secret_report` (1106-1115) instead of deleting it, so the documented endpoint (AGENTS.md API surface) actually works.
  Test: `TestClient(app).get("/secrets")` returns the secrets payload shape, and `/greeting` still returns a greeting.

  Done when: `uv run pytest -q` green including the new test.

- [x] **M.4b [AGENT]** Hotkey rebinding takes effect without relaunch.
  Anchors: `recordHotkey` at museum.html:8989-9039; registration once in `desktop/src/main.rs:448-458`.
  Add a Tauri command `hotkey_changed` that unregisters the old shortcut and registers the value from `hotkey()`; call it from the `recordHotkey` success path.
  Register the command in `generate_handler!` (main.rs:374), add it to `build.rs` commands, and add `allow-hotkey-changed` to the `museum-links` capability in tauri.conf.json.
  If the rebind throws, surface the error in settings and keep the old binding.
  Fallback if this proves flaky after a real attempt: settings copy under the recorder reading `Takes effect after relaunch.`

  Done when: manual path passes (rebind in settings, press the new shortcut immediately, overlay opens); `cd desktop && cargo build` succeeds; `bin/verify` passes.

- [x] **M.4c [AGENT]** Greeting retry dead weight.
  Anchors: `refreshGreeting` retry loop at museum.html:5946-5966 and the 60s poll at ~5975; `greeting.py` now always returns `generated: False`.
  Fetch once per home render; delete the retry counter, the 8s retry, and the interval.
  Add a reduced check: `rg -n "greetTries" src/enqueue/static/museum.html` returns zero.

  Done when: `bin/verify` passes; the greeting still renders on home (manual).

- [x] **M.4d [AGENT]** Stale comments and dead class.
  Fix the Qdrant-era docstring at `ingest/queue.py:8` (the worker is single-threaded because the index lives inside the SQLite file and embedding models are large, not because of a directory lock).
  Fix the `relevance` ordering comment at api.py:220-234 (no UI control advertises it; keep the defensive 400).
  Delete the unstyled `class="frame"` at museum.html:4694 and 4737 (the inline style does the work).

  Done when: greps confirm each; `bin/verify` passes.

### M.5 - Delete the lens/curate engine surface

Decision (Minh, 2026-08-10): delete. No dead endpoints hang around.
Facts: `POST /lens` (api.py:434-459) and `POST /curate` have no UI caller (no `EventSource` or `/lens` fetch in museum.html; `doCurate` deleted in M.2a).
The R.4 golden-set harness takes over retrieval evaluation, so the lens-eval path has no remaining consumer either.

- [x] **M.5a [AGENT]** Delete the endpoints and their modules.
  Delete from api.py: the `POST /lens` handler, `_lens_sse`, `_consume_lens` (~427-546; this supersedes M.3j, delete outright), the `POST /curate` handler (chats/curate region ~908-1041), and the two lens-cache endpoints (~785-800).
  Delete the modules: `retrieve/curate.py`, `retrieve/expand.py`, `retrieve/lens.py`, `retrieve/score.py`, `retrieve/judgments.py`.
  Before deleting each module run `rg -n "retrieve\.(curate|expand|lens|score|judgments)|from \.\.?retrieve import" src/ tests/` and confirm no live importer; if `chats.py` or `pivot.py` imports any of them, stop and report instead of deleting blind.
  `retrieve/candidates.py` and `retrieve/rerank.py` stay: they power `/search` and are imported by chats.

  Done when: `uv run pytest -q` green after the deletions.

- [x] **M.5b [AGENT]** Delete the CLI commands: `enq curate`, `enq lens-eval`, `enq lens-cache` from `cli.py`.

  Done when: `uv run enq --help` lists none of them; `uv run pytest -q` green.

- [x] **M.5c [AGENT]** Delete the tests: `tests/test_lens.py`, `tests/test_lens_api.py`, `tests/test_lens_cache.py`, `tests/test_score.py`, `tests/test_expand.py`, plus any curate/lens cases inside other test files (`rg -n "lens|curate" tests/`).

  Done when: `uv run pytest -q` green with the files gone.

- [x] **M.5d [AGENT]** Remove the lens settings: `ENQ_LENS_SCORE_THRESHOLD`, `ENQ_LENS_JUDGE_TOP`, `ENQ_LENS_JUDGE_TOP_MAX` from `config.py`, from `settings.py` writable fields, from the settings UI fields in museum.html, and from README/docs mentions.

  Done when: `rg -n "LENS_" src/` returns nothing; settings page renders (manual); `bin/verify` passes.

- [x] **M.5e [AGENT]** Drop the cache table and eval artifacts.
  New migration (next unused revision number after the current head 0019, adjusting if P.1 already claimed one) dropping `lens_judgments`; it is a derived cache, safe to drop.
  Delete `evals/lens/` and the lens sections of `docs/EVAL.md`; run `rg -n "lens|curate" bin/ scripts/ evals/` and remove anything referencing the deleted surface (keep `evals/corpus` prose and historical migrations untouched).

  Done when: `uv run pytest tests/test_migrations.py -q` green; the grep returns only corpus prose and migration history.

- [x] **M.5f [AGENT]** Update `AGENTS.md`: remove the lens/curate rows from the module map, API surface, CLI surface, and config table; rewrite the curate and lens flows under "Key data flows" and "Retrieval architecture"; amend resolved decision 10 to record that the SSE lens surface and curate were removed.

  Done when: the listed sections read true; `rg -in "lens|curate" AGENTS.md` returns only the removal note.

- [x] **M.5g [AGENT]** With the lens surface gone, move RRF to the canonical constant.
  Anchor: `store_sqlite.py:522-532` passes `k=1` with a comment tying the score scale to the lens threshold.
  Change `k=1` to `k=60` and rewrite the comment: the threshold it names no longer exists, and k=60 is the value from the RRF paper.
  Record `scripts/search_eval.py` recall@10 before and after in the commit body; ranking is allowed to shift, recall must not drop.

  Done when: `uv run pytest tests/test_fusion.py tests/test_store_sqlite.py tests/test_search_results.py -q` green; eval numbers in the commit body.

### M.6 - Consolidate duplication

- [x] **M.6a [AGENT]** One `modalShell()` factory in museum.html replacing the six hand-rolled dialogs (`ask` ~4487-4535, `askText` ~4541-4597, `askGroupName` ~4603-4676, `openCustomPicker` ~5238-5348, `pickArtifact` ~7857-7955, `pickGroup` ~8012-8068).
  The factory owns: dialog creation, the `done` guard, `finish()`, `box.close()` in try/catch, the `cancel` listener, and Escape handling.
  Behavior must be pixel-identical; this is a pure refactor.

  Done when: `bin/verify` passes and each dialog opens, cancels, and confirms by hand (manual smoke of: rename view, add to view, custom picker, artifact picker).

- [x] **M.6b [AGENT]** One SVG base rule in the CSS: `svg { fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round }`, with per-context rules carrying only width/height.
  This deletes the repeated declarations at ~1282, 1940, 2054, 2380, 2445, 2254, 893, 934, 348, 3679, 761 (line refs pre-M.2; re-anchor).

  Done when: `bin/verify` passes; icons render identically (visual spot check of wall, pill, drawer).

- [ ] **M.6c [AGENT]** One `_weighted_hits()` helper in `retrieve/candidates.py` for the staleness check + trust weighting, replacing the four copies (facet/entity loops in `candidates()` ~108-139 and `_hybrid_results()` ~221-251).

  Done when: `uv run pytest tests/test_search_results.py tests/test_rerank.py -q` green.

- [ ] **M.6d [AGENT]** One `Worker` class shared by `ingest/queue.py` and `chats_worker.py` (identical queue/Event/thread lifecycle, ~40 lines each).

  Done when: `uv run pytest tests/test_ingest.py tests/test_chats_worker.py -q` green.

- [ ] **M.6e [AGENT]** Merge the remaining JS twin implementations, one pair at a time, keeping the better name: the custom-picker row builder (`openCustomPicker.refresh` vs `refreshCustomPicker`, ~5264-5312 vs 5353-5411), the collapse plumbing (wall ~5151-5195 vs pivot ~7517-7571, one helper parameterized by storage key), the wall section renderers (~5021-5059 vs 5116-5146), the move-correction flows (`pivotMove` ~7962-8006 vs `chatPivotMove` ~8382-8432), the exclude-and-rerun trio (~7678-7812), the two trash row renderers (~8802-8828 vs 9566-9596), the settings `fieldRow` markup (~9179-9202, 9249-9272, 9438-9448, 9533-9545), and `linkFace` using `host()` (~6575-6581 vs 4903-4909).

  Done when: `bin/verify` passes after each pair; the affected surfaces smoke clean by hand.

### M.7 - Rename museum to home

- [ ] **M.7 [AGENT]** Rename every code identifier; mechanical and complete.

  File moves (use `git mv`): `src/enqueue/static/museum.html` -> `src/enqueue/static/home.html`.
  Code identifiers: `api.py:71-72` `def museum()` -> `def home()` serving `static/home.html`; `desktop/src/main.rs` `CameFromMuseum` -> `CameFromHome` (struct at :40, uses at :259-264, 289-294, 372) and locals `museum`/`from_museum` -> `home`/`from_home`; `desktop/tauri.conf.json` capability id `museum-links` -> `home-links` and its description; `bin/check-contrast:2,32,164` the `MUSEUM` path variable; `bin/verify:15` `FILES[0]`; `bin/relaunch:40` the page loop.
  User-facing strings: `chats.py:374,379` `ask the whole museum instead` -> `ask the whole library instead`.
  Comments and docstrings mentioning the museum in main.rs, home.html, capture.html, api.py, preview.py, schemas.py, tests: rewrite to `home` or `library` as fits; this is a vocabulary pass, not a behavior change.
  Docs in the same change: `AGENTS.md` (module map static table, the two-windows list, the Tauri section), `README.md`.
  Do NOT touch `evals/corpus/*.md` or `scripts/make_test_corpus.py` content fixtures; those are fictional test data, not product vocabulary.
  Sweep for remaining museum-esque terms in product surfaces (`exhibit`, `gallery`, `salon`, `placard`, `docent`, `curator` as UI copy or identifiers; `wall` stays - it is the shipped name of the home surface) and replace any UI copy hits with neutral words.

  Done when: `rg -in "museum" src/ desktop/src desktop/tauri.conf.json bin/ tests/ AGENTS.md README.md` returns nothing outside `evals/corpus` and `.git`; `cd desktop && cargo build` succeeds; `bin/verify` passes; `bin/relaunch --build` brings the app up and the main window loads (manual).

### M.8 - Split home.html

- [ ] **M.8 [AGENT]** Split the file along the GT.6 plan, after M.2/M.6 deletions are in.

  Target layout (plain scripts, one global scope exactly as today, no build step, no ES modules):
  `static/home.html` (shell: meta, font preloads, `<link>` tags, the `#topbar`/`#view`/`#pill`/`#dropover` skeleton, ordered `<script src="/static/js/...">` tags),
  `static/css/tokens.css`, `base.css`, `home.css`, `artifact.css`, `reader.css`, `chat.css`, `settings.css`, `pill.css` (sections per the sweep table: tokens 74-278; base/type/buttons/callouts/rows; topbar+searchbar+homehead+eye+wall+cards+groupbar+tagbar; artifact+drawer+editor+docpane; reader+findbox+folio; transcript; settings; pill+menu+toast+dialog+dropover+animations),
  `static/js/util.js` (esc/api/rowKey/host/since/bytes/toast), `icons.js`, `md.js`, `dialogs.js`, `pill.js`, `morph.js`, `home.js` (home, eye, greeting, drop, wall grouping, card, pager, router, refreshIfStale), `artifact.js` (artifact view, tags/views rows, find, reader, editor), `search.js`, `pivot.js`, `chat.js`, `trash.js`, `settings.js`, with the boot call last.
  Load order: util, icons, md, dialogs, pill, morph, home, artifact, search, pivot, chat, trash, settings.
  Move CSS verbatim by section; move JS verbatim by function; the only new code is the HTML shell and the `modalShell` consolidation already done in M.6a.
  Retarget: `api.py` `/` handler reads `static/home.html`; `bin/verify:15` parses the new JS files (extend the loop over `static/js/*.js`); `bin/check-contrast` reads `:root` from `static/css/tokens.css` and adds capture.html token coverage while it is being edited.

  Done when: `bin/verify` passes; `bin/relaunch` smoke passes this manual checklist: wall renders, search returns hits, an artifact opens, a chat answers, settings opens, the capture hotkey works; `rg -n "museum\.html" src/ bin/ desktop/` returns nothing.

### M.9 - Split api.py into routers

- [ ] **M.9 [AGENT]** Convert `api.py` (1460 lines) into an `api/` package with one `APIRouter` per domain.

  Domains and current anchors: `static.py` (51-89), `artifacts.py` (read 95-424 + 549-657, trash 148-193), `write.py` (663-771), `admin.py` (774-885), `search.py` (890-905), `chats.py` (908-1041), `settings.py` (1044-1115), `pivots.py` (1118-1362), `app.py` (app factory, startup warmup 1365-1460, `serve()`).
  No lens router is created; M.5 deletes that surface.
  Shared wall helpers (`_excerpt`, `_ARTIFACT_COLUMNS`, `_link_images`, `_wall_tags`, `_wall_item`) move to `api/wall.py`.
  Promote the function-level imports (785, 793, 816, 863, 892) to top-level imports in their routers.
  No behavior changes; the OpenAPI paths must stay byte-identical.

  Done when: `uv run pytest -q` green; `uv run black --check src/ tests/` passes; `uv run enq serve` boots and `uv run enq health` reports normally; `AGENTS.md` module map updated.

---

## Phase P - Performance

Measure first: these are verified smells, each with a deterministic check.

### P.1 - Index the wall's sort key

- [ ] **P.1 [AGENT]** New migration (next unused revision number; if M.5e already created one, this follows it) adding `CREATE INDEX idx_artifacts_touched ON artifacts(deleted_at, pinned, updated_at DESC)`.
  The wall default order is `updated_at DESC` (api.py:228) and today every wall page is a scan plus sort.

  Done when: `uv run pytest tests/test_migrations.py -q` passes; `uv run python -c "import sqlite3; ..."` running `EXPLAIN QUERY PLAN SELECT ... ORDER BY updated_at DESC` on a migrated dev database shows the index used (paste the plan into the commit body).

### P.2 - Batch the N+1 queries

- [ ] **P.2 [AGENT]** Replace per-row loops with one `json_each` IN-query each:
  (a) candidate titles, `retrieve/candidates.py:144-156` (up to 150 SELECTs per curate);
  (b) the snippet/title fetches in `_hybrid_results`, candidates.py:255-289;
  (c) the `hit_is_stale` probe, candidates.py:50-67 (prefetch all candidate artifacts' `body_version` once per request);
  (d) `artifact_text` in `retrieve/rerank.py:154-185` (batch bodies + chunks for the candidate set);
  (e) view membership in `GET /artifacts/{id}`, api.py:575-589 (one query for all specs, no per-view `get()`);
  (f) `chat_topics` full-table load in `chats.py:157-159` (filter by the listed chat ids).
  Add one regression test per fix where a count is observable (e.g. assert the wall item query count via a sqlite trace hook or by asserting identical output with 1 vs N artifacts present).

  Done when: `uv run pytest -q` green; behavior identical (existing tests cover the shapes).

### P.3 - Stop serial round trips in the UI

- [ ] **P.3 [AGENT]** In home.html (post-split paths; re-anchor):
  (a) `removedSection` serial artifact fetches (~7617-7632) -> one `Promise.all`;
  (b) `deletePivotGroup`'s N sequential exclude POSTs (~7744-7755) -> one bulk POST (add a plural exclude endpoint accepting a list, mirroring the single one);
  (c) the organize-turn hydration on every poll tick (~8278-8280) -> hydrate only when the transcript hash actually changes (`transcriptChanged` already computes this);
  (d) `home()` always fetching `/tags` (~5673) -> fetch only when `wallGroup === "tags"`.

  Done when: `bin/verify` passes; each flow still works by hand; the bulk endpoint has a pytest.

### P.4 - Optional, only if measured slow

- [ ] **P.4 [HUMAN-GATED]** PDF page render cache (`capture.py:384-407` re-rasterizes per request) and streaming upload bodies (api.py:750 reads whole files into memory).
  Do these only with a before/after measurement attached: time `GET /artifacts/{id}/page/{n}` twice for a 100-page PDF, and peak memory during a 200MB upload.

  Done when: measurements are in the commit body and `uv run pytest -q` is green.

---

## Final gate

- [ ] **F.1 [AGENT]** Everything green at once.

  Done when: `bin/verify` passes; `uv run black --check src/ tests/` passes; `uv run pytest -q` passes; `scripts/search_eval.py` final recall@10 is recorded next to the R.4 baseline at the top of this file; `AGENTS.md` reflects the new file layout, the renamed surfaces, and the retrieval changes; the manual smoke list (hotkey capture with kept flash, outside-click dismiss, wall, search with the quoted query `"tony tony chopper"` returning the image, artifact open, chat, settings, trash) passes on a fresh `bin/relaunch --build`.
