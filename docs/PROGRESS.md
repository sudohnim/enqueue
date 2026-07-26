# Enqueue POC - task list

Status: **23 of 35 tasks.** Phases A to G are built; the pipeline runs end to end. Phase H, the evaluation harness, is the remainder.

This builds Milestone 0 from [PRODUCT.md](PRODUCT.md): a CLI that captures, ingests, indexes, curates, and measures itself. No user interface. No encryption. No sync. No Android.

```bash
enq serve                     # engine on 127.0.0.1:8787, CLI is a client of it
enq import-fabric PATH        # or whatever loader exists
enq chunk && enq facet-gate
enq facets                    # slow, resumable, commits per artifact
enq index                     # dense plus sparse
enq search "..."              # no model calls
enq curate "antifragility"    # a room
```

### Four things that only showed up by building

Each was invisible in the spec and would have shipped broken.

1. **Facets were paraphrase, not abstraction.** Every level-2-plus statement opened "This writing demonstrates...", describing the artifact rather than making a claim, and passed every validator. A self-reference ban in the schema and the prompt fixed it. This is the moat, and it was silently dead.
2. **instructor renamed `validation_context` to `context`.** The wrong keyword does not error, it silently disables every context-dependent validator, including the proper-noun ban.
3. **Titles were never indexed.** A note whose title is the only place a name appears was unfindable by that name. The author's Epictetus note is his own paraphrase and never contains the word. Prepending the title at index time fixed it.
4. **Dense retrieval alone cannot find names.** Measured, not assumed: "what did Epictetus say about control" returned The Prince. Hybrid dense plus sparse with RRF is load-bearing, not an optimisation.

### Reference numbers from one real run

Evidence the parser and chunker handle real input. Not a baseline to reproduce.

| | Value |
|---|---|
| Artifacts | 122 (76 notes, 8 blobs, 38 bookmarks) |
| Blocks | 2,319 |
| Chunks | 633, median 38 words |
| Facet-eligible | 52 of 76 notes |
| Facet generation | about 96s per artifact on `llama3.1:8b` |
| Chunk indexing | 633 points in about 170s, dense plus sparse |

The chunk count is the load-bearing one. A first version produced 1,421 chunks at a median of 17 words, because pasted model output shreds into headings. Merging childless paragraphs while leaving claim-plus-elaboration units intact fixed it.

Work through the tasks **in order, one at a time**. Check a box only after its "Done when" is verified by actually running the command shown. Do not start a task until the previous one is checked.

## Rules for the implementing agent

- **Do exactly one task per turn.** Report what changed and how you verified it. Do not batch tasks.
- **Never commit.** The human commits.
- **If a task and a spec document disagree, the spec wins.** Specs are [PRODUCT.md](PRODUCT.md), [AGENTS.md](../AGENTS.md), [CURATION.md](CURATION.md), [EVAL.md](EVAL.md).
- **Do not invent libraries or model names.** Every dependency and model id you need is written in this file. If something seems missing, stop and say so rather than substituting.
- **Do not refactor code from earlier tasks** unless a task tells you to.
- **Never use an em dash** in code, comments, docs, or commit messages. Use a plain dash.
- Format Python with `black`. Run it before reporting a task done.

## Hard rules that are easy to break

These come from the specs. Violating any of them silently breaks the product. Re-read this list before each task.

1. **Never put text in a Qdrant payload.** Payloads hold `artifact_id`, `chunk_id` or `facet_id`, and `embed_version`. No titles, no URLs, no excerpts. Text lives in SQLite and is fetched by id after retrieval.
2. **Never use instructor's default `TOOLS` mode.** Pass the mode explicitly, per adapter.
3. **Never flatten the bullet nesting** when parsing Fabric HTML. The nesting is the author's thinking structure.
4. **Never modify or delete a row in `artifacts`, `blocks`, or `note_entries` after insert.** They are append-only. Editing a note **appends a new entry** with `supersedes_id` set. There is no `UPDATE` on user-authored text anywhere in this codebase.
5. **Never use retrieval inside the proposal pass** in Phase H. That would score the system against its own blind spots.
6. **Never report `recall@150` on this corpus.** It has 76 artifacts, so recall is trivially 1.0. See [EVAL.md](EVAL.md) for the two regimes.
7. **Run the secret scan before any text is sent to a model.** The source corpus is known to contain a plaintext password.

