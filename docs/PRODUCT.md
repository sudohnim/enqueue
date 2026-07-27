# Enqueue - Product & Design

The single source of truth for what Enqueue is, what it does, and how it looks.

| Document | Owns |
|---|---|
| **This file** | vision, museum model, the three acts, scope and milestones, design system, privacy promise, decision log |
| [AGENTS.md](../AGENTS.md) | architecture, data model, retrieval, provider layer, crypto, sync, migrations, testing |
| [CURATION.md](CURATION.md) | the three model calls, their schemas and validators, and their prompts |
| [EVAL.md](EVAL.md) | the golden set, metrics, and ablations |

**Status: design settled, nothing built.**
Milestone 0 is buildable from these documents. See [Scope](#scope).
What remains open is listed under [Open questions](#open-questions).

---

## Vision

Enqueue is a digital hoarder's dream.

Capture anything, forever, without deciding what it is.
You bring the idea; Enqueue brings the material and the connections between it.

The premise is that "this is interesting, I don't know why" is a legitimate terminal state.
Every other tool punishes that state by demanding a folder, a tag, or a link before it will accept the thing.
Enqueue accepts it unconditionally and works out what it meant later, on demand, differently every time you ask.

### The inverse of Dequeue

Enqueue is the deliberate sibling of [Dequeue](../../dequeue/docs/PRODUCT.md), and the symmetry is load-bearing.

| | Dequeue | Enqueue |
|---|---|---|
| Premise | the pile must not grow | the pile *should* grow |
| Mechanic | decay, hard caps, forced action | accumulation, zero friction, no forced action |
| Axis | time, and only time | arbitrary concepts, chosen later |
| Failure it prevents | hoarding | losing the thing you could not name yet |

Dequeue makes you act.
Enqueue lets you not act.

Anything that makes Enqueue feel like a task manager or a file tree is off-concept, the same way projects, labels, and priorities are off-concept for Dequeue.

### Product principles

1. **Hoarding is a virtue.** No decay, no caps, no guilt, no inbox zero. Dequeue punishes the pile; Enqueue *is* the pile.
2. **Capture costs nothing.** Hotkey, paste, gone. It never asks a question at capture time.
3. **Structure is generated, not maintained.** The enemy is manual toil, not structure. Backlinks, membership, and themes are all welcome - as long as the machine produces them and you only adjust. What is banned is being asked to file, tag, or link something by hand before the tool will accept it.
4. **Eighty percent is a good day.** The curator proposes, the director disposes. An auto-generated exhibit that is mostly right and one nudge from correct beats a perfect one you had to build. Design every generated thing to be cheaply adjustable rather than exactly right.
5. **Silent until asked.** No badges, no unread counts, no digests, no nudges. The pile never nags. This is what makes guilt-free hoarding possible.
6. **Captures are sacred, your writing is yours, derivations are disposable.** Three categories, not two. A capture is immutable forever, because fidelity to the source is the whole point of having saved it. Your own writing is a document you own and can rewrite at will, with every version kept. Everything abstracted, embedded, or curated is rebuildable, so the museum gets smarter when the models do.
7. **Your hand beats the machine's.** Anything you wrote, edited, pinned, or ejected survives every regeneration. The curator never overwrites the director.
8. **Show your work.** Every connection traces back to the passage that produced it. A leap you cannot check is a leap you cannot use.
9. **Privacy is the premise, not a feature.** Proton's Lumo is the default AI backend and the reason the promise holds. See [Privacy](#privacy).
10. **Every outside boundary is pluggable, and every plug is labelled.** AI backend and storage backend are both swappable, because a lifetime tool must outlive any single vendor. Swappable does not mean silent: each backend states what leaves the device, at the moment you choose it.

### It should get smarter as it gets bigger

Hoarding is only a virtue if the pile repays it.

More artifacts must mean better connections, not merely more of them, and that does not happen for free. Volume by itself hurts: more material means more near-misses to sift.

Four things make accumulation pay, and none of them ask anything of you beyond ordinary use.

- **The curator learns from your corrections.** Every ejection is a targeted judgment about what does not belong, and the abstraction that produced it quietly demotes itself. Nothing you have to teach.
- **Your vocabulary emerges.** After enough material the same underlying ideas recur across unrelated artifacts. Those recurring abstractions are your conceptual vocabulary, discovered rather than authored.
- **Rooms teach the museum.** Artifacts that repeatedly hang together in exhibits you saved become related, which is a set of backlinks nobody maintained.
- **Themes you never named surface.** The honest answer to "what do I keep saving without knowing why" is the largest cluster of recurring ideas that has no exhibit. A thing you keep producing instances of and have never once named.

That last one is only possible at volume, and it is the clearest argument for hoarding.

Mechanisms, thresholds, and sequencing are in [AGENTS.md](../AGENTS.md).

### Anti-goal

Not "Obsidian with AI search."

Obsidian's value *is* the graph you maintain: backlinks you author, tags you curate, notes you write.
Enqueue's value is that you maintain nothing.
The moment it asks you to organize, tag, link, or process, it has become the thing it replaces.

---

## What success looks like

One sentence, and it is deliberately not a number:

> I have thoughts I would not otherwise have had, and I stopped losing things.

Enqueue's own principles forbid every normal product metric.
No counts, no streaks, no engagement surface, nothing that nags.
So the measures have to be passive, and there are exactly three.

| Measure | Signal | Why it is honest |
|---|---|---|
| **Sustained capture** | artifacts per week, unprompted, over months | Volume is the precondition for everything. If capture is not effortless you will not hoard, and an exhibit over two hundred artifacts is a sad little room. |
| **Save rate on exhibits** | share of built exhibits that get saved | Saving is already a one-click act in the product, so it needs no instrumentation and no prompt. You save a room when it showed you something. That is the quality signal, free. |
| **Recall on the golden set** | recall at the candidate stage | The only measure that catches the invisible failure. See [EVAL.md](EVAL.md). |

The failure this guards against is specific: a system like this produces *plausible* output when it fails.
An exhibit built from the wrong ten artifacts reads beautifully.
Without a stated definition of good, there is no way to tell that apart from the real thing.

---

## Scope

The documents describe the finished museum. This is the order it gets built in.

### Milestone 0 - prove the moat

No interface. A CLI over the engine.

Capture, ingest, index, curate, and the evaluation harness with a hand-marked golden set.
Success is a number: recall at the candidate stage on lenses that require analogy, not topical similarity.

This comes first because the retrieval design is the single thing that, if mediocre, makes Enqueue a worse Fabric.
Everything downstream assumes it works. Nothing else should be built until it does.

**M0 has no encryption, and its corpus is genuinely disposable.**

The store lives at `~/.enqueue-poc`, holds junk loaded for development plus a constructed evaluation set, and is **deleted rather than migrated** when M1 begins. Nothing in it exists only there.

Encryption at rest arrives with M1, which is the first moment the store holds material worth keeping.

### Milestone 1 - the museum

The macOS app. Encryption at rest, because this is where real material starts accumulating.

Hotkey capture, home, exhibit view, artifact detail, reading view, search.
Curate with save, refresh, edit, and eject.
**Export**, because a store with no recovery path needs a second copy that plain files can hold.

### Milestone 2 - the hoard grows

Browser extension, which is the capture surface that actually generates volume.
Bulk import for cold start.
Ask, all three scopes.

### Milestone 3 - portability

Sync backends, and the Android capture-and-read satellite.

### Deferred, explicitly

Video keyframes and slide OCR. Near-duplicate detection. Agentic multi-hop retrieval. Late chunking, pending the benchmark. Anything on the [non-goals](#non-goals) list, permanently.

### Performance budgets

Targets, not aspirations. A miss is a bug.

| Action | Budget |
|---|---|
| Hotkey pressed to capture window visible | 100ms |
| Capture submitted to window dismissed | 50ms, always, because ingest is asynchronous |
| Search keystroke to results | 200ms |
| Ask, one artifact | 5s |
| Ask, everything | 20s |
| Curate an exhibit | 90s, with the room filling progressively rather than a spinner |
| Refresh an exhibit | 30s |
| Ingest one artifact | no budget. It is a queue. It must survive restarts, rate limits, and crashes without redoing finished work. |

Capture is the only one of these that is non-negotiable.
If capture ever feels slow, the product stops working, because hoarding stops.

---

## The museum model

The organizing metaphor, and the vocabulary the whole product uses.

| Museum | Enqueue | Rule |
|---|---|---|
| **Artifact** | anything you saved or wrote | permanent, never filed, never deleted. A capture is immutable; a note is yours to rewrite |
| **Vault** | everything you have, newest first | most artifacts sit in storage most of the time, and that is normal, not a backlog |
| **Exhibit** | a saved formation on a theme | summoned by naming a theme, never filled by dragging |
| **Placard** | the "why this is here" note on an artifact | written per-artifact, *per-exhibit* |
| **Curator** | Lumo | hangs the show, never chooses the theme |
| **Director** | you | name the theme, edit the wall text, eject what does not belong |

### Artifact

The primary data model.

An artifact is one thing you saved or wrote: a link, an article, a PDF, a video, an image, a screenshot, a highlighted passage, a note.

- **Permanent.** Nothing expires, nothing is capped, nothing is auto-deleted.
- **Never filed.** An artifact does not live anywhere. It has no parent, no folder, no home.
- **The original bytes are kept**, not just extracted text. See [Originals are kept](#originals-are-kept-forever) for why.
- **Shows which exhibits it is currently hanging in.** A backlink you never maintained: derived, not authored, and the moment you see the shape of your own mind.

### Two kinds of artifact

They differ in exactly one respect, and it is the one that matters.

| | A capture | A note |
|---|---|---|
| Where it came from | the world | you |
| Its body | **immutable** | **yours, editable, every version kept** |
| Your commentary | an annotation attached to it | there is nothing to attach it to; the note *is* the commentary |

A captured page is frozen because fidelity to the source is the reason you saved it. Editing it would destroy the only thing it was for.

A note has no source to be faithful to. It is a document you own, and a tool that will not let you rewrite your own paragraph is not a second brain, it is a filing cabinet.

**This was got wrong once.** The first build treated every artifact as an immutable capture with an editable comment underneath, which made a note you wrote read-only and appendable-to. See [Notes are documents, captures are not](#notes-are-documents-captures-are-not) in the decision log.

### Vault

Everything, newest first.

The vault is the museum's storage, not an inbox.
It has no unread state, no processed/unprocessed distinction, and no count of things awaiting your attention.
Browsing it is a valid activity; ignoring it forever is equally valid.

### Exhibit

A formation on a theme, built by asking.

You supply the concept ("antifragility", "brutalist architecture", "why do I keep saving this"), and the curator pulls from the vault and hangs the show.
It surfaces the through-line, hangs each artifact with its own placard, and names the tensions between them.

**An exhibit is a thinking surface, not a report.**
A report tells you what you already own.
An exhibit tells you something you did not know you thought.

- **Naming:** you name the exhibit. The curator may suggest a name; you edit it.
- **Membership is generated, never filed.** An artifact appears in as many exhibits as want it, and in none by default. Membership is real and stored - it just is not something you do by hand. There is no "add to" as the primary act, and never a "move", because an artifact has no home to move out of.
- **Theme is immutable.** Changing what an exhibit is *about* means making a new exhibit. Reshaping is not an operation; it is a second room.
- **Everything else is editable.** Contents, placards, your own notes, ordering, ejections.
- **Cheap and disposable.** Every question builds a temporary exhibit. Saving it is one click. Nothing is ever saved automatically.
- **Refresh, not rebuild.** Refresh absorbs artifacts captured since last time and re-derives the synthesis. It is incremental: already-indexed artifacts are not reprocessed.
- **Your edits survive refresh.** Notes you wrote, placards you rewrote, artifacts you ejected. Ejection is permanent for that exhibit unless you undo it.

### Placard

The reason an artifact is in *this* room.

The placard is the whole product.
The same artifact carries different wall text in different exhibits.

An article on hand-built furniture, hung in *Antifragility*:

> Joinery designed to be undone. The object expects to be broken.

The same article, hung in *Brutalism*:

> Honest joints, nothing concealed. The structure is the finish.

Tags cannot do this, because a tag is one label everywhere.
Folders cannot do this, because a folder is one home.
A placard is contextual by nature, and contextual meaning is the entire premise of Enqueue.

### The division of labor

**You** make the conceptual leap.
**Enqueue** finds which of your hoard belongs to that leap, including the pieces that do not obviously belong, and shows how they hang together.

It never guesses what matters to you.
It waits, then performs.

---

## Core loops

### Capture

A global hotkey opens a capture window over whatever is frontmost.
Paste, drop, or type. Enter and it is gone.
It never asks a question, never blocks, and never shows a spinner you have to wait on. Processing is always asynchronous.

Context that costs zero friction is captured silently alongside the artifact: source URL, page title, selected text, application, timestamp, and what else was captured nearby in time.
That context is fuel for retrieval, and is mostly not shown back to you. Visible metadata rebuilds the file-tree feeling the product exists to escape.

**Capture volume is the precondition for everything else.**
An exhibit built over two hundred artifacts is a sad little room.
Capture surfaces are therefore not a v1 nicety; they are what makes the rest of the product work at all.

Surfaces, in priority order:

1. macOS global hotkey.
2. Browser extension. Captures the already-rendered page, which also means no second network request from you to the publisher, and no paywall problem for pages you legitimately have access to.
3. Bulk import from existing tools, for cold start.
4. Android share sheet.

### Three acts: search, ask, curate

One continuum, not three features. The same retrieval spine, at three depths, returning three different shapes.

| Act | The question | Returns | Cost | Persists |
|---|---|---|---|---|
| **Search** | "find that thing from Epictetus" | artifacts | instant | no |
| **Ask** | "what have I saved about Stoic control?" | an answer with citations, in a conversation | seconds | yes, as a chat |
| **Curate** | "antifragility" | an exhibit | around a minute | when you save it |

They are never merged into one bar.
The distinction is what the answer is *shaped* like, and collapsing it would leave the product with one vague box that does all three badly.

#### Search

You are looking for a specific artifact you know exists, and you should get it.

Not a keyword box.
Search digs, and on the way it surfaces adjacent artifacts you were not looking for.
Finding the Epictetus passage is the job; showing you what sits near it is why search belongs in a museum rather than a filing cabinet.

#### Ask

A question about your own material, answered with citations back to the passage.

**Ask takes a scope**, and the scope is a dial rather than three separate features:

- **One artifact.** Chat with this PDF, this article, this transcript.
- **One exhibit.** Follow-up questions about a room you already built.
- **Everything.** Question answering over the whole hoard.

**Ask is a conversation, and it is kept.**
This was one shot and ephemeral, and the shape was wrong for the reason the whole product exists: the conceptualisation is usually not known in advance. A single shot asks you to name the thing you are trying to find. A conversation lets you circle it.

What makes the conversation worth keeping is not the transcript.
As you talk, the concepts you are circling are extracted and stored against the chat, and **a topic is the same kind of object a lens is.** So a topic drawn out of a conversation is clickable, and clicking it hangs a room. The chat is where you find out what you are actually asking; the room is what that turns into.

**Ask is still the utility; curate is still the product.**
Chat-with-your-notes is what Fabric and mem.ai already are.
If the home screen becomes a chat box, Enqueue is a worse version of both.
Conversations sit above the artifacts on the home screen, not in place of them, and asking is still one of three glyphs on one small control.

#### Curate

You name a lens. The curator builds a room.
You read it, pull a thread, ask again inside it.
When a room earns it, you save it.

### Read

Enqueue is a museum you go into, not an index that points elsewhere.

Artifacts are readable in place: articles, PDFs, transcripts, images.
Re-reading is a first-class act, not a fallback.

### Ingest

What has to become readable and thinkable, per type:

| Type | Handling |
|---|---|
| Article, web page | full text, kept |
| PDF | text plus original file |
| Video link | transcript always; keyframes and slide OCR only for slide-shaped video, later |
| Image | caption *and* OCR, always. They are different jobs: OCR is everything for a screenshot, a caption is everything for a photograph |
| Highlight, screenshot, note | as captured |

Machine-generated descriptions stay visibly derived.
A caption is a guess, it gets indexed, and it will later be cited back to you. It must never be promoted to fact.

**Duplicates are merged.** Capturing the same URL twice does not create a second artifact.

---

## Non-goals

- Not a todo list.
- Not a note editor.
- No folders, tags, or hierarchies.
- **No spaces.** Fabric-style spaces are folders in a nicer coat: you file into them, and an item lives in one. If Enqueue ships anything you drag items into, the premise is gone. A standing exhibit called *books* catches book-shaped artifacts on refresh; it is not a container you put books in.
- No read-later queue with unread counts.
- No sharing, publishing, collaboration, or social.
- No auto-summarizing everything for you. That is the report product.
- No processing ritual, daily review, or inbox zero.
- No proactive surfacing, digests, or "you have been circling this idea" nudges. Enqueue is silent until spoken to.

---

## Where this sits against Fabric

Fabric is the closest prior art, and already does capture-anything, auto-tagging, semantic search, and "related items" associations.
Three real gaps:

1. **Similarity versus lens.** Fabric associates things that are alike. Hand-built furniture is not *like* antifragility; it rhymes with it under a lens you supplied. Fabric cannot make that connection because it has no lens - it associates without being asked. This is the moat.
2. **Storage versus formations.** Fabric organizes so you can retrieve. Enqueue builds formations to think with, which persist and grow.
3. **Cloud versus Lumo.** Fabric is cloud and collaborative. Enqueue is single-player and private by construction.

Gaps 2 and 3 are strong but copyable. Gap 1 is the product.

---

## Design

### The scene

A dim gallery after hours, and the same gallery at ten in the morning.
Stone walls, ink, and one lamp on whatever is currently on view.
The room is deliberately quiet because the objects are not.

**Colour strategy: restrained.**
Two colours exist in the entire interface, and neither of them is the point.
Everything saturated on screen comes from the artifacts.

### Sibling to Dequeue, not a recolour

Dequeue and Enqueue share bone structure, not hue.
Same spacing rhythm, same icon weight, same restraint discipline, one shared sans.
The palettes are unrelated on purpose, because chasing hue similarity produces a recolour, which is the weaker relationship.

The separator is temperature and direction.

| | Dequeue | Enqueue |
|---|---|---|
| Cast | warm, yellow | cool, blue-grey |
| Ground | linen `#F5F2EA` | stone `#E5E8EB` |
| Identity | olive *is* the brand | the absence of app colour is the brand |
| Direction | deep signal on a light canvas | lit object in a quiet room |

Enqueue must never use olive, moss, or verdigris.
That is Dequeue's territory, and verdigris in particular is the obvious Bronze Age move that has to be refused for exactly that reason.

### The eight rules

These decide a hundred later arguments, and matter more than the hex values.

1. **Stone is the room.** Nothing in the interface is a surface of any other colour.
2. **The exhibit's lighting is constant; the room's is not.** Mount, gold, and vellum are identical in both modes. Everything else inverts. This is the tie that makes light and dark feel like one product at two hours, and it is borrowed from Solarized, which holds all eight accents fixed and inverts only the monotones.
3. **No warm mid-tones.** Warm is either near-black or bright gold. The middle is brown, and brown is the failure state. This is Enqueue's equivalent of Dequeue's mud.
4. **Gold is light, not paint.** Rules, edges, small marks, one fill. Spread gold across an area and it becomes brown.
5. **Gold only appears against near-black.** On the mount, or as a dark-mode fill. It never has to survive against pale stone, which is what keeps it gold instead of mustard. The light-mode primary action is therefore an ink fill.
6. **One mount at a time.** Only the artifact on view. Two makes it a swatch book.
7. **The curator is the only one who gets a different face.** You share sans with the interface, because you are the director and the interface is your instrument.
8. **All saturated colour comes from the artifacts.**

The failure mode has a name so it is catchable: **the gift shop**.
Accent creeps onto fills, chips, and decoration, the walls start competing with the objects, and the gallery becomes a shop.

### Tokens

Authored in OKLCH. Hex is the fallback, not the source.

**Constant across both modes.** These three are the tie.

| Token | OKLCH | Hex | Use |
|---|---|---|---|
| `mount` | `0.230 0.010 110` | `#1D1D18` | the surface the on-view artifact is mounted on |
| `gold` | `0.740 0.090 88` | `#C3A866` | rules framing the mount, dark-mode primary fill |
| `vellum` | `0.925 0.010 88` | `#E9E6DF` | text on the mount, and only there |
| `vellum-sub` | `0.755 0.012 88` | `#B3AFA7` | secondary text on the mount |

**Light.**

| Token | OKLCH | Hex | Contrast on base |
|---|---|---|---|
| `base` | `0.930 0.005 235` | `#E5E8EB` | canvas |
| `surface-1` | `0.958 0.004 235` | `#EFF2F3` | headers, toolbars, panels |
| `surface-2` | `0.988 0.002 235` | `#FAFBFC` | raised, reading surface |
| `ink` | `0.230 0.014 245` | `#181E23` | body, and the primary fill | 13.74 |
| `subtext` | `0.470 0.011 242` | `#565C61` | 5.55 |
| `muted` | `0.505 0.010 242` | `#60656A` | 4.77 |
| `border` | `0.868 0.006 235` | `#D0D4D7` | hairlines |
| `border-strong` | `0.795 0.008 235` | `#B7BDC1` | secondary button, emphasis |

**Dark.**

| Token | OKLCH | Hex | Contrast on base |
|---|---|---|---|
| `base` | `0.175 0.010 245` | `#0D1115` | canvas |
| `surface-1` | `0.222 0.010 245` | `#171C1F` | headers, toolbars, panels |
| `surface-2` | `0.272 0.010 245` | `#23282C` | raised, reading surface |
| `ink` | `0.928 0.006 242` | `#E4E8EB` | body | 15.34 |
| `subtext` | `0.728 0.009 242` | `#A2A8AC` | 7.88 |
| `muted` | `0.682 0.009 242` | `#949A9E` | 6.64 |
| `border` | `0.312 0.010 245` | `#2D3136` | hairlines |
| `border-strong` | `0.402 0.010 245` | `#44494D` | secondary button, emphasis |

**Verified contrast.**
Vellum on mount 13.52, vellum-sub on mount 7.72, gold rule on mount 7.30, gold fill with base text 8.20.
Every text token clears WCAG AA in both modes, including muted, which is also the placeholder colour and therefore held to the same 4.5 as body text.

**The one deliberate low-contrast value.**
The mount sits at 13.74 against the light canvas and 1.12 against the dark canvas.
That asymmetry is the effect, not a defect: in the light room the mount advances as a near-black plinth on limestone, and in the dark room it recedes into shadow so only the gold rules and the artifact itself remain visible.
The gold rules carry the definition in both cases.
If in practice the dark-room mount reads as unrendered rather than as an object floating in the dark, lift it and accept losing the perfect constant. Do not fix it by adding a border in another colour.

### The four voices

The Axial Age's native format is text plus commentary: the Talmud, the Confucian commentaries, Vedic bhashya, Greek scholia.
Original words in one hand and later interpretation in another, sharing a page.
That is the oldest information design there is, and it is exactly what Enqueue needs.

| Voice | Face | Where |
|---|---|---|
| The artifact's own words | mono | captured text, source lines, snippets, metadata |
| The curator interpreting | serif | placards, exhibit titles, through-line prose |
| You speaking | sans | your notes, pinned wall text |
| The building | sans | navigation, buttons, labels, chrome |

You and the interface share a face on purpose.
The curator is the only voice that is not you, so it is the only one that gets set apart.
This works in greyscale, which is why it survived removing the second accent colour.

Sans is **Inter**, shared with Dequeue, which is the one piece of visible family resemblance.

Serif is **Source Serif 4**. Transitional, screen-designed, and legible at 13px, which is where most placards live and where an old-style face like EB Garamond gets fragile. It pairs with Inter on a genuine contrast axis rather than being a near-miss against it.

Mono is a matter of taste and is not yet decided, but it must be a true text mono rather than a coding face with programming ligatures. It is quoting Epictetus, not rendering a diff.

### Type scale

Fixed rem steps, not fluid. Product UI is viewed at consistent DPI, and a heading that shrinks inside a panel looks worse rather than better.

| Style | Face | Size | Weight | Tracking |
|---|---|---|---|---|
| Exhibit title | serif | 22px | 400 | -0.01em |
| Section header | sans | 15px | 500 | -0.01em |
| Placard | serif | 13px | 400 | 0 |
| Your note | sans | 13px | 400 | 0 |
| Body / reading | serif | 16px | 400 | 0 |
| Source line | mono | 11px | 400 | 0 |
| Label, button | sans | 13px | 400 | 0 |

Prose caps at 65-75ch. Dense lists may run tighter.

### Spacing, radius, motion

Multiples of 4, matching Dequeue so the two feel built by the same hand.

```
4px   micro
8px   compact gaps
14px  standard
20px  section gaps, side margins
28px  major sections
40px  page margins
```

Radius: 3px on artifact thumbnails (objects are square-ish, not soft), 8px on controls, 12px on panels, 9999px on pills.

Motion: 150-250ms, ease-out, state changes only.
No orchestrated load sequences. The museum is already built when you walk in.
Every transition needs a `prefers-reduced-motion` alternative.

### Components

- **Artifact rows are bordered list items**, not floating cards. Hairline dividers between them. Cards are the lazy answer and nested cards are always wrong.
- **The mount is the exception**: full-bleed within the list, gold rule top and bottom, vellum text, no radius. It reads as a panel let into the wall rather than a card sitting on it.
- **Primary action** is an ink fill in light mode and a gold fill in dark mode. One per view.
- **Secondary action** is a `border-strong` outline. Never a second filled button.
- Every interactive component ships default, hover, focus, active, disabled, loading, and error. Half a set is not a set.
- Empty states teach the interface. An empty museum says what capture does, not "nothing here."

### Surfaces

Eight, and only the exhibit was designed before this list existed.

#### 1. Capture

A borderless, always-on-top window over whatever is frontmost, opened by a global hotkey.
It must not raise or activate the main window.

Accepts paste, drop, typed text, and a screenshot region.
One field, plus an optional note that is never required.
Enter captures and the window is gone.

**It never asks a question, never blocks, and never shows a spinner.**
Processing is asynchronous without exception, and the 50ms dismissal budget is the one non-negotiable number in the product.
If capture ever feels slow, hoarding stops, and everything downstream has nothing to work with.

Three lessons transfer directly from Dequeue's equivalent window, each of which was a bug there first:

- **Transparency** requires `macOSPrivateApi` on Tauri, which App Review can reject. Dequeue carries this as an open risk. Enqueue should decide up front whether the rounded transparent card is worth the same exposure.
- **Theme sync**, because a long-lived separate webview does not re-read the theme on its own.
- **Dismissal**, because a window sized to its card means "clicking outside" is almost always a blur rather than a backdrop click, and the transient blur during window-show must not dismiss it instantly.

Feedback on success is a brief inline confirmation in the window as it dismisses, not a notification. Notifications nag, and the pile never nags.

#### 2. Home

Structure from Fabric, semantics inverted. Newest first, dense, no counts anywhere.

#### 3. Exhibit

The designed surface. Title, meta line, the mount holding the artifact on view, then bordered rows.

Actions: save, refresh, edit a placard, pin a note, eject.

**Refresh is the interesting one and it is half-specified everywhere else.**
After a refresh the room reports what changed: how many artifacts joined, whether the through-line moved, and whether anything you had ejected would have come back.
It never silently re-hangs. The report is the point, because it is the museum telling you your own mind changed shape.

**Ejection is permanent for that exhibit, with undo available for the session.**
Your edits survive every subsequent refresh. See product principle 7.

#### 4. Artifact

The object itself, plus everything derived from it.

Your notes, the source line, when it was captured, and which exhibits it is currently hanging in.
That last one is a backlink you never maintained, and it is where you see the shape of your own mind.

Facets are visible but collapsed by default. They are the machine's working, useful when an exhibit surprises you and you want to know why it pulled this in.

#### 5. Reading

Reading is first-class, not a fallback. You go into this museum.

Articles, PDFs, transcripts, and images render in place on the raised surface.
Serif at 16px, prose capped at 65-75ch.
Placards from every exhibit this artifact hangs in are available alongside, because the same object reads differently depending on which room you came from.

#### 6. Search

Returns artifacts, instantly, hybrid sparse and dense.
Adjacent results are shown below exact ones rather than mixed into them, since the whole reason search belongs in a museum is that it shows you what sits near the thing you wanted.

#### 7. Ask

A panel, not a page, and never the front door.
Scope is explicit and always visible: this artifact, this exhibit, or everything.
Answers carry citations back to the passage.
One button promotes an answer into an exhibit.

#### 8. Settings

Small, and mostly consequential rather than cosmetic.

- **AI backend picker.** Each option states what leaves the device *at the moment of choosing*, not in a help page. This is the mechanism that keeps the privacy promise honest while backends stay pluggable.
- **Storage backend**, same treatment.
- **Password and encryption**, including the plain statement that there is no recovery.
- **Local-only default** for new artifacts, and the per-artifact override.
- Theme, hotkey, capture surfaces.

#### 9. First run

Not a tour. Cold start is the identified death spiral, so first run has exactly one job: get material in.

Offer bulk import, install the browser extension, and set the hotkey. Then get out of the way.
An empty museum states what capture does and what will happen to it. It never says "nothing here yet."

---

### States

Specified because a system like this fails by looking fine.

| State | Behaviour |
|---|---|
| **Zero artifacts** | The empty museum teaches capture and import. No sample data, no fake exhibits. |
| **Under ~50 artifacts** | Curate still works and says so honestly: rooms will be thin until there is more material. It does not hide the feature or pretend. |
| **Ingest in flight** | The artifact exists and is readable immediately. Facets and placards arrive later. Nothing is gated on processing. |
| **Ingest permanently failed** | The artifact still exists, because captures are sacred. It is marked as text-only, searchable, and excluded from curate until reprocessed. It is never deleted and never silently dropped. |
| **Backend unreachable** | Ingest queues and retries. Curate says the curator is unavailable rather than returning a degraded room. A bad room is worse than no room. |
| **No local model configured** | Local-only artifacts keep plain text search and lose facets and placards. Stated plainly at the artifact, never silently sent to the network instead. |
| **Thin room** | Reported, never padded. The `thin` field is required in the synthesis schema so the model has to make the call explicitly. |
| **Loading a room** | The room fills progressively, artifact by artifact, as judgments return. Skeletons, never a spinner, and never a blocking 90 seconds of nothing. |

### Keyboard

Desktop is keyboard-first, matching Dequeue.

| Key | Action |
|---|---|
| `⌥⇧E` | global capture, from anywhere |
| `⌘K` | search |
| `⌘⇧K` | ask, at current scope |
| `j` / `k` | move between rows |
| `⏎` | open artifact |
| `⌘⏎` | save exhibit |
| `⌘R` | refresh exhibit |
| `⌫` | eject from exhibit |
| `⌘Z` | undo |
| `Esc` | dismiss |

The global hotkey must not collide with Dequeue's `⌥⇧A`, since both will be installed on the same machine.

### Icons

Single-stroke line icons at 1.8px, no fills, no emoji. Same stroke weight as Dequeue, because that weight is the family resemblance.

Lucide as the set. MIT, comprehensive, and its default stroke matches without overrides.

```
┌─────────────────────────────────────────────┐
│  Exhibits                              ›    │  standing shows, top billing
│  [ Antifragility ] [ Books ] [ Brutalism ]  │
│                                             │
│  Pinned                                ›    │  you pinned it, so it stays
│  [ card ] [ card ] [ card ]                 │
│                                             │
│  Recent artifacts                      ›    │  the loading dock, not an inbox
│  [ card ] [ card ] [ card ] [ card ]        │
│                                             │
│              ( + )  ( search )  ( ask )     │  floating, always reachable
└─────────────────────────────────────────────┘
```

- **Exhibits get top billing** over recent artifacts. The museum's current shows come before the loading dock.
- **Pinned stays.** You pinning something is a rare human signal and it is honoured.
- **Recent artifacts has no badge, no count, and no unread state.** Nothing anywhere tells you how many things are unprocessed, because nothing is unprocessed.
- The floating control holds the three acts and never merges them into one bar.

### Accessibility

- Every text token clears WCAG AA in both modes. Placeholders are held to 4.5 like body text, not to a muted-grey default.
- Colour is never the only carrier. The four voices distinguish speakers typographically, so the interface survives greyscale and colour blindness with no information lost.
- Reduced motion is not optional.

---

## Privacy

Privacy is the premise of the product, not a feature of it.

The thing being protected is not any single artifact.
Any one capture is innocuous.
Ten years of what you found interesting, plus the questions you asked about it, is a psychological profile that no single document in the hoard could produce.
The aggregate is the sensitive object.

### What Enqueue promises

1. **The hoard is encrypted at rest**, with a key derived from your password. Nothing readable sits on disk. A password prompt over plaintext files is theatre and does not count.
2. **Sync stores ciphertext.** Whoever holds the bytes - Proton Drive, S3, GCS - cannot read them.
3. **Nothing you save is ever used to train a model.**
4. **You choose the AI backend, and the app tells you what each one costs you.** See [Backends](#backends).
5. **Any artifact can be marked local-only.** It is never sent to a network model and never leaves the machine that captured it, whatever the defaults are set to.
6. **Enqueue never fetches your saved links without telling you.** The browser extension captures the page you already loaded, so no publisher and no ISP learns your reading list from us. Fetching exists only for what the extension cannot cover - bulk-importing old bookmarks, a link you were sent but never opened - and the app says so before it happens.
7. **You can always get everything out, as plain files.** `enq export` writes the whole museum as markdown plus original documents in an ordinary folder. No database, no encryption, nothing of ours required to read it. Your hoard is readable without this application, forever.

### What Enqueue does not promise

Stated plainly, because a privacy promise with unstated holes is worse than none.

- **Lose the password, lose the museum.** There is no recovery, because any recovery path is a copy of your key held by somebody else. This is exactly why promise 7 exists: keep an export somewhere the password cannot lock you out of.
- **Metadata leaks to whoever stores the blobs.** An object store sees how many objects exist, how big they are, and when they change. It never sees what they are.
- **Choosing a third-party backend means third-party terms.** OpenRouter and similar providers may log and may train. That is your call to make, and the app says so at the moment you make it.

### Backends

Every boundary that touches the outside world is pluggable, and every plug is labelled.

**AI backends:**

| Backend | What leaves the device | Use |
|---|---|---|
| Local (Ollama, on-device models) | nothing | local-only artifacts, offline work, maximum privacy |
| **Lumo (default)** | content, under zero-access encryption, no logs, no training | everything |
| OpenRouter and other cloud providers | content, under that provider's terms | when you knowingly trade privacy for capability |

Lumo is the default and the reason the product can make the promise it makes.
The others exist because a lifetime tool should not be hostage to one vendor's uptime, pricing, or continued existence.

**Storage backends:** local only (no sync), Proton Drive, S3, GCS.

**Threat model.** Defends against, in priority order: content becoming training data or an advertising profile; whoever runs the servers reading it, whether by breach, insider, or subpoena; someone with your unlocked machine; someone with your locked machine.

Detailed architecture - key derivation, envelope encryption, what the local model does, how exempt artifacts stay searchable - belongs in AGENTS.md, not here.

---

## Platforms

| Platform | Role |
|---|---|
| macOS | full peer. Ingest, index, curate, read. Any number of machines |
| Browser extension | primary capture surface |
| Android | capture-and-read satellite. Captures artifacts, syncs, reads an index a Mac built |

Local-first: every peer holds the whole museum, and sync moves ciphertext through an object store rather than centralising anything.
There is no primary machine and no device that has to be awake for another to work.

**Local-only artifacts do not sync.**
The flag that keeps an artifact away from network models also keeps it off every other machine.
That matters most on a work-managed computer, where the relevant risk is not a stolen laptop but an administered endpoint, and encryption at rest is not the defence against it.

Engineering detail lives in [AGENTS.md](../AGENTS.md).

---

## Open questions

Product:

- Cold start. The existing pile is hand-written book annotations in Fabric: small, high signal, low volume. Import is a modest job, and the museum opens close to empty either way, which is why capture volume matters more than import does.
- Which mono. It must be a text mono, not a coding face with programming ligatures.
- Whether the dark-room mount reads as an object floating in shadow or as an unrendered gap. See the note under [Tokens](#tokens).
- Whether the transparent capture window is worth the App Review exposure. See [AGENTS.md](../AGENTS.md) open items.
- Global hotkey default. `⌥⇧E` is provisional and must not collide with Dequeue's `⌥⇧A` on a machine running both.

Technical questions are now answered in [AGENTS.md](../AGENTS.md): retrieval architecture, data model, provider layer, crypto, sync, and the evaluation harness.

---

## Decision log

Decisions made deliberately, with the reasoning, so a future reader does not restore something that was reversed on purpose.

### Ask became a conversation, and its topics became lenses

Ask was one shot: name a theme, get an answer, lose the thread. That assumed you arrive knowing what you are looking for, which contradicts the premise of everything else here. The whole product exists because the conceptualisation shows up later.

A chat keeps the thread. But a stored transcript is not worth much on its own, and a sidebar of them is the failure mode this product is built against: a list that grows until nothing in it can be found.

What makes it worth keeping is that the concepts a conversation circles are extracted and stored against it, and those are the same kind of object a lens is. A topic can be handed straight back to the curator. So the sidebar is not a pile of transcripts, it is a list of concepts you arrived at by talking, each one a door into a room.

The risk taken knowingly: chat-with-your-notes is what Fabric and mem.ai already are, and a chat box on the home screen would make Enqueue a worse version of both. The mitigation is placement, not restraint in the feature. Conversations sit above the artifacts and never replace them, and asking stays one of three glyphs on one small control.

### A saved link says nothing until you ask it to

Saving a link fetches nothing, because a request at capture time tells the publisher you read the thing, for every link you ever save, whether or not you go back to it.

The cost is a museum full of bare URLs, which is a real cost and was the complaint that produced this entry. A preview pays it once, per link, when you press the button, and the button says what it will do.

Only text is stored. An `og:image` kept as a URL would fetch from the publisher on every single view, forever, which is worse than the one request the default was avoiding. That distinction is the whole reason this is a stored preview and not an embed.

Some publishers refuse a client that does not identify itself with a contact URL. Complying with a stated policy is identification, not evasion, and it stays a setting rather than a default that invents a URL nobody owns.

### Spaces were rejected, but structure was not

Fabric-style spaces were the reference for the home screen, and are explicitly not the model.
A space is a container you file into, so an item lives in one place, which is a folder tree with better typography.
Exhibits invert the mechanic: you describe a theme and the room fills itself.
The same UI affordance can stay; the semantics cannot.

The reason is toil, not structure.
Membership, backlinks, and themes are all welcome, and Enqueue stores real membership records.
What is rejected is the manual labour of producing them, and the tool refusing to accept something until you have.
An auto-populated space that you can adjust is just an exhibit; a space you drag things into is a folder.

### Reshape is not an operation

Changing an exhibit's theme creates a new exhibit rather than mutating the existing one.

Two reasons. It keeps refresh cheap and incremental, since a fixed theme means only newly captured artifacts need evaluating against it.
And it keeps exhibits honest as thinking artifacts: a room that silently became about something else destroys the record of what you were thinking when you built it.

Exhibits are cheap, so making a second room costs nothing.

### Originals are kept forever

Derived text alone would be smaller, and storage is not the argument either way.

The argument is re-processability.
The abstraction layer will improve, models will improve, and the definition of a good placard will change.
Keeping originals means the entire museum can be re-hung overnight when the curator gets better.
Keeping only derived text freezes the museum at whatever the 2026 model understood.
Link rot is the secondary argument: the article you saved is gone in three years.

### Enqueue is silent until asked

Proactive surfacing was considered and rejected: no digests, no notifications, no "you have saved fourteen things circling this idea."

Hoarding is only guilt-free if nothing nags.
A pile that taps you on the shoulder is an inbox, and an inbox is Dequeue's job.
The human supplies the formulation; the machine supplies the material. Pushing inverts that.

### AI backends are pluggable, and Lumo is the default

An earlier framing made Lumo a hard constraint: every AI call that touches content goes through Lumo, full stop.

That is now the default rather than the rule.
A museum meant to hold a lifetime cannot be hostage to one vendor's uptime, pricing, terms, or continued existence, and Lumo's own API had not shipped when this was written.
Local models via Ollama and cloud routers like OpenRouter are supported alongside it.

The privacy promise survives this only because of the labelling rule.
A backend picker that silently routes a lifetime hoard through a logging provider would make the promise meaningless.
Each backend states what leaves the device at the moment you choose it, and Lumo remains the default so the private path is the path of least resistance.

### Local-only artifacts stay in the museum

Marking an artifact exempt from AI could mean two things: no AI touches it ever, or it never goes to a *network* model.

The second reading is the shipped one.
A local model is not a disclosure, so a local-only artifact can still be indexed, still be found by search, and still hang in an exhibit - it simply never leaves the machine.
The first reading would exile the artifact from the museum entirely, which punishes you for hoarding exactly the material you most wanted kept.

Degradation is honest rather than hidden: with no local model configured, a local-only artifact keeps plain text search and loses its placards and abstractions.
It is never silently sent to the network instead.

### Ask is scoped, not a fourth feature

Question answering over your own material - the thing mem.ai and Fabric do - is a real requirement and was nearly modelled as its own subsystem.

It is instead one act with a scope dial: one artifact, one exhibit, or everything.
That collapses three apparent features into one, and it makes cost track scope for free.
A single-artifact ask skips retrieval entirely because the artifact fits in context.
An exhibit-scoped ask mostly fits too.
Only the everything scope pays for the full pipeline.

The risk being managed is drift.
Chat-with-your-notes is a commodity that two competitors already ship, and a product whose front door is a chat box has quietly become one of them.
Ask stays a utility, and curate stays the thing.

### The palette is two colours, and both are constrained

Several richer directions were built and rejected, and the reasoning matters because each will look tempting again.

**Oxblood as a wall** was too loud as a surface and, when muted to fit, became dusty rose, which is the opposite of rich. Lightening a deep red produces pink, so there is no muted-but-rich version of it.

**Two accents carrying separate jobs** (one for the curator, one for you) was coherent and encoded the director-and-curator split in colour. It was dropped because two accents are always one governance rule away from the gift shop. Filled-versus-drawn and the four voices carry the same information with one fewer colour to police.

**Bronze at mid value** was the worst outcome: two mid-brown surfaces adjacent is mud. Brown is desaturated orange, and warm plus mid lightness plus moderate chroma has no other result. Hence rule 3.

**A single mid-value gold shared by both modes**, the literal Solarized construction, was computed and rejected. The best achievable balance on these grounds is roughly 3.9 to 1 in each mode, and at that lightness the gold is mustard. Solarized accepts 2.98 to 1 for its yellow on its light ground because it is a syntax theme; product UI cannot.

What survived is the structural lesson rather than the literal one: hold a set fixed and invert the rest. Applied to the mount instead of to a hue, it works, and it is rule 2.

### Notes are documents, captures are not

The first build had one artifact model: immutable body, with an append-only note attached underneath. Every artifact was treated as something captured from the world.

That is right for a page, a PDF, or an image, where the promise is that what you saved is what the source said. It is wrong for a note you wrote. The symptom was a note whose text could not be changed, only added to; the cause was a data model with no concept of authorship.

Three categories now, not two:

- **A capture** is immutable. Fidelity is the point.
- **A note** is a document you own. Editing it rewrites the body and keeps the previous version.
- **An annotation** is your commentary on a capture, and stays append-only because it comments on something fixed.

Editing a note updates the artifact and appends to its version log. That is not a contradiction with append-only storage: the log is the history, the artifact is the current state, and nothing you wrote is ever destroyed.

### The output is a thinking surface, not a report

An early framing called the output a "comprehensive overview."
It is not.
An overview tells you what you already own, which you could get by re-reading the items.
An exhibit shows the connective tissue and the tensions, which you cannot get any other way.
