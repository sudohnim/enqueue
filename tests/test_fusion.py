"""Reciprocal Rank Fusion: hand-computed expectations and determinism.

The four shapes the plan calls out cover the ways two ranked lists can
relate: one list alone, identical lists, disjoint lists, and lists sharing a
single id. Every expected value below is computed by hand from the formula
score(id) = sum over lists of 1/(k + rank), k = 60.
"""

from __future__ import annotations

from enqueue.index.fusion import rrf, rrf_scored


def test_one_list_passes_through() -> None:
    assert rrf(["a", "b", "c"], k=60, limit=30) == ["a", "b", "c"]


def test_two_identical_lists_double_the_score() -> None:
    # a: 1/61 + 1/61, b: 1/62 + 1/62; same order, no ties to break.
    assert rrf(["a", "b"], ["a", "b"], k=60, limit=30) == ["a", "b"]


def test_two_disjoint_lists_tie_break_by_first_appearance() -> None:
    # a and c both score 1/61, b and d both 1/62. First appearance order:
    # a (list 1, rank 1), b (list 1, rank 2), c (list 2, rank 1), d (list 2, rank 2).
    assert rrf(["a", "b"], ["c", "d"], k=60, limit=30) == ["a", "c", "b", "d"]


def test_two_lists_sharing_one_id() -> None:
    # a: 1/61 (list 1, rank 1) + 1/62 (list 2, rank 2) ~ 0.03253
    # x: 1/61 (list 2, rank 1)                          ~ 0.01639
    # b: 1/62 (list 1, rank 2)                          ~ 0.01613
    # c: 1/63 (list 1, rank 3)                          ~ 0.01587
    assert rrf(["a", "b", "c"], ["x", "a"], k=60, limit=30) == ["a", "x", "b", "c"]


def test_limit_truncates() -> None:
    assert rrf(["a", "b", "c", "d"], k=60, limit=2) == ["a", "b"]


def test_deterministic_for_the_same_input() -> None:
    """Same input, any number of runs: identical output, order included."""
    lists = (["a", "b", "c"], ["x", "a", "d"], ["b", "x"])
    first = rrf(*lists, k=60, limit=30)
    for _ in range(5):
        assert rrf(*lists, k=60, limit=30) == first


def test_scored_variant_matches_the_formula() -> None:
    out = rrf_scored(["a", "b", "c"], ["x", "a"], k=60, limit=30)
    by_id = dict(out)
    assert round(by_id["a"], 12) == round(1 / 61 + 1 / 62, 12)
    assert round(by_id["x"], 12) == round(1 / 61, 12)
    assert round(by_id["b"], 12) == round(1 / 62, 12)
    assert round(by_id["c"], 12) == round(1 / 63, 12)