---

## Context (read once before starting)

### What this POC is proving

That a hand-built furniture article can surface under "antifragility" when the two share no vocabulary. Everything in this task list exists to make that testable.

At 76 artifacts the candidate pool is the whole corpus, so **this POC measures judgment, not retrieval**. The metric is `hard-hit@15`: do the hard analogies rank into the top fifteen after reranking.

### The corpus

**Throwaway. The store gets deleted and rebuilt freely.**

A Fabric export was used once to learn the shape of real input, and the parser is built and tested against that shape. It is **not** the working corpus and is not imported during development.

What the format taught us, and what the parser therefore handles:

- TipTap HTML, with `data-uuid` and `data-created-at` on every node.
- Nesting is semantic: a top-level `<li>` is a claim, nested `<li>` elements elaborate on it. Flattening destroys the signal.
- Real notes range from one word to 2,600. Many are under 50.
- Pasted model output is mixed in with authored notes, and it shreds into headings and single list items unless childless paragraphs are merged.
- Netscape bookmark files carry URL, title, and `ADD_DATE` only, with no content.
- Credentials turn up in snippets, which is why the secret scan runs before any model call.

For development, load junk. When there is something worth keeping, delete the store and start clean.

**The eval corpus is a separate problem.** Junk data has no genuine analogies, and the whole point of the golden set is measuring whether hard analogies surface. See Phase H.

### Models and the privacy decision

**The human must choose before task A1. Do not choose for them.**

Facet generation is the moat, and bad facets are permanent pollution rather than a weak result: a placard is read once and forgotten, a facet is embedded and votes on every future retrieval. A 7B running locally may never climb past level 2, which would make the whole evaluation measure the model rather than the architecture.

But the Lumo API has not shipped, so "the good model" means a hosted one, and the corpus is the human's real notes.

| Path | What happens |
|---|---|
| **A. Hosted, pre-scrubbed** (recommended) | Mark `biz_` and `snippets` as `local_only` before the first facet run, then use OpenRouter. Books and mental models, which are the interesting material, go to a strong model. Nothing sensitive leaves the machine |
| B. Fully local | Ollama for everything. Nothing leaves the machine at all. Accept that a poor result may be the model rather than the design |

Under either path, `local_only` artifacts route to Ollama. That mechanism is the same.

Whichever is chosen, record it at the top of every eval run, because a score is meaningless without knowing which model produced the facets.

| Purpose | Model |
|---|---|
| Embeddings | `BAAI/bge-base-en-v1.5` via `fastembed`, 768 dimensions, ONNX, no PyTorch |
| Facets, rerank, synthesis, path A | an OpenRouter model the human names |
| Facets, rerank, synthesis, path B | `qwen2.5:7b-instruct` via Ollama |
| Anything marked `local_only` | `qwen2.5:7b-instruct` via Ollama, always |

`qwen2.5:7b-instruct` is chosen for a 16GB M1. **Do not substitute a larger local model.**

### The Ollama endpoint is `127.0.0.1`, not `localhost`

**This machine has two Ollama instances.**

A native one listening on `127.0.0.1:11434`, and a Docker container from an unrelated project listening on the IPv6 wildcard `*:11434`. `localhost` resolves to IPv6 first, so any client using `http://localhost:11434` reaches the **Docker** instance, which has different models.

**Always use `http://127.0.0.1:11434/v1`.** If a model you pulled is reported as missing, this is why. Verify with:

```bash
curl -s http://127.0.0.1:11434/api/tags | grep -o '"name":"[^"]*"'
```

That must list `qwen2.5:7b-instruct` before you start Phase A3.

### Layout

```
enqueue/
  pyproject.toml
  src/enqueue/
    __init__.py
    cli.py              typer entry point
    config.py           paths, model ids, constants
    db.py               sqlite3 connection, schema application
    schema.sql
    providers/
      base.py           the Provider protocol
      ollama.py         the only adapter in the POC
    ingest/
      fabric.py         TipTap HTML parser
      secrets.py        secret scanning
      importer.py       files to artifacts
      chunk.py
      facets.py
    index/
      embed.py
      qdrant.py
    retrieve/
      expand.py
      search.py
      rerank.py
      synthesize.py
    schemas.py          all pydantic models from CURATION.md
  eval/
    golden.yaml
    harness.py
  tests/
```

