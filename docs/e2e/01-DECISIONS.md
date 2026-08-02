# Decisions a human must make first

These were pulled out of the implementation phases on purpose. Each one is a real
tradeoff with consequences, and a model asked to "decide and record" will produce a
confident-sounding answer without actually weighing anything.

**No code begins until every question below has an answer written into it.**

Answer in plain language. Write the answer under the question. Then set the decisions
line in `PROGRESS.md` to YES.

---

## D1 — How is the database encrypted today?

Phase 0 will investigate and report. You decide what to do with the finding.

- **(A) The whole file is locked**, opened with a key. The app sees normal data inside.
- **(B) Individual fields are locked** separately, and stay scrambled while the app runs.
- **(C) Not encrypted at all.**

**Why it matters:** search needs readable data inside the database. Under (B) neither
keyword search nor vector search can work, and Part 3 must be redesigned.

**Recommendation:** (A). It is the only option compatible with searching your own
library. Its cost is that something already running on your unlocked machine could
read the file; (B) would prevent that and also prevent search, which defeats the
product.

**Answer:** (C) Not encrypted at all. Confirmed — the database is plain SQLite (`~/.enqueue-poc/enqueue.db`).
Encryption at rest is a planned milestone, not built yet.

---

## D2 — When a topic is applied, do pinned items stay pinned?

You have a shelf of pinned items above the wall. Under a topic view, pinned items
could stay on their shelf, or get sorted into related/not-related like everything else.

**Tradeoff:** keeping them pinned means the shelf is stable and predictable, but a
pinned item unrelated to your topic still sits at the top taking space. Sorting them
in makes the view purely about the topic, but your pinned things move around.

**Recommendation:** keep pinned pinned, above both sections. Pins are a deliberate
user act; a topic view is temporary and should not disturb them.

**Answer:** Keep pinned pinned, above both sections. A topic view is temporary and
should not disturb deliberate pins.

---

## D3 — When the library outgrows one pass, what do you call the second section?

At a few hundred items, everything gets examined and "not related" is true. When the
library is large enough that only part of it was examined, the second section contains
items nobody looked at.

- **(A)** Label it honestly: *not yet checked*, with a way to check more.
- **(B)** Label it *not related* regardless.

**Tradeoff:** (A) is truthful but exposes that the answer is incomplete. (B) reads
cleaner and is a lie.

**Recommendation:** (A). The product's whole premise is that it does not quietly
mislead you about your own library.

**Answer:** "not checked yet" — (A). Honest about incompleteness, with a way to
check more on demand.

---

## D4 — How aggressive should the relevance cutoff be?

Phase 13 measures this. You choose the tradeoff it optimizes for.

- **(A) Loose cutoff** — almost nothing relevant gets missed, but some unrelated items
  appear in the related section.
- **(B) Tight cutoff** — the related section is clean, but some relevant things end up
  in the second section where you may never look.

**Recommendation:** (A). A stray item you can see and dismiss costs you two seconds.
A relevant item hidden in the wrong section is invisible, and you will never know it
was there.

**Answer:** Medium. Not as loose as the recommendation, not tight. To be quantified
in Phase 13 once there are real measurements.

---

## D5 — Argon2id parameters for the password

Do not let a model choose these. They determine how hard your password is to attack.

Write the three values here: **memory cost**, **iterations**, **parallelism**.

Guidance: use the current published recommendation from the library you adopt
(libsodium's `crypto_pwhash` INTERACTIVE or MODERATE presets are reasonable named
choices). Pick a named preset rather than hand-tuned numbers, and record which one.

**Tradeoff:** stronger settings mean a slower unlock on every app open, and much
slower offline attacks against a stolen file.

**Answer:** libsodium `crypto_pwhash` INTERACTIVE preset. To be confirmed when sync
is built; can be bumped to MODERATE or SENSITIVE later.

---

## D6 — How many events per uploaded bundle?

Sync writes files into a folder your cloud client replicates. One file per event
produces tens of thousands of tiny files, which some sync clients handle badly.
Batching means a delay before your changes reach another device.

**Tradeoff:** larger bundles mean fewer files and happier sync clients, but a longer
wait before another machine sees your edit. Smaller bundles sync faster and risk
choking the client.

**Recommendation:** start with a short time window rather than a fixed count, so idle
periods do not hold changes hostage. Write the chosen window here.

**Answer:** Start with a short time window rather than a fixed count. Idle periods
should not hold changes hostage.

---

## D7 — Pruning rules for old history

Compaction removes old events so a new device does not replay years of history. The
danger is pruning something a device that has been offline for a long time still needs.

Decide: **how long must a device be able to stay offline and still catch up?**

**Tradeoff:** a long window means the history keeps growing. A short window means a
laptop left in a drawer for months may be unable to reconcile and needs a full rebuild.

**Answer:** No practical limit. Sync must be robust enough to catch up after months
or years offline. If the history grows too large, that tradeoff can be revisited.

---

## D8 — Should the trash empty itself?

Deleted items sit in the trash until emptied. Emptying is what actually removes them
from storage, on every device.

- **(A)** Manual only. Nothing is ever destroyed without you asking.
- **(B)** Auto-empty after N days, configurable, default off.

**Tradeoff:** (A) means deleted things linger in your cloud folder indefinitely unless
you remember. (B) means storage cleans itself, at the cost of a deadline you might
forget you set.

**Recommendation:** (B) with the default off. Offer it; do not impose it.

**Answer:** Already implemented in the codebase as `trash_days` (default 30,
configurable via settings or `ENQ_TRASH_DAYS`). Auto-empty after N days with
expiry at startup. This decision is settled.

---

## D9 — Is the topic view available on a phone?

The topic view scores every item using both meaning and exact-word matching. A phone
is planned to have only the keyword half, because shipping the meaning data to it is
large and the design says it never leaves a machine.

- **(A)** Phone gets no topic view. Search only.
- **(B)** Phone gets a keyword-only topic view, clearly weaker than on a laptop.
- **(C)** Phone computes meaning data itself.

**Tradeoff:** (B) is available but will disagree with your laptop for the same topic,
which is the exact inconsistency this project already avoids elsewhere. (A) is honest
but a missing feature. (C) is consistent but a significant amount of work.

**Answer:** (A) — phone gets no topic view. Search only. A weaker inconsistent
version is worse than none.

---

## D10 — Which model runs Part 4, and who reviews it?

Part 4 is event sourcing, a hybrid logical clock, and cryptography. Errors there are
silent and destroy data, and multi-turn reliability degrades across long sequences.

Decide: **which model**, and **will a human review each phase before the next begins?**

**Recommendation:** strongest model available, human review per phase, no exceptions.

**Answer:** OpenRouter, using Kimi k3 or GLM-5.2 (whichever performs better on the
crypto/sync tasks).
Human review at the end of Part 4 rather than per-phase, unless a phase unearths
something unexpected that warrants intervention.
