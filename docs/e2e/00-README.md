# Enqueue Implementation Plan — Operating Manual

Read this file first. Read it again at the start of every session.

## The single most important rule

**Never load more than one phase file at a time.**

This plan is deliberately split across files because the implementing model has a
finite context window and loses track of long sequences. Loading the whole plan is
the main way this fails.

One session = one phase. Finish it, commit, update `PROGRESS.md`, start a new session.

## File map

| File | What it is | Who reads it |
|---|---|---|
| `00-README.md` | this operating manual | everyone, every session |
| `01-DECISIONS.md` | questions a human must answer before coding | the maintainer, once |
| `PROGRESS.md` | which phase and step we are on | everyone, every session |
| `E2E.md` | encrypted, provider-agnostic sync (per-artifact snapshot model). Phases E1-E8 | agent, with review |


## Step tags

Every checkbox is tagged. Respect the tag.

- **`[AGENT]`** — mechanical. Implement it.
- **`[HUMAN]`** — requires judgment, a real person, or a decision with consequences.
  **Stop and hand it over.** Do not attempt it. Do not fabricate a result.

If a step asks you to make a design tradeoff, choose a security parameter, judge
whether something "feels right", or complete a manual test as a user, it is
`[HUMAN]` even if it is not tagged. Stop and ask.

## Progress protocol

After finishing each checkbox:

1. Commit the code change alone.
2. Tick the checkbox in the phase file.
3. Update `PROGRESS.md` with the phase, the step, and the date.
4. Commit those two files together with the message `progress: <phase> <step>`.

At the start of every session, read `PROGRESS.md` first and resume from there.
Never assume you know where you left off.

## Rules

- One checkbox per commit. Never batch.
- After every checkbox the app must still start and existing tests must pass.
- Every step must be idempotent. Running it twice changes nothing the second time.
- If a file or table already exists in the required state, tick the box and move on.
- Never weaken an existing privacy rule to make a step easier. If a step seems to
  require that, stop and report.
- If a step says STOP, stop. Write your findings into the named file and hand over.

## When a step fails

Do not improvise around it.

1. Try at most twice.
2. If it still fails, `git revert` your attempt so the tree is clean.
3. Write what you tried and the exact error into `PROGRESS.md` under `## Blocked`.
4. Stop. Hand over.

A clean tree and an honest blocker beats a half-applied change.

## Testing rigor

Where a step says "property test", it means:

- Use `hypothesis`.
- At least 100 generated examples.
- A fixed seed recorded in the test.

Three hand-picked cases is not a property test. The replay-determinism invariant in
Part 4 is the one thing everything else depends on; a weak test there is worse than
no test, because it produces false confidence.

## Model guidance

- **Parts 1-3** are a reasonable fit for a mid-tier coding model.
- **Part 4** involves event sourcing, a hybrid logical clock, and cryptography.
  Multi-turn reliability degrades over long sequences, and mistakes here are silent
  and destroy data. Use the strongest model available, and have a human review every
  phase before moving on.

## What this plan will not do

It will not decide product questions for you. Those are in `01-DECISIONS.md`.
It will not run a user experience test. Those steps are `[HUMAN]` and say STOP.