---

## Phase A - Skeleton

### A1. Project skeleton and CLI

- [x] **Files:** `pyproject.toml`, `src/enqueue/__init__.py`, `src/enqueue/cli.py`, `src/enqueue/config.py`

Steps:
1. `uv init` in the repo root. Set `requires-python = ">=3.11"`.
2. `uv add typer pydantic instructor chonkie fastembed qdrant-client beautifulsoup4 lxml pyyaml fastapi uvicorn httpx`
3. `uv add --dev black pytest`
4. `config.py` holds constants only, no logic:

```python
DATA_DIR      = Path.home() / ".enqueue-poc"
DB_PATH       = DATA_DIR / "enqueue.db"
BLOB_DIR      = DATA_DIR / "blobs"
EMBED_MODEL   = "BAAI/bge-base-en-v1.5"
EMBED_DIM     = 768
EMBED_VERSION = "bge-base-en-v1.5"
LLM_MODEL     = "qwen2.5:7b-instruct"
OLLAMA_URL    = "http://127.0.0.1:11434/v1"   # 127.0.0.1, never localhost. See Context.
QDRANT_URL    = "http://127.0.0.1:6333"
```
5. `cli.py` defines a typer app with one command, `enq version`, that prints the package version.

**Done when:** `uv run enq version` prints a version string.

### A2. Database

- [x] **Files:** `src/enqueue/schema.sql`, `src/enqueue/db.py`

Write `schema.sql` with exactly these tables. Use `TEXT` for all ids and timestamps. Timestamps are ISO 8601 strings in UTC.

```sql
CREATE TABLE IF NOT EXISTS artifacts (
  id            TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,          -- note | bookmark | pdf | image
  title         TEXT NOT NULL,
  source_url    TEXT,
  content_hash  TEXT NOT NULL UNIQUE,   -- dedupe key
  captured_at   TEXT NOT NULL,
  imported_from TEXT,                   -- 'fabric:books' etc
  provenance    TEXT NOT NULL,          -- authored | pasted | unknown
  local_only    INTEGER NOT NULL DEFAULT 0,
  status        TEXT NOT NULL           -- ok | text_only | failed
);

CREATE TABLE IF NOT EXISTS blocks (
  id           TEXT PRIMARY KEY,
  artifact_id  TEXT NOT NULL REFERENCES artifacts(id),
  parent_id    TEXT REFERENCES blocks(id),   -- NULL for top level. THIS IS THE NESTING.
  ordinal      INTEGER NOT NULL,
  depth        INTEGER NOT NULL,
  text         TEXT NOT NULL,
  created_at   TEXT
);

CREATE TABLE IF NOT EXISTS note_entries (
  id            TEXT PRIMARY KEY,
  artifact_id   TEXT NOT NULL REFERENCES artifacts(id),
  supersedes_id TEXT REFERENCES note_entries(id),   -- an edit appends, never updates
  text          TEXT NOT NULL,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
  id            TEXT PRIMARY KEY,
  artifact_id   TEXT NOT NULL REFERENCES artifacts(id),
  ordinal       INTEGER NOT NULL,
  text          TEXT NOT NULL,
  chunker       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facets (
  id            TEXT PRIMARY KEY,
  artifact_id   TEXT NOT NULL REFERENCES artifacts(id),
  level         INTEGER NOT NULL,       -- 0..4
  statement     TEXT NOT NULL,
  model_version TEXT NOT NULL,
  trust         REAL NOT NULL DEFAULT 0.5   -- see below
);

CREATE TABLE IF NOT EXISTS exhibits (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  theme         TEXT NOT NULL,          -- IMMUTABLE after insert
  through_line  TEXT,
  thin          INTEGER NOT NULL DEFAULT 0,
  thin_reason   TEXT,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exhibit_members (
  exhibit_id    TEXT NOT NULL REFERENCES exhibits(id),
  artifact_id   TEXT NOT NULL REFERENCES artifacts(id),
  placard       TEXT NOT NULL,
  evidence      TEXT NOT NULL,
  strength      INTEGER NOT NULL,
  rank          INTEGER NOT NULL,
  origin        TEXT NOT NULL,          -- generated | manual
  PRIMARY KEY (exhibit_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS facet_skips (
  artifact_id  TEXT PRIMARY KEY REFERENCES artifacts(id),
  reason       TEXT NOT NULL           -- too_short | kind | text_only
);

CREATE INDEX IF NOT EXISTS idx_blocks_artifact ON blocks(artifact_id);
CREATE INDEX IF NOT EXISTS idx_chunks_artifact ON chunks(artifact_id);
CREATE INDEX IF NOT EXISTS idx_facets_artifact ON facets(artifact_id);
```

