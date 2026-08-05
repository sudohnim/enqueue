# Tags — design analysis (no code yet)

A review of how to add user tags to Enqueue: the data model, search integration, wall
filtering, and where the UI lives. Analysis only; nothing is implemented.

## 0. The principle tension, and how to stay on-side

The original design bans "being asked to file, tag, or link something by hand before the
tool will accept it" (PRODUCT principle 3). Tags look like exactly that. They are not, if
one line is held:

> **Never ask for a tag at capture time. Never require one. Ever.**

Capture stays zero-friction (hotkey, paste, gone). A tag is an *optional, later, deliberate*
act performed on an artifact you already own, the same category as an annotation or a pin.
Under that framing tags are additive, not a violation. The ban was about friction at the
door, not about forbidding the user from labelling their own things afterward.

Corollary: tags are **user-authored and sacred** (principle 6), so they live with
`annotations`/`artifacts`, never with the derived `chunks`/`facets` that get rebuilt.

---

## 1. Data model

Two new tables. Both are source-of-truth rows (not derived), so they survive `enq rebuild`.

```
tags(
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,   -- canonical: lowercased, trimmed
  created_at  TEXT NOT NULL
)

artifact_tags(
  artifact_id TEXT NOT NULL REFERENCES artifacts(id),
  tag_id      TEXT NOT NULL REFERENCES tags(id),
  created_at  TEXT NOT NULL,
  PRIMARY KEY (artifact_id, tag_id)
)
```

- **Why a join table, not a JSON column on `artifacts`:** the join table indexes both
  directions cheaply. "All tags with counts" and "artifacts having tag X" are both one
  indexed query. A JSON column can do neither without a scan.
- **Normalization:** store one canonical name (lowercase, trimmed). Exact match only, no
  fuzzy — tags are precise by nature; fuzzy matching defeats their purpose. Decide once
  whether spaces are allowed (recommend: yes, but treat `machine learning` as one tag,
  not two).
- **Sync (Part 4, E2E.md):** a tag edit is a change to an artifact. Add a `tags` list to
  the per-artifact snapshot (Section 1 of E2E.md). LWW per artifact already covers it. No
  new sync mechanism, no new event type. This is a clean fit with the snapshot pivot.

---

## 2. Search integration (the part you care about most)

Today: hybrid dense + FTS5 over `chunks` and `facets`, rolled up to one row per artifact.
The chunk index text is `"{title}\n\n{text}"` (`CHUNK_INDEX_TEXT` in `store_sqlite.py`).

Three ways to bring tags in. The recommendation is **B**, optionally plus a light **A**.

### Option A — fold tags into the index text (index-time boost)
Change `CHUNK_INDEX_TEXT` to `"{tags}\n{title}\n\n{text}"`, so a tag word ranks through the
existing FTS + dense path.
- **Pro:** zero new query code; a tag word typed plainly still nudges ranking.
- **Con:** tags get diluted among body text; no precise "only things tagged X"; a tag
  change forces re-chunking that artifact (chunks are derived, so rebuild is fine but not
  free). Weak precision.

### Option B — structured `tag:` / `#` filter (RECOMMENDED)
Parse the query for `#work` or `tag:work` tokens before search:
- The tag tokens become an **exact filter** against `artifact_tags` (an id set / WHERE
  clause), intersected with the hybrid results.
- The free-text remainder runs through normal hybrid search.
- `kubernetes #work` = semantic "kubernetes" **AND** tagged `work`.
- A **bare tag query** (`#work`, nothing else) skips embedding entirely and is a plain
  SQL filter on `artifact_tags` — roughly 1 ms, versus ~11 ms to embed a query. That is
  both a feature (instant) and aligned with the query-speed work already done (the
  embed-cache pass). Tags become the fastest possible search.

This treats tags as a **filter dimension**, not as fuzzy text to rank — which is exactly
how tags work mentally ("show me the things I marked X"). It gives precise filtering while
leaving semantic search untouched.

### Option C — tags as a third RRF branch
Overkill. RRF fusion exists to blend *fuzzy* rankings; tags are exact tokens. Skip.

**Verdict:** ship **B** as the primary path. Optionally add **A** later so an un-prefixed
tag word still helps ranking. B alone satisfies the "reach for easy tags" workflow.

---

## 3. Filtering and sorting the wall

- `list_artifacts(...)` gains an optional `tags: list[str]` parameter with **AND**
  semantics (artifact has *all* listed tags):
  `WHERE id IN (SELECT artifact_id FROM artifact_tags at JOIN tags t ON t.id = at.tag_id
  WHERE t.name IN (...) GROUP BY artifact_id HAVING COUNT(*) = <len(tags)>)`.
  Keep `order` and `pinned` as they are.
