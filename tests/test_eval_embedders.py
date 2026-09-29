"""The embedder comparison: floor fitting and config swapping."""

from __future__ import annotations

from enqueue import config
from enqueue import eval_embedders as ee
from enqueue.retrieve import candidates as cand


def test_bars_sit_outside_the_calibration_extremes():
    bars = ee.suggest_bars(real_best=[0.43, 0.56, 0.7], nothing_best=[0.38, 0.6])
    assert bars == {"keep_above": 0.62, "drop_below": 0.41}


def test_cleanly_separated_scales_never_invert_the_bars():
    bars = ee.suggest_bars(real_best=[0.8, 0.9], nothing_best=[0.3])
    assert bars["keep_above"] >= bars["drop_below"]


def test_using_swaps_the_embedder_and_floor_then_restores_them():
    before = (config.EMBED_MODEL, config.EMBED_DOC_PREFIX, cand.KEEP_ABOVE)
    with ee.using("nomic-ai/nomic-embed-text-v1.5", {"keep_above": 0.9, "drop_below": 0.1}):
        assert config.EMBED_QUERY_PREFIX == "search_query: "
        assert config.EMBED_DOC_PREFIX == "search_document: "
        assert (cand.KEEP_ABOVE, cand.DROP_BELOW) == (0.9, 0.1)
    assert (config.EMBED_MODEL, config.EMBED_DOC_PREFIX, cand.KEEP_ABOVE) == before


def test_the_current_model_is_a_candidate_with_its_committed_prefixes():
    spec = ee.CANDIDATES[config.EMBED_MODEL]
    assert spec["query_prefix"] == config.EMBED_QUERY_PREFIX
    assert spec["doc_prefix"] == config.EMBED_DOC_PREFIX