`db.py` exposes `get_conn() -> sqlite3.Connection` which creates `DATA_DIR`, opens `DB_PATH`, sets `row_factory = sqlite3.Row`, enables `PRAGMA foreign_keys = ON`, and applies `schema.sql`.

Add `enq init` to the CLI, which calls `get_conn()` and prints the database path.

**Done when:** `uv run enq init` runs twice with no error, and `sqlite3 ~/.enqueue-poc/enqueue.db ".tables"` lists all six tables.

### A3. HTTP API, and the CLI becomes a client of it

- [x] **Files:** `src/enqueue/api.py`, rework `cli.py`

AGENTS.md says the engine sits behind a narrow localhost API and clients never know what is behind it. If the POC ships CLI-only, M1 inherits **two ways to drive the engine** and has to retrofit the boundary. Build it now.

1. `api.py` defines a FastAPI app bound to `127.0.0.1:8787` only. Never `0.0.0.0`.
2. `enq serve` runs it with uvicorn.
3. Every CLI command calls the API over HTTP. **No CLI command touches the database directly.**
4. Start with `GET /health` returning `{"status": "ok", "artifacts": <count>}`.

Add endpoints as later tasks need them. The rule is what matters: **business logic lives behind the API, and the CLI is a thin client.**

**Done when:** `uv run enq serve` starts, `curl -s http://127.0.0.1:8787/health` returns the JSON, `uv run enq health` prints the same, and `lsof -nP -iTCP:8787` shows it bound to `127.0.0.1` and not `*`.

### A4. Provider interface and Ollama adapter

- [x] **Files:** `src/enqueue/providers/base.py`, `src/enqueue/providers/ollama.py`

`base.py`:

```python
from typing import Protocol, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Provider(Protocol):
    name: str

    def complete(
        self,
        system: str,
        user: str,
        response_model: type[T],
        context: dict | None = None,
        max_retries: int = 3,
    ) -> T: ...
```

`ollama.py` implements it using `instructor` against Ollama's OpenAI-compatible endpoint at `config.OLLAMA_URL`, which is `http://127.0.0.1:11434/v1`. **Do not hardcode `localhost` here.** See the Context section for why.

**Pass `mode=instructor.Mode.JSON` explicitly.** Do not rely on the default.

Pass `context` through to `validation_context` so the validators in Phase E can read it.

**Done when:** a throwaway script asks for a two-field pydantic model and gets a valid instance back. Delete the script after verifying.

---

## Phase B - Import

### B1. Fabric HTML parser

- [x] **File:** `src/enqueue/ingest/fabric.py`

Parse one TipTap HTML file into a flat list of blocks that preserves the tree via `parent_id`.

```python
@dataclass
class ParsedBlock:
    uuid: str
    parent_uuid: str | None
    ordinal: int
    depth: int
    text: str
    created_at: str | None


def parse_fabric_html(html: str) -> list[ParsedBlock]: ...
```

Rules:
- Walk `<ul>` and `<li>` recursively with BeautifulSoup and the `lxml` parser.
- A block's text is the text of its own direct `<p>` child, not its descendants' text.
- `depth` is nesting level, top level is 0.
- Read `data-uuid` and `data-created-at` from the `<li>` when present, otherwise from the `<p>`. Generate a uuid4 if neither exists.
- Handle files with no list at all: a bare `<p>`, `<h2>`, or `<pre>` becomes a single depth-0 block.
- Preserve `<pre><code>` content verbatim, including newlines.
- Unescape HTML entities.

**Do not flatten the tree. Do not concatenate a parent with its children.**

**Done when:** parsing `books/Discourses_by_Epictetus.html` returns 19 blocks, 8 at depth 0 and 11 at depth 1, and the block containing "boxer derives their greatest advantage" is at depth 0 with three children. Every block has a `created_at`.

