# Enqueue - Agent Instructions

Project-specific instructions for agents working on Enqueue.
Inherits global guidelines from ~/boxer/AGENTS.md.
**If you are here to write code, your work queue is [docs/PROGRESS.md](docs/PROGRESS.md).** Do one task per turn, in order, and verify each with the command in its "Done when" before checking the box. This file is reference: read the section a task points you at, not the whole thing.

This file covers engineering decisions and gotchas, not product behaviour.

| Document | Owns |
|---|---|
| [docs/PRODUCT.md](docs/PRODUCT.md) | vision, museum model, the three acts, scope and milestones, design system, privacy promise, decision log |
| [docs/CURATION.md](docs/CURATION.md) | the three model calls, their schemas and validators, and their prompts |
| [docs/EVAL.md](docs/EVAL.md) | the golden set, metrics, and ablations |

Consult PRODUCT.md for "what should this feature do" questions, and CURATION.md before touching anything that shapes a facet, a placard, or an exhibit.

**Status: rebuilding.** The retrieval half is built and works. The ingest half is being replaced, because the first version had no concept of authorship. See [docs/PROGRESS.md](docs/PROGRESS.md).

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
| macOS | **full peer.** Ingests, indexes, curates, reads. Any number of them. |
| Browser extension | primary capture surface |
| Android | capture-and-read satellite. Captures artifacts, syncs, reads an index a Mac built. Does not ingest or curate. |

