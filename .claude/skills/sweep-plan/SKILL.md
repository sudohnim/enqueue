---
name: sweep-plan
description: Consolidate the repo's PLAN.md and PROGRESS.md into the durable docs (AGENTS.md, README.md), then truncate PLAN.md and PROGRESS.md to only open work. Use when PLAN.md/PROGRESS.md have grown large and finished work risks getting lost, or when the user asks to sweep, consolidate, or compact the plan.
version: 1.0.0
user-invocable: true
argument-hint: ""
allowed-tools: Read, Edit, Write, Grep, Bash, AskUserQuestion
---

# sweep-plan

Finished work piles up in `docs/PLAN.md` and `docs/PROGRESS.md`.
As those files grow, the durable lessons inside them (why a thing is built the way it is, what invariant must hold, what gotcha bit us) get buried and eventually lost.
This skill lifts the durable knowledge up into the two curated files that agents and humans actually read - `AGENTS.md` (how the system works and why) and `README.md` (how to run and use it) - and then trims the plan files back down to only the work that is still open.

The rule that makes this safe: **nothing is deleted from PLAN.md or PROGRESS.md until its durable content already lives in AGENTS.md or README.md (or is confirmed ephemeral).**
Git history keeps the raw removed text regardless, so truncation loses nothing that mattered.

## What counts as durable vs ephemeral

Durable (must be captured before truncation):
- Architecture, module boundaries, data flows, invariants, schema facts -> `AGENTS.md`.
- Resolved decisions and the REASON behind them (so the next person does not reverse a correct call under pressure) -> `AGENTS.md` `## Resolved decisions`.
- Gotchas and hard-won constraints (for example: use 127.0.0.1 never localhost; the keychain stores the DEK base64 so the QR must pass it verbatim; a null `getElementById(...).addEventListener` aborts page init) -> `AGENTS.md`, in the section the gotcha belongs to.
- User-facing behavior, CLI commands, config keys, run/verify steps, known gaps -> `README.md`.

Ephemeral (safe to drop, git keeps it):
- Blow-by-blow debugging narrative, superseded approaches, dead ends, one-off verification transcripts.
- Task bookkeeping (done-when checklists, verify recipes) for work that is finished.

Open work (never remove): any task still `[ ]`, or `[~]` that is not yet verified/committed, stays in PLAN.md verbatim.

## Process

Do the steps in order. Do not truncate before the user confirms (step 5).

1. **Read all four files** in full: `docs/PLAN.md`, `docs/PROGRESS.md`, `AGENTS.md`, `README.md`.
   Note the section headers of AGENTS.md and README.md so you fold into the RIGHT existing section instead of appending a new one.

2. **Classify every PLAN.md phase/task and PROGRESS.md entry** as DONE or OPEN.
   DONE = marked `[x]`, or `[~]` whose text says committed/verified/superseded/closed.
   OPEN = `[ ]`, or `[~]` still pending device-verify / not committed.
   A phase can be mixed: some tasks done, some open. Handle per task, not per phase.

3. **Extract the durable knowledge** from the DONE items.
   For each, decide its destination (AGENTS.md section, README.md section, or drop as ephemeral).
   Write it in the destination's voice and register, not as a changelog entry.
   Merge into existing sentences/sections; do not create a duplicate section or a "recently completed" dumping ground.
   Convert relative dates to absolute. Follow the repo style rules below.

4. **Edit AGENTS.md and README.md** to land that knowledge.
   Then re-read the edited sections and confirm each durable fact from step 3 is actually present.
   This is the gate: a fact not yet in the curated docs blocks truncating the source that carries it.

5. **Show the user the plan before truncating.**
   Summarize: what moved into AGENTS.md, what moved into README.md, what will be dropped as ephemeral, and exactly which PLAN.md phases/tasks and PROGRESS.md lines will be removed vs kept.
   Ask for confirmation with AskUserQuestion (options: proceed with truncation / adjust first).
   Do not proceed on anything except an explicit yes.

6. **Truncate, after confirmation.**
   - `docs/PLAN.md`: keep the file header and any top "Context" block, the OPEN tasks (verbatim, under their phase headers), and the `## Out of scope` section. Remove the DONE phases/tasks. If a phase becomes empty, remove its header too. At the top, under the title, keep or add one line: `Swept <YYYY-MM-DD>: finished work folded into AGENTS.md and README.md; git history holds the raw detail.`
   - `docs/PROGRESS.md`: reset to a short current-state stub - the title, the same swept-on line, and a brief "Current state" paragraph plus any still-in-flight notes. Drop the finished log.
   - Never touch auto-generated files. Never edit CHANGELOG.md.

7. **Report** what changed and remind the user to review the diff and commit themselves.
   Do not commit or stage anything.

## Repo style rules (must follow)

- Never use the em dash. Use a plain dash instead.
- In AGENTS.md, README.md, PLAN.md, PROGRESS.md, put each full sentence on its own line.
- Do not run `git commit`, `git add`, or stage anything. Leave the working tree for the human to review and commit.
- Do not auto-add an agent name as co-author anywhere.
- Weigh quality, simplicity, and long-term maintainability over development cost when deciding what durable knowledge to keep.

## Guardrails

- If AGENTS.md or README.md already states a fact, refine it in place rather than adding a second copy.
- If you are unsure whether something is durable, keep it: fold it in rather than dropping it.
- If a DONE item's only content is ephemeral (a dead end with no lasting lesson), it is fine to drop it without folding, but say so in the step 5 summary.
- If PLAN.md/PROGRESS.md are already small (for example under ~150 lines combined and no clearly-finished phases), say there is nothing worth sweeping and stop, rather than churn the files.