Those numbers are ground truth from the file: it contains 19 `<li>` elements, 8 top level and 11 nested, plus one empty `<p>` that must be skipped.

### B2. Secret scanning

- [x] **File:** `src/enqueue/ingest/secrets.py`

```python
@dataclass
class SecretHit:
    kind: str
    line: int
    excerpt: str  # the matched line with the secret value replaced by ***


def scan(text: str) -> list[SecretHit]: ...
```

Detect at minimum: assignments to `password`, `passwd`, `secret`, `token`, `api_key`, `apikey`; AWS access key ids (`AKIA` followed by 16 uppercase alphanumerics); private key headers (`-----BEGIN`); and `Bearer` followed by a long token.

**Never put the secret value itself in `excerpt`.**

**Done when:** `scan()` on the text of `snippets/sftp_command.html` returns at least one hit of kind `password`, and the excerpt does not contain the actual password.

### B3. Importer

- [x] **File:** `src/enqueue/ingest/importer.py`, plus `enq import-fabric PATH` in the CLI

For each `*.html` under each folder:
1. Read, parse with `parse_fabric_html`.
2. Compute `content_hash` as the sha256 of the concatenated block texts. **Skip the file if the hash already exists** in `artifacts`.
3. Title comes from the filename: underscores to spaces, `.html` stripped, whitespace collapsed.
4. `captured_at` is the earliest `data-created-at` across the file's blocks, falling back to file mtime.
5. `imported_from` is `fabric:<folder>`.
6. `provenance` is `unknown` for now. Task B5 fills it in.
7. `local_only` is 1 for anything under `biz_`, 0 otherwise.
8. Run `scan()` on the joined text. If it returns hits, set `status = 'text_only'` and print a loud warning naming the file and the hit kinds. **Import it anyway** and do not print the secret.
9. Insert the artifact, then all blocks with `parent_id` resolved from `parent_uuid`.

PDFs, PNG, GIF, and the one `.md` file: insert an artifact row with `status = 'text_only'` and no blocks. They are handled later.

**Done when:** `uv run enq import-fabric "<copy of the export>"` reports 76 notes imported, running it a second time reports 0 new, `SELECT COUNT(*) FROM blocks` returns more than 400, and the `sftp_command` warning appeared exactly once.

### B4. Bookmarks

- [x] **File:** extend `importer.py`, add `enq import-bookmarks PATH`

Parse `Bookmarks.html` (Netscape format) with BeautifulSoup. Each `<A HREF>` becomes an artifact with `kind = 'bookmark'`, title from the link text, `source_url` from the href, `captured_at` from `ADD_DATE` (a millisecond epoch), `content_hash` of the URL, `status = 'text_only'`, no blocks.

**Do not fetch the URLs.** Fetching is out of scope for the POC.

**Done when:** 39 bookmark artifacts exist and re-running adds none.

### B5. Provenance

- [x] **File:** extend `importer.py`, add `enq mark-provenance`

Classify each note artifact as `authored` or `pasted` using a heuristic, not a model:

Mark `pasted` if the joined text matches two or more of:
- contains an emoji in a heading
- contains "Let's break", "Let me know if", "Here's a", "That's an excellent", "In summary"
- contains three or more `<h2>`-level headings converted to blocks
- exceeds 800 words with fewer than 3 blocks at depth 1

Everything else is `authored`.

**Done when:** `hideas/PKMS.html` is `pasted`, `books/Discourses_by_Epictetus.html` is `authored`, and a printed summary shows counts per class for the human to sanity check.

---

## Phase C - Chunks

### C1. Chunking

- [x] **File:** `src/enqueue/ingest/chunk.py`, plus `enq chunk`

Rules, in order:
1. If an artifact has blocks, **each depth-0 block plus all of its descendants becomes one chunk**, joined with newlines. This preserves claim-plus-elaboration as a unit.
2. If a resulting chunk exceeds 800 tokens, split it further with chonkie's `RecursiveChunker` at 500 tokens with 80 overlap.
3. If an artifact has no blocks, skip it.

Record `chunker` as `blocks-v1` or `blocks-v1+recursive` accordingly.

