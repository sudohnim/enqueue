"""Reciprocal Rank Fusion, as a pure function.

`search` runs the dense and the keyword branch separately, then merges the
two ranked id lists into one. RRF is the standard choice: it only looks at
ranks, so the two branches' incomparable score scales never have to be
reconciled, and it is stable under monotone rescoring of either branch.

Deliberately free of imports from the rest of the app: this module cannot
drag a database, a config, or an embedding model into anything that just
wants to merge two ranked lists, and it is testable in isolation.
"""

from __future__ import annotations

from typing import Any


def rrf(*ranked_lists: list, k: int = 60, limit: int = 30) -> list:
    """Fuse ranked id lists into one, highest fused score first.

    Each list is ids in rank order, best first. An id's fused score is the
    sum over every list that contains it of 1 / (k + rank), rank counting
    from 1. Ties are broken by first appearance, scanning lists in order, so
    the same input always produces the same output.
    """
    return [item for item, _ in rrf_scored(*ranked_lists, k=k, limit=limit)]


def rrf_scored(*ranked_lists: list, k: int = 60, limit: int = 30) -> list[tuple[Any, float]]:
    """Like `rrf`, but each id comes with its fused score.

    The store needs the score as well as the ordering: hits carry a score the
    caller can compare across branches, and recomputing it here instead of in
    the store keeps the formula in exactly one place.
    """
    score: dict[Any, float] = {}
    first: dict[Any, int] = {}
    order = 0
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            if item not in first:
                first[item] = order
                order += 1
            score[item] = score.get(item, 0.0) + 1.0 / (k + rank)
    ranked = sorted(score, key=lambda item: (-score[item], first[item]))
    return [(item, score[item]) for item in ranked[:limit]]