Peers do not talk to each other. They all read and append to a shared encrypted log, so there is no primary, no pairing, and no device that has to be awake for another to work. See [Sync](#sync).

Two independent constraints landed on this split: Python does not cross-compile to Android, and local Whisper transcription of a two-hour lecture is not something a phone should attempt.
When two unrelated constraints agree, take the hint.

---

## Processes and API surface

### Processes on one machine

| Process | What it is | Bound to |
|---|---|---|
| `enqueue-shell` | Tauri. Native window, global hotkey, tray. M1 onward | nothing |
| `enqueue-engine` | Python. FastAPI plus a background worker, one process | `127.0.0.1:8787` |
| `qdrant` | vector store, Docker | `127.0.0.1:6333` |
| `ollama` | local models | `127.0.0.1:11434` |

**Everything binds to loopback.** Nothing listens on a network interface, ever, on any milestone.

The engine serves HTTP and drains the ingest queue in the same process.
No broker, no Redis, no second container. This is the same call Dequeue made with in-process APScheduler, and for the same reason: a single-user local tool does not need a job infrastructure.

### Endpoints

```
POST   /capture                       202 {artifact_id}, returns before processing
POST   /capture/upload                multipart

GET    /artifacts?since=&limit=       newest first, the home feed
GET    /artifacts/{id}                detail, body, annotations, exhibits it hangs in
GET    /artifacts/{id}/content        readable rendering
GET    /artifacts/{id}/blob           original bytes
PATCH  /artifacts/{id}/body           edit a note. Captures reject this
GET    /artifacts/{id}/versions       every saved body
POST   /artifacts/{id}/annotations    commentary on a capture
PATCH  /artifacts/{id}                local_only, pinned. Flags only

POST   /artifacts/{id}/preview        fetch what a saved link is. Opt-in, one request

GET    /search?q=                     artifacts. No model calls, fully local

GET    /chats                         conversations, newest first, each with its topics
POST   /chats                         {scope_kind, scope_id?, text?} start one
GET    /chats/{id}                    transcript, citations, topics
POST   /chats/{id}/messages           {text} one turn
PATCH  /chats/{id}                    rename
DELETE /chats/{id}                    the one deletable object in the product
GET    /chats/ready                   whether there is anything to answer from
GET    /chats/passages?q=             exactly what an answer would be allowed to read

POST   /curate                        {lens}, SSE
GET    /exhibits
GET    /exhibits/{id}
POST   /exhibits                      save a curated room
POST   /exhibits/{id}/refresh         SSE
PATCH  /exhibits/{id}/members/{aid}   edit placard, eject
POST   /exhibits/{id}/notes           pinned wall text

GET    /health
GET    /jobs                          queue depth, failures
GET    /settings
PATCH  /settings
```

`/curate` and `/refresh` are **Server-Sent Events**, not request-response.
The budget is 90 seconds and PRODUCT.md requires the room to fill artifact by artifact rather than showing a spinner, so judgments stream as they return.

`PATCH /artifacts/{id}` accepts flags only. Artifact content is immutable after ingest, which is data model invariant 2.

## Data model

SQLCipher for everything textual and relational. Qdrant for vectors only.

### Tables

| Table | Purpose | Notes |
|---|---|---|
| `artifacts` | the primary model | immutable after ingest. `content_hash` is unique and is how dedupe works |
| `artifact_blobs` | original bytes | encrypted at rest, referenced by path |
| `artifact_text` | extracted text | per artifact, with extractor name and version |
| `capture_context` | silent capture-time context | source app, page title, selection, nearby captures |
| `artifact_versions` | every saved state of a note's body | append-only. The artifact holds current state; this holds history |
| `annotations` | your commentary on a **captured** artifact | append-only, superseding by id. A note's own body is never stored here |
| `chunks` | literal layer | text, ordinal, token count, chunker name and version |
| `facets` | conceptual layer | statement, abstraction level, generator model and version, **`trust` REAL default 0.5** |
| `exhibits` | saved formations | `theme` is immutable after creation |
| `exhibit_members` | artifact in exhibit | placard, rank, `origin` (generated/manual), `ejected_at` |
| `exhibit_notes` | pinned wall text | **user-authored, never regenerated** |
| `chats` | conversations with the collection | replaced `asks`. A chat is scoped to everything, one artifact, or one room |
| `chat_messages` | one turn | append-only. `grounded` records whether the answer came from the collection |
| `chat_citations` | what an answer was built from | message to artifact, ranked |
| `chat_topics` | the concepts a conversation circles | derived, regenerable, and the handle a room is hung from |
| `link_previews` | what a saved link turns out to be | derived. Text only, never a remote asset URL |
| `ingest_jobs` | durable work queue | resumable, backpressured, survives restarts |
| `model_versions` | registry | embedding models, facet generators, chunkers, with dimensions |

### Invariants

Break these and the product's promises stop being true.

1. **Qdrant payloads never contain text.** Vectors plus opaque `artifact_id` and `chunk_id`/`facet_id`. No titles, no URLs, no excerpts. Qdrant stores payloads unencrypted on disk, and the privacy promise says nothing readable sits on disk. Text is fetched from SQLCipher by id after retrieval. This is cheap to do now and impossible to retrofit once an index exists.
2. **A capture's body is immutable after ingest. A note's body is not.** A capture is frozen because fidelity to the source is why it was saved. A note is a document the user owns, and `artifacts.body` is updated in place when they edit it.
3. **No user-authored text is ever destroyed.** Editing a note appends the new body to `artifact_versions` before updating the artifact. Annotations on captures supersede by id and are never deleted. Regeneration never touches `annotations`, `exhibit_notes`, manual `exhibit_members`, or `ejected_at`. This is product principle 7 as a schema rule.
4. **Every vector is stamped with its embedding model version.** Query and corpus must share a vector space, so a model change means re-embedding. Stamping makes that an incremental background job instead of a migration crisis.
5. **`exhibits.theme` is immutable.** Reshaping means a new exhibit.
6. **Derived rows carry the model or tool version that produced them**, so anything derived can be regenerated and nothing derived is ever the only copy of anything.
7. **Schema changes are Alembic revisions.** Never a `CREATE TABLE` in application code, never an edit by hand. A database that predates migrations is stamped at the baseline and upgraded, never rebuilt: rebuilding it would destroy everything the person ever saved, which is the one failure this product cannot come back from.
8. **An answer states whether it is grounded, and the citations must back it.** A grounded answer names artifacts it was actually shown; an ungrounded one names none. Enforced in `schemas.Answer` and again when citations are written. The failure being prevented is the fluent, correct, well-cited answer that came from the model's own knowledge and has nothing to do with the collection, which is invisible from the outside and makes the collection pointless.

### Why a note is mutable and its history is not

An earlier version of this file made every note an append-only list of entries, with no mutable body anywhere.

The reasoning was sound and the conclusion was wrong. Last-write-wins on a text field genuinely is silent data loss: write on one machine, extend on another before the pull lands, and one version disappears with no conflict marker. Enqueue has no server and therefore no authoritative clock, only a hybrid logical clock, which orders events but does not make discarding one of them safe.

What that argument justifies is **keeping every version**. It does not justify refusing to let the user rewrite their own paragraph, which is what shipped: a note whose text could only be appended to.

The resolution keeps the guarantee and drops the restriction:

- `artifacts.body` is the current text and is updated in place.
- `artifact_versions` gets an append before every update.
- Sync ships the version rows, so two peers editing the same note produce two version rows and neither is lost. Reconciling which body is current is last-write-wins on a field whose entire history is recoverable, which is a different proposition from last-write-wins on a field that has none.

Annotations on captures stay append-only, because they comment on something immutable and there is no "current state" to resolve.

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

## How the museum improves with volume

Without these, Enqueue gets **bigger** with more artifacts, not smarter. The machinery would be identical at 76 and at 50,000, and volume would actively hurt precision by adding near-misses.

Five mechanisms make the claim true. None require the user to do anything extra, and all of them emerge from ordinary use.

### 1. Facet trust, from your own corrections

Adapted from Hermes Agent's holographic memory provider, which scores facts 0.0 to 1.0 with asymmetric feedback.

`facets.trust` starts at 0.5. Every `Judgment` already records `matched_facet_id`, so:

| Event | Delta |
|---|---|
| The artifact it matched enters a saved exhibit | **+0.05** |
| The artifact it matched is ejected | **-0.10** |

Retrieval scales facet similarity by trust. Below a floor a facet is excluded from matching but **never deleted**.

**Negative evidence is weighted double on purpose.** A save is ambient, since a room gets saved for many reasons. An ejection is targeted: this artifact, this room, no. Far more information per event.

This is also the read-time half of quality control. The validators in [docs/CURATION.md](docs/CURATION.md) prevent junk at write time; trust demotes whatever got through, based on use.

It does not violate the memory-rot rule under [Corrections are scoped to the exhibit](#corrections-are-scoped-to-the-exhibit). One ejection moves trust by 0.10 and killing a facet takes five, so a repeated pattern is still what produces a global effect. The rule is expressed as a gradient rather than a threshold.

**Cheapest mechanism here by a wide margin.** One column, two update rules, and it starts working the first time the user ejects something.

### 2. Facet vocabulary convergence

At a few hundred artifacts every facet is bespoke. At several thousand, level 3 and 4 statements recur.

Cluster the level-3-and-above facet embeddings. Clusters above a size threshold are the user's conceptual vocabulary, discovered rather than authored.

- New artifacts get scored against known concepts instead of generating free-form, which is cheaper and far more consistent
- Lens expansion snaps to concepts the user actually holds rather than doing blind HyDE
- The vocabulary is browsable, and it is the honest answer to "what am I actually interested in"

Needs roughly 500 artifacts before it means anything.

### 3. Exhibit co-occurrence

Every saved exhibit is a human-validated cluster, produced for free by ordinary use.

Build an artifact-to-artifact affinity graph from co-membership across saved rooms, and at retrieval boost candidates that repeatedly co-hang with already-strong candidates.

That is a backlink structure nobody maintained, learned from the user's own judgment. Needs roughly 25 saved exhibits.

### 4. Contradiction detection across the facet corpus

Hermes runs a `contradict` operation continuously over stored facts. Enqueue has `tensions`, but only per query at synthesis time.

Running contradiction detection across the whole facet corpus finds the user's own disagreements without being asked. "Reversibility is strength" sitting against "commitment is strength" is a real tension in a person's thinking, and it is invisible until there is enough material for it to repeat.

### 5. The concept instantiated but never named

Falls out of mechanism 2 for free, and it is the best of the five.

The answer to "what I keep saving without knowing why" is **the largest facet clusters that have no saved exhibit**. A theme the user keeps producing instances of and has never once named.

This does not violate "silent until asked". The user asked.

### Sequencing

| Mechanism | Needs | Milestone |
|---|---|---|
| Facet trust | one column, two rules | **M1** |
| Exhibit co-occurrence | ~25 saved exhibits | M2 |
| Facet vocabulary | ~500 artifacts | M2 |
| Contradiction detection | the vocabulary | M2 |
| Unnamed themes | the vocabulary | M2 |

### What not to build

**No GraphRAG-style entity extraction, and no knowledge graph.** Hindsight builds one and it works for them, but entity extraction is brittle and a graph pre-commits to a structure, which is wrong for a product whose premise is that structure is a query. All five mechanisms above are cheaper and better aligned.

**No Holographic Reduced Representations.** Hermes uses them for compositional algebraic queries over entities. Enqueue's problem is analogy, not composition.

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
| **Facet generation** | **the good model** | see below |
| Rerank | the good model | low volume, high value |
| Synthesis | the good model | this is where exhibit quality is decided |
| Ask | the good model | |

**Facet generation used to run locally, and that was wrong.**

The old reasoning was throughput: it is the high-volume path, and Lumo's rate limits are unknown. That optimises cost at the expense of the one stage that cannot be cheap.

The facet layer is the moat, and bad facets are not merely a weak result. **They are permanent pollution.** A placard is transient, read once and gone. A facet is embedded, indexed, and votes on every future retrieval. Junk there degrades the museum quietly and forever.

So the rule is now one line instead of a per-stage matrix:

> **The good model by default. Local only when the artifact says so.**

The cost is real and accepted: bulk import of ten thousand artifacts is ten thousand calls against unknown rate limits, and it may take days. It is a resumable queue, it happens once per artifact, and steady state is a handful of calls a day.

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

---

## Sync

Every Mac is a full peer. Each one captures, ingests, curates, and reads.

### The log is the source of truth

SQLite is not the data. It is a materialised view.

The truth is an **encrypted, append-only log of immutable objects** in the configured store: Proton Drive, S3, GCS, or none.
Each peer appends its own events and replays everybody's to rebuild its local SQLite and Qdrant.

This is the "derived data is disposable" principle applied one level up, and it collapses three separate problems into one operation.
Adding a second machine, restoring from backup, and recovering a corrupted index all become the same thing: point a peer at the log and let it rebuild.

**Do not reach for a database server here.** A server that cannot read the data cannot index it either, so a managed Postgres or Turso would be an expensive blob store with extra failure modes. The privacy promise makes a dumb object store the correct choice rather than a compromise.

### What syncs, and what each peer rebuilds

| Syncs | Rebuilt locally |
|---|---|
| artifacts and blobs, content-addressed | chunks |
| `artifact_versions`, every note body ever saved | |
| extracted text | **all embeddings** |
| capture context | the Qdrant index |
| your notes | |
| **facets, as text** | |
| saved exhibits: membership, placards, your edits | |

Embeddings are the bulk, roughly forty vectors per artifact, so ten thousand artifacts is well over a gigabyte. None of it crosses the wire.

**Facets sync even though they are derived.** This is a deliberate exception to the rule above. If each peer generates its own, two local models quietly disagree and retrieval stops being comparable between machines. They are cheap as text, about 10MB at ten thousand artifacts, and their embeddings still stay local.

**Saved exhibits publish their membership rather than re-deriving it per peer.** Otherwise the work laptop shows nine artifacts and the home machine shows eleven, which is indefensible even under "eighty percent is a good day." Unsaved exhibits are ephemeral and never sync.

### It is an event log, not a data lake

The distinction changes what gets built, so it is worth stating plainly.

A data lake is queried in place with schema-on-read. This log is **never queried, only replayed**. Events are typed, ordered by a hybrid logical clock, and idempotent, and every device's SQLite is a read model rebuilt from them.

**The working analogy is git.**
Each clone is a full replica built from an immutable object log. The remote is dumb storage that understands nothing about the contents. `git gc` is exactly the compaction problem in the open items.

There is no sync server. The service is a bucket.

### Object layout

```
enqueue/
  log/{device_id}/{hlc}-{ulid}.evt    one encrypted event
  blobs/{sha256}                       encrypted original bytes, content addressed
  snapshots/{hlc}.snap                 periodic compaction, see open items
```

**Per-device prefixes are what make a dumb object store viable as a multi-writer log.**
Each device only ever writes under its own `device_id`, so there is no write contention, no locking, and no compare-and-swap. Two peers appending at the same moment cannot collide because they are not writing to the same place.

Blobs are content addressed by sha256, so the same artifact captured on two machines uploads once.

### Event types

| Event | Payload |
|---|---|
| `artifact.created` | id, kind, title, source_url, content_hash, captured_at, provenance |
| `block.added` | artifact_id, parent_id, ordinal, depth, text |
| `note.revised` | artifact_id, version_id, body |
| `annotation.appended` | artifact_id, entry_id, supersedes_id, text |
| `facet.generated` | artifact_id, level, statement, model_version |
| `exhibit.saved` | id, name, theme, through_line, members with placards |
| `member.placard_edited` | exhibit_id, artifact_id, text |
| `member.ejected` | exhibit_id, artifact_id |
| `artifact.flagged` | artifact_id, local_only, pinned |

Every event carries `{event_id, hlc, device_id, type, payload}` and is encrypted with the DEK before upload.

**Local-only artifacts emit no events at all.** They never enter the log, which is what makes the flag mean what PRODUCT.md says it means.

### The two loops

- **Push** appends new events under this device's own prefix.
- **Pull** lists objects newer than this device's watermark, fetches, decrypts, and applies them in HLC order. Application is idempotent by `event_id`, so a partial pull is safe to redo.

Transport is plain S3, GCS, or WebDAV for Proton Drive.
There is no custom protocol and no server-side code to operate or secure.

### Conflicts

- **Artifacts cannot conflict.** Content-addressed and immutable. The same URL captured on two machines is one artifact with two capture events.
- **Note bodies resolve by last-write-wins over a complete history.** Two peers editing the same note produce two rows in `artifact_versions`, both of which sync. Only which body is *current* is resolved by the clock, and the losing text is one click away rather than gone. See [Why a note is mutable and its history is not](#why-a-note-is-mutable-and-its-history-is-not).
- **Annotations cannot conflict.** They are append-only and supersede by id, so two peers annotating at once produce two entries and both survive.
- **Placards and flags** resolve by field-level last-write-wins. A placard is machine-generated with a rare manual override, and a flag is a scalar where discarding the loser is what the user meant.
- **Ejections are tombstones**, resolved by the same rule, so an ejection made on either peer sticks.

**There is no server, therefore no authoritative clock.**
Dequeue resolves last-write-wins with server timestamps. Here two peers can drift, and a laptop can simply have the wrong time.
Use a **hybrid logical clock with a device-id tiebreak**, never wall time. It is a small amount of code and a genuinely nasty class of bug if skipped.

Duplicate ingest work is possible when two peers process the same artifact. It is idempotent, so it is waste rather than corruption, and it is not worth a locking scheme.

### What the backend sees

Object count, object sizes, and timing. Never content.

### Export is the second copy

The sync log is not a backup. It is one copy in one place, behind a password with **no recovery path by design**.

Lose the password or lose the bucket and a lifetime hoard is gone. Two single points of failure in a store whose first principle is that captures are sacred.

`enq export` writes the museum as **plain markdown plus original files** in an ordinary directory tree: one file per artifact, notes inline, exhibits as their own files listing members and placards. No database, no encryption, nothing Enqueue-specific required to read it.

It serves two purposes at once, which is why it is one feature and not two:

- **The escape hatch.** The hoard is readable without this application, forever, which is the minimum honest commitment for something meant to hold decades of a person's thinking.
- **The second copy.** Somewhere the password cannot lock you out of.

M1. It is not optional, and it is not a nice-to-have to defer under pressure.

### Local-only means local

The per-artifact `local-only` flag keeps an artifact away from network models. It also keeps it out of the log.

An artifact marked local-only exists on the machine that captured it and nowhere else.
This is the escape hatch for a hoard that spans a personal machine and a work-managed one, where encryption at rest is not the relevant defence: an MDM-managed endpoint has an agent, disk access, remote wipe, and possibly TLS interception on the network sync traffic crosses.
Full peering is the default because it is what makes the museum whole. The flag is there for the material that should never have been on that machine in the first place.

---

## Migrations and versioning

The store is meant to last decades, and most of the usual migration pain does not apply because of a property already in the design.

**Derived data is never migrated. It is dropped and regenerated.**

That splits the problem cleanly:

| Class | Tables | Policy |
|---|---|---|
| Sacred | `artifacts`, `artifact_versions`, `artifact_blobs`, `capture_context`, `annotations`, `exhibits`, `exhibit_members`, `exhibit_notes` | Real migrations. **Additive only.** Never a destructive change, never a drop that loses user-authored content. |
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

### The sync log is the source of truth, and SQLite is a view

An earlier design made the local SQLite store the data, with sync as an afterthought.

Two Macs as full peers forces the inversion, and the inversion is better on its own merits.
Adding a machine, restoring a backup, and rebuilding a corrupted index become one operation instead of three.
It also extends the "derived data is disposable" rule to cover the entire local database rather than only the index.

A database server was considered and rejected. The privacy promise says the sync target only ever sees ciphertext, and a server that cannot read the data cannot index it, so Postgres or Turso would be a costly blob store with more failure modes than an object store.

### The in-process worker is about blast radius, not about avoiding a broker

This was previously justified as "no Redis, no broker, no second container", which is development cost wearing a disguise.

The real reason is robustness. A broker introduces a failure mode where **capture breaks because infrastructure is down**, and capture is the one thing in this product that must never fail. A SQLite table has no such mode: if the process is running at all, the enqueue succeeded.

Stated as cost, the next person under different pressure reverses it. Stated as blast radius, it holds.

### Python was chosen to avoid owning a PDF parser

The record previously leaned partly on library availability, which is cost-adjacent reasoning.

The deciding value is narrower and stronger: **a Rust engine would mean maintaining a document parser.** Scanned pages, two-column layouts, tables, ligatures, and broken producers are a swamp, and marker exists because a team grinds on it full time. Owning that for a decade is a far worse maintenance liability than bundling an interpreter.

Speed was never the argument. Over 95 percent of wall clock is model inference, and Qdrant, the embedding runtime, and pymupdf are already native.

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
- **Log compaction.** An append-only log grows forever. It needs periodic snapshotting so a new peer does not replay a decade of events, and the snapshot must not become a second source of truth.
- **Log object granularity.** One object per event is simple and produces a great many small objects; batching is cheaper and complicates partial failure.
- **New-peer bootstrap time.** A fresh machine must replay the log and re-embed the entire corpus locally. At ten thousand artifacts that is hours, not minutes. It needs to be resumable and to make the museum usable before it finishes rather than after.
- Everything under Open in [docs/CURATION.md](docs/CURATION.md) and [docs/EVAL.md](docs/EVAL.md), all of which the golden set answers rather than argument.