**Done when:** `uv run enq chunk` produces chunks for all 76 notes, `Discourses_by_Epictetus` yields exactly 8 chunks, and no chunk is empty.

---

## Phase D - Index

### D1. Embeddings

- [x] **File:** `src/enqueue/index/embed.py`

Wrap `fastembed.TextEmbedding` with `BAAI/bge-base-en-v1.5`. Expose `embed(texts: list[str]) -> list[list[float]]`. Load the model once at module level, not per call.

**Done when:** embedding two strings returns two 768-length vectors, and the same string twice returns identical vectors.

### D2. Qdrant

- [x] **File:** `src/enqueue/index/qdrant.py`, plus `enq index`

Start Qdrant with:

```bash
docker run -d --name enqueue-qdrant -p 127.0.0.1:6333:6333 -v ~/.enqueue-poc/qdrant:/qdrant/storage qdrant/qdrant
```

Binding to `127.0.0.1` rather than all interfaces is deliberate. Qdrant has no authentication and this one holds the human's personal corpus.

Create two collections, `chunks` and `facets`, both with a 768-dimension dense vector using cosine distance.

**Payloads contain only `artifact_id`, `chunk_id` or `facet_id`, and `embed_version`. No text. This is hard rule 1.**

`enq index` embeds every chunk and upserts it into `chunks`.

**Done when:** the `chunks` collection point count equals `SELECT COUNT(*) FROM chunks`, and a scroll of any point shows a payload with no text field.

---

## Phase E - Facets

This is the moat. Read [CURATION.md](CURATION.md) fully before starting E2.

### E1. Proper noun extraction

- [x] **File:** `src/enqueue/ingest/facets.py`

```python
def proper_nouns(text: str, title: str) -> set[str]: ...
```

Return capitalised words that are not sentence-initial, plus every word in the title, lowercased for comparison. No spaCy, no model. A regex and a stopword list are enough.

**Done when:** for the Epictetus note the set contains `epictetus`, `diogenes`, and `socrates`.

### E2. Schemas

- [x] **File:** `src/enqueue/schemas.py`

Transcribe `AbstractionLevel`, `Facet`, `FacetSet`, `Verdict`, `Judgment`, `Grouping`, `Tension`, and `Exhibit` **exactly as written in [CURATION.md](CURATION.md)**, including every validator.

Do not soften a validator because a model fails it. A failing validator is the system working.

**Done when:** `pytest tests/test_schemas.py` passes, with tests that assert each validator **rejects** bad input: a 4-facet set, a set with zero level-3-or-above facets, a level-3 facet containing a banned proper noun, a hedged placard, evidence that is not a substring, and a through-line that restates the lens.

### E3. Facet eligibility gate

- [x] **File:** extend `facets.py`, plus `enq facet-gate`

**About a third of this corpus should never get facets.** A kubectl command has no honest level-3 abstraction. Forcing five to fifteen out of it produces noise that matches random lenses forever.

Write `facet_skips` for every artifact where any of these holds:

| Condition | `reason` |
|---|---|
| fewer than 40 words of text | `too_short` |
| folder is `snippets` or `biz_` | `kind` |
| `status` is `text_only` | `text_only` |

Skipped artifacts stay searchable and readable. They are simply never curatable.

**Done when:** roughly 30 to 40 of the 76 notes are skipped, `mental_models/getting_rich_vs_staying_rich` is skipped as `too_short`, `snippets/sftp_command` is skipped, and `books/Discourses_by_Epictetus` is **not** skipped. Print the counts per reason.

### E4. Facet generation

- [x] **File:** extend `facets.py`, plus `enq facets`

For each artifact **not in `facet_skips`**: build the input text, compute `proper_nouns`, call the provider with the facet-generation system prompt from CURATION.md and `response_model=FacetSet`, passing `context={"proper_nouns": ...}`.

Route to Ollama when the artifact is `local_only`, and to the chosen good model otherwise. Record which one was used.

Store each facet with `model_version = LLM_MODEL`.

Print a per-artifact line showing the facet count and the level histogram. Print a final summary of how many artifacts needed a retry and how many failed after `max_retries`.

**Done when:** every eligible artifact has between 5 and 15 facets, at least two at level 3 or above, and the retry rate is reported. **If more than a third of artifacts fail after retries, stop and report it** rather than weakening validators.

