# Enqueue - Agent Instructions

Project-specific instructions for agents working on Enqueue.
Inherits global guidelines from ~/boxer/AGENTS.md.
This file covers engineering decisions and gotchas, not product behaviour.

| Document | Owns |
|---|---|
| [docs/PRODUCT.md](docs/PRODUCT.md) | vision, museum model, the three acts, scope and milestones, design system, privacy promise, decision log |
| [docs/CURATION.md](docs/CURATION.md) | the three model calls, their schemas and validators, and their prompts |
| [docs/EVAL.md](docs/EVAL.md) | the golden set, metrics, and ablations |

Consult PRODUCT.md for "what should this feature do" questions, and CURATION.md before touching anything that shapes a facet, a placard, or an exhibit.

**Status: design. Nothing is built yet.**

## General Guidelines

- Never use the em dash. Use plain dash instead.
- When writing commit messages, never auto-add your agent name as co-author.
- Never manually modify CHANGELOG.md files or any files marked as auto-generated.
- When writing or substantially editing long Markdown files, put each full sentence on its own line.
- When making technical decisions, prefer quality, simplicity, robustness, scalability, and long-term maintainability over development cost.
- When doing bug fixes, always start by reproducing the bug in an end-to-end setting as closely aligned with how an end user would hit it.
- Be picky about the UI. If something looks off, even if unrelated to the current task, get it fixed.
- Engineering excellence: lint, test failures, and test flakiness must be fixed even if not caused by the current work.
- Python formatting is black. Non-negotiable.

### Engineering principles

Development cost is explicitly deprioritised. Architectural decisions are evaluated against:

1. **Quality** - does this produce the best possible user experience?
2. **Simplicity** - is this the simplest solution that solves the problem correctly?
3. **Robustness** - does this handle failure gracefully? No silent data loss.
4. **Scalability** - can this grow 10x without rewrites?
5. **Long-term maintainability** - can an agent iterate on this cleanly?

---

## Architecture

### Shape

A local Python engine on macOS, with thin clients around it.

```
┌──────────────────────────────────────────────┐
│ macOS app (capture hotkey, museum UI)        │
│ Browser extension (primary capture surface)  │
└───────────────────┬──────────────────────────┘
                    │ localhost HTTP
┌───────────────────▼──────────────────────────┐
│ Engine (Python daemon)                       │
│  ingest pipeline · retrieval · curation      │
│  provider adapters · crypto · sync           │
└──────┬──────────────────────┬────────────────┘
       │                      │
┌──────▼────────┐   ┌─────────▼─────────────┐
│ SQLCipher     │   │ Qdrant (local sidecar)│
│ artifacts,    │   │ vectors + opaque ids  │
│ text, exhibits│   │ NEVER text            │
└───────────────┘   └───────────────────────┘
       │
┌──────▼──────────────────────────────────────┐
│ Sync target: Proton Drive / S3 / GCS        │
│ ciphertext objects only                     │
└─────────────────────────────────────────────┘
```

**The engine is local, not cloud.**
It runs on the user's Mac and listens on localhost.
"Local-first" here means the engine and both stores live on the machine, and sync moves ciphertext between machines rather than centralising anything.

### Why Python

Every library that does the hard parts is Python: marker for documents, chonkie for chunking, instructor for structured output, crawl4ai for fetching.

Rust was evaluated and rejected. The reasoning is worth keeping because it will come up again:

- **Speed is not the issue.** Over 95% of wall clock is model inference. Qdrant is already Rust, embedding runtimes are already native, pymupdf is already C. Porting the glue wins low single digits on minute-long operations.
- **Rust would mean owning a PDF parser.** There is no Rust marker. Document parsing is a swamp of scanned pages, two-column layouts, tables, ligatures, and broken producers. Owning that is a far worse ten-year maintenance liability than bundling an interpreter.
- **It would not escape Python anyway.** A Rust engine would still shell out to marker, so both runtimes get bundled, which destroys Rust's best argument (single static binary).

