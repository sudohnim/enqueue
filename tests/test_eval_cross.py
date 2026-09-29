"""The cross-domain eval: suite integrity, scoring, and the facet plumbing end to end."""

from __future__ import annotations

import json

import pytest

from enqueue import eval_cross as xd


@pytest.fixture(scope="module")
def suite():
    return xd.load_suite()


def test_ids_are_unique_and_do_not_clash_with_the_main_corpus(suite):
    ids = [n["id"] for n in suite["notes"] + suite["decoys"]]
    main = {
        e["id"] for e in json.loads((xd.MAIN_CORPUS / "MANIFEST.json").read_text())["artifacts"]
    }
    assert len(ids) == len(set(ids))
    assert not set(ids) & main


def test_every_target_has_exactly_one_query_and_decoys_are_never_expected(suite):
    targets = {n["id"] for n in suite["notes"]}
    expected = [aid for q in suite["queries"] for aid in q["expect"]]
    assert sorted(expected) == sorted(targets)
    assert not {d["id"] for d in suite["decoys"]} & set(expected)


def test_no_target_shares_its_query_vocabulary(suite):
    """The whole point: the note must be findable only by meaning, never by words."""
    notes = {n["id"]: n for n in suite["notes"]}
    for q in suite["queries"]:
        assert q["forbidden"], q["id"]
        for aid in q["expect"]:
            text = notes[aid]["title"] + "\n" + xd.note_body(notes[aid])
            assert xd.forbidden_hits(text, q["forbidden"]) == [], (q["id"], aid)


def test_forbidden_hits_matches_whole_words_only():
    assert xd.forbidden_hits("A ship sailed.", ["ship"]) == ["ship"]
    assert xd.forbidden_hits("Their relationship held.", ["ship"]) == []
    assert xd.forbidden_hits("Do not burn out now", ["burn out"]) == ["burn out"]


def test_rank_and_score():
    assert xd.rank_of(["b"], ["a", "b", "c"]) == 2
    assert xd.rank_of(["z"], ["a"]) is None
    results = [
        {"id": "1", "rank": 1, "pass": True},
        {"id": "2", "rank": 4, "pass": False},
        {"id": "3", "rank": None, "pass": False},
    ]
    s = xd.score(results)
    assert (s["total"], s["pass"], s["pass_rate"]) == (3, 1, 0.3333)
    assert s["MRR"] == round((1 + 0.25) / 3, 4)


def test_fixture_facets_reach_search(tmp_path, monkeypatch):
    """A fixture facet must survive the staleness check and lift its note; fixture
    entities and lifts load too.

    The facet repeats one query word for word, so with facets loaded the target has a
    keyword hit on the facet layer and must pass; this fails if load_facets stamps a
    model the search staleness check rejects.
    """
    from enqueue import settings
    from enqueue.retrieve import candidates as cand

    monkeypatch.setattr(xd, "TEST_DIR", tmp_path / "xd")
    monkeypatch.setattr(xd, "FACETS_PATH", tmp_path / "facets.json")
    monkeypatch.setattr(settings, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(
        cand, "judge_gray_zone", lambda query, hits: {h["artifact_id"] for h in hits}
    )

    suite = xd.load_suite()
    q = suite["queries"][0]
    (tmp_path / "facets.json").write_text(
        json.dumps(
            {
                "facets": {
                    q["expect"][0]: [{"level": 3, "statement": q["query"] + ".", "trust": 1.0}]
                },
                "entities": {
                    q["expect"][0]: [{"entity": "Q", "fact": "Q - a stand-in entity line."}]
                },
                "lifts": {q["id"]: [q["query"] + " again."]},
            }
        )
    )
    report = xd.run()

    assert report["facets_loaded"] == 1
    by_id = {r["id"]: r for r in report["modes"]["enriched"]["results"]}
    assert by_id[q["id"]]["pass"], by_id[q["id"]]
    assert set(report["modes"]) == {"chunks", "enriched", "lifted"}
    assert report["entities_loaded"] == 1
    assert report["lifts_loaded"] == 1
    assert {r["id"]: r for r in report["modes"]["lifted"]["results"]}[q["id"]]["pass"]
    assert report["modes"]["enriched"]["total"] == len(suite["queries"])


def test_ingest_prompts_do_not_leak_the_eval(suite):
    """Prompt examples must not mention an eval target's subject, or the eval would
    measure the prompt's examples instead of the model's ability to abstract."""
    from enqueue import prompts

    subjects = [
        "willow", "oak", "reed", "baton", "relay", "mise", "burn", "fire", "forest",
        "hive", "bee", "chess", "opening", "crop", "soil", "bulkhead", "hull",
        "jazz", "chorus", "sourdough", "starter", "postal", "postage", "tide",
        "pigment", "migratory",
    ]  # fmt: skip
    for name in (
        "FACET_GENERATION",
        "ENTITY_EXTRACT",
        "ENTITY_ENRICH_BATCH",
        "CHUNK_CONTEXT",
        "QUERY_LIFT",
        "SECTION_SUMMARY",
    ):
        assert xd.forbidden_hits(getattr(prompts, name), subjects) == [], name


def test_long_targets_put_their_idea_past_the_read_limit(suite):
    """The padded targets exist to test map-reduce: their own paragraph must start
    beyond what a truncating reader would see."""
    from enqueue import config

    long_notes = [n for n in suite["notes"] if n.get("pad_with")]
    assert len(long_notes) >= 2
    for n in long_notes:
        full = xd.note_body(n)
        assert full.index(n["body"].strip()[:40]) > config.FACET_INPUT_CHARS * 2