### E5. Index facets, with two post-checks

- [x] **File:** extend `qdrant.py`

Embed every facet statement, then drop before upserting:

1. **Near-duplicates.** Any facet within 0.95 cosine of another facet in the same artifact's set. One idea should not get several votes.
2. **Vacuous facets, by geometry.** Compare each level-2-or-above facet's embedding to its own artifact's chunk embeddings. Drop it if the maximum similarity is **above 0.90** (it never climbed, whatever level it claims) or **below 0.25** (untethered boilerplate that will match anything).

The band edges are guesses. Record how many were dropped at each end so the ablations can tune them.

Upsert the survivors into the `facets` collection. Payload is ids only, as always.

**Done when:** the `facets` point count equals the number of surviving facets, the drop counts are printed, and no more than about 20 percent were dropped. **A much higher drop rate means the generation prompt is producing summaries rather than abstractions.** Report it.

---

## Phase F - Search

### F1. Search

- [x] **File:** `src/enqueue/retrieve/search.py`, plus `enq search "QUERY"`

Embed the query, search the `chunks` collection for the top 30, fetch chunk text and artifact titles from SQLite by id, and print title plus a 120-character snippet.

**Done when:** `uv run enq search "what did Epictetus say about control"` returns the Epictetus note in the top three.

---

## Phase G - Curate

### G1. Lens expansion

- [x] **File:** `src/enqueue/retrieve/expand.py`

Given a lens string, ask the provider for 5 facet-style restatements of the lens and 3 hypothetical passages that would appear in a document exemplifying it. Return all 8 as strings.

Use a small pydantic model for the response. **This is a model call, so it goes through the Provider, not a raw HTTP request.**

**Done when:** expanding "antifragility" returns 8 strings, and at least one mentions repair or reversibility without using the word antifragile.

### G2. Candidates

- [x] **File:** `src/enqueue/retrieve/search.py`

```python
def candidates(lens: str, limit: int = 150) -> list[str]: ...  # artifact ids
```

Embed the lens plus all 8 expansions. Search both `chunks` and `facets`. Union the results, roll chunk and facet hits up to their `artifact_id`, dedupe, and return artifact ids ordered by best hit score.

**At 76 artifacts this will return nearly everything. That is expected and correct. Do not add filtering to make the number look better.**

**Done when:** `candidates("antifragility")` returns a list of artifact ids with no duplicates.

### G3. Rerank

- [x] **File:** `src/enqueue/retrieve/rerank.py`

For each candidate: call the provider with the rerank system prompt from CURATION.md, `response_model=Judgment`, and `context={"artifact_text": <the artifact's full text>}`.

Run with **bounded concurrency of 4**. Not sequentially.

A full eval run is 76 judgments per lens across 8 lenses. Sequential turns that into hours, and an eval nobody runs casually defeats the entire reason it was built before the retriever. Four workers is roughly twenty lines and turns it into tens of minutes.

Do not raise it above 4 without measuring. Ollama serialises internally, and a hosted endpoint has rate limits.

Keep judgments where `verdict == BELONGS`, sort by `strength` descending, and take the top 15.

**Done when:** running against "antifragility" produces judgments where every kept one has evidence that is a verbatim substring, and the count of `no` verdicts is greater than zero. **If nothing is rejected, the prompt or the model is broken.** Report it.

### G4. Synthesis

- [x] **File:** `src/enqueue/retrieve/synthesize.py`

Call the provider with the synthesis system prompt, `response_model=Exhibit`, and `context={"kept_artifact_ids": [...], "lens": lens}`. Pass the kept artifacts as title plus placard plus evidence, not full text.

**Done when:** it returns an `Exhibit` that passes its validators, including the report guard.

### G5. The curate command

- [x] **File:** `cli.py`

`enq curate "LENS"` runs expand, candidates, rerank, synthesize; persists the exhibit and its members; and prints the room: name, through-line, each artifact with its placard, then groupings and tensions.

**Done when:** `uv run enq curate "antifragility"` prints a readable room, and re-running `SELECT * FROM exhibit_members` shows the rows persisted.

---

## Phase H - Measure

### H1. Proposal pass

- [ ] **File:** `eval/propose.py`, plus `enq propose "LENS"`