Rust's real advantages were packaging longevity, Android-as-peer, and crypto ergonomics. None outweighed the parser problem.

### Draw the seam anyway

Rust may become correct later, if Android has to become a full peer rather than a satellite.
Design so that port is possible without a rewrite:

- The engine sits behind a narrow localhost API. Clients never know what language is behind it.
- Provider adapters stay narrow (see [Provider layer](#provider-layer)).
- Storage and crypto sit behind their own interface. No Python types leak into the on-disk format.

If the port ever happens, orchestration, storage, and crypto move to Rust and a Python sidecar keeps exactly one job: document parsing.

### App shell

**Tauri, with the Python engine as a sidecar.**

Same reasoning that put Dequeue's desktop on Tauri: a native window, menu bar, global shortcuts, and tray in a small binary, with a web view layer where keyboard handling is simpler and more reliable than native macOS menu plumbing.
Tauri's sidecar mechanism is also the supported way to ship a bundled interpreter alongside the app.

The engine never leaks into the shell. The shell speaks to localhost and does not know what language is behind it, which is what keeps the Rust port open.

### Platform split

| Platform | Role |
|---|---|
| macOS | the engine. Ingest, index, curate, read. |
| Browser extension | primary capture surface |
| Android | capture-and-read satellite. Captures artifacts, syncs ciphertext, reads an index the Mac built. Does not ingest or curate. |

Two independent constraints landed on this split: Python does not cross-compile to Android, and local Whisper transcription of a two-hour lecture is not something a phone should attempt.
When two unrelated constraints agree, take the hint.

---

## Data model

SQLCipher for everything textual and relational. Qdrant for vectors only.

### Tables

| Table | Purpose | Notes |
|---|---|---|
| `artifacts` | the primary model | immutable after ingest. `content_hash` is unique and is how dedupe works |
| `artifact_blobs` | original bytes | encrypted at rest, referenced by path |
| `artifact_text` | extracted text | per artifact, with extractor name and version |
| `capture_context` | silent capture-time context | source app, page title, selection, nearby captures |
| `notes` | user-authored notes on artifacts | **user-authored, never regenerated** |
| `chunks` | literal layer | text, ordinal, token count, chunker name and version |
| `facets` | conceptual layer | statement, abstraction level, generator model and version |
| `exhibits` | saved formations | `theme` is immutable after creation |
| `exhibit_members` | artifact in exhibit | placard, rank, `origin` (generated/manual), `ejected_at` |
| `exhibit_notes` | pinned wall text | **user-authored, never regenerated** |
| `asks` | question and answer log | ephemeral by default, promotable to an exhibit |
| `ingest_jobs` | durable work queue | resumable, backpressured, survives restarts |
| `model_versions` | registry | embedding models, facet generators, chunkers, with dimensions |

### Invariants

Break these and the product's promises stop being true.

1. **Qdrant payloads never contain text.** Vectors plus opaque `artifact_id` and `chunk_id`/`facet_id`. No titles, no URLs, no excerpts. Qdrant stores payloads unencrypted on disk, and the privacy promise says nothing readable sits on disk. Text is fetched from SQLCipher by id after retrieval. This is cheap to do now and impossible to retrofit once an index exists.
2. **Artifacts are immutable after ingest.** Every derived row carries the model or tool version that produced it, so anything derived can be regenerated. Nothing derived is ever the only copy of anything.
3. **User-authored rows are never overwritten by regeneration.** `notes`, `exhibit_notes`, manual `exhibit_members`, and `ejected_at` survive every refresh and every re-index. This is product principle 7 as a schema rule.
4. **Every vector is stamped with its embedding model version.** Query and corpus must share a vector space, so a model change means re-embedding. Stamping makes that an incremental background job instead of a migration crisis.
5. **`exhibits.theme` is immutable.** Reshaping means a new exhibit. See the decision log in PRODUCT.md.

### Qdrant collections

| Collection | Vectors | Payload |
|---|---|---|
| `chunks` | dense + sparse (BM25-style) | `{artifact_id, chunk_id, embed_version}` |
| `facets` | dense | `{artifact_id, facet_id, embed_version}` |

Qdrant runs as a **local sidecar process**, not in local mode.
In-process mode (`QdrantClient(path=...)`) is documented for roughly 20,000 points.
One thousand artifacts produce around forty vectors each once chunks and facets are counted, so day one is already past that, in a store designed to grow forever.

---

## Retrieval architecture

The moat. If this is mediocre, Enqueue is a worse Fabric.

### The problem

Plain RAG fails the core case, structurally rather than by tuning.
"Antifragility" embeds near Taleb, black swans, and convexity.
A hand-built furniture article embeds near joinery, grain, and hand tools.
Cosine similarity between them is near zero, so the furniture article never enters top-k.

RAG closes the lexical-to-semantic gap. This is the semantic-to-conceptual gap, and it needs different machinery.
The qa-system literature calls the same failure "multi-hop": documents that are not semantically similar but jointly hold the answer.

### The design: meet in the middle

Two moves from opposite ends.

**Ingest raises artifacts toward concepts.** Per artifact, once, re-runnable:

1. Extract text (see [Ingest](#ingest-pipeline)).
2. Chunk with chonkie. Embed chunks locally. This is the **literal layer**, and it powers Search.
3. Generate a **facet set**: 5 to 15 statements of what this artifact could be an example of, climbing in abstraction. Not tags. Full sentences, because sentences embed richly and carry their own reasoning.
4. Embed each facet locally. This is the **conceptual layer**.

For a hand-built furniture article, facets look like:

> joinery designed to be disassembled and remade
> craft where damage is expected and reversibility is the design goal
> systems that accumulate skill through repeated failure
> resistance to obsolescence through repairability rather than durability

**Query lowers concepts toward artifacts.** Per curate:

1. Expand the lens into facets plus hypothetical exemplar passages. Hypothetical passages work because they live in document space rather than question space.
2. Multi-vector search against both collections. Roll chunks up to artifacts. Target around 150 candidates.
3. Rerank: the model reads candidates against the lens and keeps 10 to 20. **The placard is generated here, not in a separate call** - the model has already articulated why each artifact qualifies.
4. Synthesise over survivors: through-line, tensions, groupings. That is the exhibit.

"Antifragility" now hits facets 2 and 3 of the furniture article directly. The connection was precomputed before the question existed.

This degrades gracefully. Bad facets and query expansion still reaches. An unanticipated lens and the facets still cover neighbouring ground. Both layers have to fail together.

### Two granularities

Do not conflate them.

| Layer | Unit | Powers |
|---|---|---|
| Literal | chunk | Search, citation to passage |
| Conceptual | artifact | Curate |

Chunking advice from the RAG literature applies only to the literal layer.
Facets are artifact-level and have no chunking problem.

### Hybrid search

Sparse and dense together, fused with RRF, using Qdrant's native support for both in one index.

Sparse matters more than it first appears. "Find that thing from Epictetus" is a proper noun, and embeddings blur proper nouns while BM25 nails them. Same for book titles, error codes, rare jargon.

- **Search**: hybrid, weighted toward sparse.
- **Curate**: dense plus facets, sparse as a minor channel.

### Scope dial for Ask

Ask takes a scope, and cost tracks scope for free:

| Scope | Retrieval |
|---|---|
| One artifact | none. The artifact fits in context, load it whole |
| One exhibit | light. Fifteen artifacts mostly fit |
| Everything | full pipeline |

### Thin results are reported, not padded

If the candidate pool is weak, the curator says so and offers what is adjacent.
Never pad an exhibit to look full. See PRODUCT.md principle 8.

---

## Ingest pipeline

Always asynchronous. Capture never blocks, never spins, never asks a question.

`ingest_jobs` is a durable, resumable, backpressured queue.
Bulk import of an existing pile is measured in hours or days, not in a progress bar, and it must survive restarts, rate limits, and crashes without redoing finished work.

### Per type

| Type | Path |
|---|---|
| Web page | browser extension supplies rendered DOM. crawl4ai only as an announced fallback |
| PDF | tiered, see below |
| Video link | audio extract, then local Whisper transcript. Keyframes and slide OCR deferred |
| Image | caption **and** OCR, always. Different jobs: OCR is everything for a screenshot, caption is everything for a photograph |
| Note, highlight | as captured |

### PDF tiering

Do not run marker on everything.

1. pymupdf first. Born-digital PDFs extract in milliseconds, near-perfectly.
2. Detect failure: low text density means a scan, broken reading order means columns.
3. Marker only then.

Marker's published throughput is measured on a B200 GPU. On Apple Silicon it runs through llama.cpp at a fraction of that, so a VLM pass on a document pymupdf could have parsed instantly is pure waste.

### Dedupe

Content hash on the extracted bytes. Same URL captured twice does not create a second artifact.
Near-duplicates (different versions of the same document) need fuzzy matching, deferred.

### Untrusted content

Captured pages become model input, and a malicious page can inject instructions.
The blast radius here is worse than usual: a poisoned **facet** is written to the index permanently, not just a bad answer in one session.

Treat all extracted content as untrusted data inside every prompt that touches it. Never as instructions.

---

## Provider layer

One narrow interface, adapters behind it. Never scatter model calls through the codebase.

```python
class Provider(Protocol):
    def complete(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
    ) -> str | BaseModel: ...
```

### Adapters and instructor modes

Instructor defaults to `TOOLS` mode, which requires function calling. **Do not take the default.** Pin the mode per adapter.

| Adapter | Mode | Why |
|---|---|---|
| **Lumo (default)** | `MD_JSON` | The official Lumo API has not shipped, and lumo-tamer states custom tool support is experimental. `MD_JSON` puts the schema in the system message and parses JSON from a markdown block, requiring nothing from the endpoint |
| Ollama | `JSON_SCHEMA` | native structured output |
| OpenRouter | `TOOLS` | per underlying model |

### Which stage runs where

| Stage | Backend | Reason |
|---|---|---|
| Embeddings | **always local** | Lumo has no embeddings endpoint. Strictly more private, not a compromise |
| Transcription | **always local** (whisper.cpp) | Lumo has no ASR |
| Facet generation | local by default | high volume: every artifact, several calls. Burning an unknown rate limit on bulk ingest is the wrong trade |
| Rerank | Lumo | low volume, high value |
| Synthesis | Lumo | this is where exhibit quality is decided |
| Ask | Lumo | |

Local-only artifacts never route to a network adapter, whatever the default is set to.
With no local model configured they keep plain text search and lose facets and placards. They are never silently sent to the network instead.

### lumo-tamer is not a shipping dependency

Useful for prototyping before the official API exists.
It scrapes credentials, is Linux-tested only, and its own author states use may violate Proton's terms of service.
Build against the `Provider` interface, prototype through lumo-tamer, ship against the official API or Ollama.

---

## Storage and crypto

### Key handling

- Password to master key via Argon2id.
- Master key wraps a data encryption key (envelope encryption), so the password can change without re-encrypting the corpus.
- Artifacts and blobs encrypted with the DEK, AES-256-GCM.
- SQLCipher for the relational store.
- Qdrant's data directory lives inside the encrypted volume.

**There is no recovery path.** Lose the password, lose the museum. Any recovery path is a copy of the key held by somebody else, which would void the promise. This is stated in PRODUCT.md as a non-promise and must not be quietly "fixed" later.

### Residual risk to keep visible

Raw embeddings are partially invertible. Inversion attacks can reconstruct approximate source text from vectors.
Far weaker than plaintext, not nothing.
Keeping the Qdrant data directory encrypted at rest is the mitigation, and it is why invariant 1 (no text in payloads) is not the whole answer on its own.

### Sync

Ciphertext objects to the configured backend: Proton Drive, S3, GCS, or none.
The backend sees object count, sizes, and timing. It never sees content.
Mac is the engine. Android reads a synced index.

---

## Migrations and versioning

The store is meant to last decades, and most of the usual migration pain does not apply because of a property already in the design.

**Derived data is never migrated. It is dropped and regenerated.**

That splits the problem cleanly:

| Class | Tables | Policy |
|---|---|---|
| Sacred | `artifacts`, `artifact_blobs`, `capture_context`, `notes`, `exhibits`, `exhibit_members`, `exhibit_notes` | Real migrations. **Additive only.** Never a destructive change, never a drop that loses user-authored content. |
| Disposable | `artifact_text`, `chunks`, `facets`, both Qdrant collections | No migrations at all. On a version bump, truncate and rebuild from originals in the background. |

Consequences to respect:

- Every derived row already carries the tool or model version that produced it, so a rebuild is incremental rather than total.
- A rebuild runs as ordinary `ingest_jobs` work: resumable, backpressured, interruptible.
- **A migration must never block capture.** Capture writes only to the sacred tables, which is exactly why those are additive-only.
- The store records its schema version. Downgrade is not supported, and the app says so rather than corrupting a store.

## Testing

No network in tests. Provider adapters replay recorded responses.

| Layer | What |
|---|---|
| Unit | chunkers, extractors, crypto, dedupe hashing, provider adapters |
| **Contract** | every schema in [docs/CURATION.md](docs/CURATION.md) gets fixtures of good *and deliberately malformed* model output, asserting the validators reject what they should |
| Integration | full ingest of a fixture corpus: one born-digital PDF, one scan, one article, one image, one video, asserting each lands and becomes searchable |
| Eval | [docs/EVAL.md](docs/EVAL.md), run on demand rather than in CI, since it is slow and costs model calls |

**The contract layer matters more than the happy path.**
The validators in CURATION.md are the product's quality floor, not defensive plumbing.
A suite that only feeds them well-formed output proves nothing about the thing they exist to catch.

## Evaluation

Full spec in [docs/EVAL.md](docs/EVAL.md). Build it before the retriever.

### The number that matters

**Recall at the candidate stage** (target: recall@150), measured against a hand-marked golden set.

A recall failure is fatal *and invisible*. If the furniture article never entered the candidate pool, the exhibit still reads beautifully, built from the wrong ten artifacts, and nothing in the output reveals it. Precision failures are visible and fixable. Recall failures quietly make the museum smaller than the mind it is supposed to hold.

### Golden set

10 to 15 lenses. For each, the artifacts that should surface, hand-marked, deliberately including the hard analogies (furniture under antifragility, the same artifact under brutalism).

### Do not use RAGAS faithfulness

Borrow **context recall** from RAGAS. Discard **faithfulness**.

Faithfulness scores whether the answer is supported by retrieved documents. For question answering that is correct. For an exhibit it is actively wrong: the value is the through-line *between* artifacts, which appears in none of them. Faithfulness would penalise exactly the output the product exists to produce.

Faithfulness is still the right metric for **Ask**, which is genuinely question answering. Two acts, two metrics.

### Benchmarks to run

- `RecursiveChunker` versus `LateChunker`. Late chunking is a recall play and recall is our metric, but it improves the *literal* layer only. It will not close the abstraction gap, so expect it to move Search and barely move Curate. Let the golden set decide.
- Facet count and abstraction depth. More facets means better recall and more ingest cost.
- Candidate pool size before rerank.

---

## Library decisions

| Library | Role | Licence | Notes |
|---|---|---|---|
| **instructor** | structured LLM output | MIT | Pydantic validation with automatic re-prompt on validation failure. This is the quality floor on facet generation: enforce count, sentence form, and abstraction level in the validator and let it retry |
| **chonkie** | chunking | MIT | `RecursiveChunker` to start (500-800 tokens, 50-100 overlap). `LateChunker` to benchmark. Skip `SlumberChunker`, expensive and solving a different problem |
| **marker** | document parsing | Apache 2.0 code | **Model licence tripwire:** Surya models are modified AI2 OpenRAIL-M, free under $5M funding or revenue, commercial use above that needs a Datalab licence. Irrelevant for personal use, a real gate if Enqueue ever ships |
| **crawl4ai** | web fetch fallback | Apache 2.0 | Demoted, see below |
| **qdrant** | vector store | Apache 2.0 | Local sidecar, not local mode. Native sparse plus dense in one index with RRF fusion, which is why it beats sqlite-vec and LanceDB here |
| **whisper.cpp** | transcription | MIT | Metal-accelerated on Apple Silicon |

### crawl4ai is the fallback, not the default

The browser extension captures the page the user already loaded. Zero extra network requests, and no publisher or ISP learns a reading list.

crawl4ai is a headless Chromium fetching from the user's IP, which is exactly the leak the extension avoids. It exists for cases the extension cannot cover: bulk-importing old bookmarks, a link received but never opened, Android capture.

Rules:

- Never the default path.
- The app states that it is about to fetch from the network.
- Its stealth mode, undetected-browser mode, and 3-tier proxy escalation stay **off**. Fetching your own reading list is fine; building bot-detection evasion into a personal archiver is not a road to start down.
- Proxy support may be used to hide the originating IP if the user configures it.

---

## Key technical decisions

Made for specific reasons. Do not undo without understanding why.

### Qdrant holds no text

Invariant 1 above. Payloads are unencrypted on disk, and putting chunk text there would write plaintext excerpts of the entire hoard to an unencrypted store, voiding privacy promise 1. Text lives in SQLCipher and is fetched by id after retrieval.

### The engine is Python, and the seam is drawn for Rust

See [Why Python](#why-python). The deciding factor was that Rust would mean owning a PDF parser. Revisit only if Android has to become a full peer.

### Instructor modes are pinned per adapter

Never rely on the `TOOLS` default. Lumo's tool-calling support is unknown and lumo-tamer's is experimental. `MD_JSON` requires nothing from the endpoint and is the correct floor.

### Facet generation runs locally by default

It is the high-volume path, and Lumo's rate limits are unknown. Quality is spent where it is decided: rerank and synthesis.

### Marker is tiered behind pymupdf

Running a VLM on a born-digital PDF is minutes of compute replacing milliseconds.

### Corrections are scoped to the exhibit

Ejecting an artifact from an exhibit teaches the curator about *that exhibit*, not about global taste. Only a repeated pattern across unrelated exhibits earns a global write, and it happens as a background write rather than in the hot path.

The failure being avoided is memory rot: a one-off correction becoming a permanent rule, after which the museum degrades steadily with no traceable cause. React fast locally, learn slowly globally.

---

## Open items

- Packaging: bundling CPython plus PyTorch plus Playwright into a signed, notarised Mac app via Tauri's sidecar mechanism. A bundled interpreter is a maintenance surface that breaks on OS updates.
- Whether the transparent capture window is worth `macOSPrivateApi` and the App Review exposure Dequeue already carries.
- Whether Qdrant ships as a bundled sidecar binary or is required as a separate install.
- Android index format. What exactly a satellite reads, and how much of it syncs.
- Fabric export format, for cold-start import of existing hand-written book annotations.
- Everything under Open in [docs/CURATION.md](docs/CURATION.md) and [docs/EVAL.md](docs/EVAL.md), all of which the golden set answers rather than argument.
