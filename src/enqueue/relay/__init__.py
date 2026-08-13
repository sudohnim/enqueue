"""The sync relay: a standalone, dumb, encrypted-opaque byte store.

This package is a separate FastAPI service, not part of the local engine.
It holds per-device snapshot objects and content-addressed blobs keyed by name,
serves them back, and streams a "something changed" signal over SSE.
It parses none of the bytes and can decrypt nothing.
"""