For each artifact in the corpus, in a loop, ask the provider whether it is an instance of the lens and why, in one sentence. Write a draft `should_surface` list.

**This must read every artifact directly. It must not call `candidates()` or touch Qdrant.** Using retrieval here makes the golden set circular, which is hard rule 5.

**Done when:** `enq propose "antifragility"` emits YAML matching the golden-set format in [EVAL.md](EVAL.md), having read all 76 artifacts.

### H2. Golden set

- [ ] **File:** `eval/golden.yaml`

Run `enq propose` for these seven lenses and hand the drafts to the human for correction:

`antifragility`, `slow craft`, `stoic control`, `systems that improve under stress`, `what I keep saving without knowing why`, `memory and forgetting`, `combat sport as a model for thinking`.

The human must mark `hard: true` on artifacts sharing no vocabulary with the lens, add anything missed, and add at least one lens the proposal pass never saw.

**Done when:** the human has corrected all seven, every lens has at least two `hard: true` entries, and an eighth human-authored lens exists.

### H3. Harness

- [ ] **File:** `eval/harness.py`, plus `enq eval`

For each lens in `golden.yaml`: run the full curate pipeline, compare the top 15 against `should_surface`.

Report per lens and in aggregate:
- `hard-hit@15`: the share of `hard: true` artifacts that landed in the top 15. **This is the number.**
- `hit@15` overall
- false positives from `should_not_surface`
- lens-pair agreement between `antifragility` and `systems that improve under stress`

**Print a banner stating that recall is not reported because the corpus is under 500 artifacts**, so nobody later mistakes a missing number for a failure.

Write every run to `eval/runs/<timestamp>.json`.

**Done when:** `uv run enq eval` prints a per-lens table and writes a run file.

### H4. First measurement

- [ ] Run it. Report `hard-hit@15` per lens and overall.

Then, for every missed `hard: true` artifact, report which of **three** causes applies. They have nothing in common and their fixes point in opposite directions.

| Cause | How to tell |
|---|---|
| **Eligibility** | the artifact is in `facet_skips` and has no facets at all |
| **Facet** | it has facets, but none above level 2 that match the lens. Quote what they actually said |
| **Judgment** | a matching facet exists and rerank still returned `no`. Quote the facet and the verdict |

**Report this breakdown before changing anything.** An aggregate score without it is close to useless.

Also report which model produced the facets, per the privacy decision at the top. A score is meaningless without it.

---

## Ablations (only after H4)

Each answers a question that is currently a guess. Run one at a time, re-run `enq eval`, record the number.

- [ ] Facets disabled, chunks only. This is the baseline the whole architecture is justified against.
- [ ] The proper-noun ban removed from the level-2-and-above validator.
- [ ] The minimum-two-at-level-3 rule removed.
- [ ] Levels 0 and 1 dropped from the `facets` collection.
- [ ] Facet count capped at 5, then at 15.
- [ ] The vacuity band widened to 0.95 and 0.15, then narrowed to 0.85 and 0.35.
- [ ] The eligibility gate disabled, so short notes and snippets get facets after all.
- [ ] Local model versus the good model, same corpus, same golden set. This is the one that tells you whether a poor score was the design or the model.

---

## Risks (for the human, not the agent)

- **The local model may not be good enough.** A 7B is the largest that fits comfortably in 16GB alongside Docker, and it may produce facets that never climb past level 2, which would make the eval measure the model rather than the design. The tell is a low `hard-hit@15` combined with facet statements that read like summaries. The fix is a stronger model, which means either more RAM or content leaving the machine. That is your call, not the agent's.
- **Facet generation over 76 artifacts on an M1 will take a while.** Roughly 76 calls, each producing 5 to 15 sentences, sequentially, on a 7B. Expect tens of minutes, not seconds. Reranking during `enq eval` is 76 calls per lens across 8 lenses, so budget hours for a full evaluation run and do not run it casually.
- **76 artifacts is a small corpus.** A good score here does not prove the retrieval design works at 10,000, only that the judgment layer works. Retrieval genuinely gets tested at M1 volumes.
- **The corpus is your real notes.** M0 was specified against a throwaway corpus and this is not that. Local-only models are what makes that acceptable.
- **A password is in the corpus.** Rotate it. B2 keeps it out of prompts, but it will still sit in your SQLite.
