# Superseded

The Part 4 sync plan moved to **`E2E.md`** and changed direction: from an
event-sourcing + hybrid-logical-clock design to a simpler **per-artifact snapshot,
last-writer-wins, provider-agnostic** model. The encrypted snapshots are the sync unit;
the storage provider is a dumb byte replicator, so any synced folder works.

Do not implement anything from this file's old history. Read `E2E.md`.