- **You filter by tag; you sort by time.** A tag is a set membership, not an orderable key,
  so "sort by tag" is not a real operation. Correcting the phrasing in the request: tags
  are a filter, the existing `touched` / `created` orderings stay the sort.
- **"All available tags"** is one cheap query:
  `SELECT t.name, COUNT(*) n FROM tags t JOIN artifact_tags at ON at.tag_id = t.id
  GROUP BY t.id ORDER BY n DESC`. That is the tag cloud / index, and the source for the
  tag bar below.

---

## 4. Where it lives in the UI (layout skill applied)

Product register: predictable, familiar, hierarchy through space and weight — no invented
affordances. The app is chrome-less (the rail was removed), so tags live **inline**, never
in a sidebar. Four surfaces, in priority order.

### (a) Add / remove a tag — on the artifact detail page
This is where the deliberate optional act belongs, never at capture. A **chip row directly
under the `.meta` line** (kind dot + kind word + date), above the body pane. Existing tags
render as chips with a small `x`; an inline "add tag" input autocompletes against the tag
cloud. Grouping: the chip row is part of the "about this artifact" cluster, so keep it
tight to `.meta` and take the generous step down to the body pane. One new spacing group,
consistent with the CSS comment already there ("one tight group, then a generous step").

### (b) See all tags + one-click filter — the home wall (the "easy reach")
The home is `greeting → searchbar → shelves`. Insert a **tag bar**: a single horizontal row
of the **top-N tags by count** as chips, placed **directly under the searchbar, above the
first shelf**. Clicking a chip filters the wall to that tag (sets `#tag` as the active
query). This is the reaching-for-easy-tags path the request is about — tags are one click
from the home screen.
- **Hierarchy through weight:** the searchbar stays the primary input (largest, bordered);
  the tag chips are secondary (smaller, muted until hover/active). Space and weight carry
  importance, per the skill — no new colours needed; reuse `--surface-2` for a resting
  chip, `--accent` outline for the active one.
- **Do not render every tag** — a heavy tagger would flood the bar (the skill's
  "identical-grid noise" failure). Show top-N (say 8-12) plus a small "all tags" affordance.
- This keeps the existing vertical rhythm: tight `greeting + search` group, then the tag
  bar as a lighter secondary band, then the generous gap to the `saved` shelf. No sidebar,
  no chrome, faithful to the current direction.

### (c) The active-filter state
When a tag is active, reuse the existing search-result header pattern (`doSearch` renders
"N results for ..."). The wall header becomes "Tagged **#work**" with a clear-filter `x`.
Consistency with the search surface *is* the affordance — a user who has searched already
knows this shape.

### (d) Dedicated "all tags" view — phase 2, optional
The full tag cloud sorted by frequency, each chip a filter entry point, reached from the
"all tags" affordance on the bar. Low priority; the top-N bar covers the core need.

### The card face — deliberately NOT tagged
Cards already carry kind dot + kind word + date. Putting tags on every card face is clutter
and pushes the grid toward the identical-card monotony the layout skill warns against. Keep
the card clean; surface tags on **hover** at most, or a tiny count. Tags are a filter and a
detail-page concern, not a card-face concern.

---

## 5. Risks and decisions to settle before building

| Decision | Recommendation |
|---|---|
| Tag explosion (heavy tagger floods the bar) | Cap the bar at top-N by count; rest behind "all tags". |
| Case / spaces / synonyms | Lowercase canonical, exact match, spaces allowed as one tag. No fuzzy, no auto-synonyms. |
| Re-index on tag change | Avoided entirely if search uses Option B (filter, not index). Only Option A needs it. |
| Multi-tag filter semantics | AND (has all). OR can come later behind a toggle if wanted. |
| Rename / merge tags | Defer. A rename is an update to `tags.name`; a merge repoints `artifact_tags`. Not v1. |
| The capture-time ban | Hold it. No tag prompt at capture, ever. Tags only on an artifact you already own. |

---

## 6. Minimal viable slice (build order)

1. `tags` + `artifact_tags` migration (source-of-truth tables).
2. Add/remove-tag API + the chip row on the artifact detail page (surface **a**).
3. `#tag` / `tag:` parsing in `/search` → exact `artifact_tags` filter, with the
   **no-embed fast path** for a pure tag query (Option B).
4. Tag bar under the searchbar, top-N chips, click-to-filter (surface **b**), reusing the
   active-filter header (surface **c**).
5. `list_artifacts(tags=...)` parameter for the filtered wall.

Defer: all-tags view (d), card-face display, rename/merge, Option A ranking boost.

The whole slice reuses existing machinery — the FTS/hybrid path is untouched (tags are a
filter beside it), the wall composition gains one band, and the artifact page gains one
chip row. No architectural change, and it drops cleanly into the E2E.md snapshot for sync.
