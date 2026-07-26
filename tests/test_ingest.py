"""Tests for the parts that run without a model or a vector store.

The corpus fixtures are the real Fabric export. If it is absent the corpus tests skip
rather than fail, since the export is not in the repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from enqueue.ingest.chunk import MERGE_FLOOR_WORDS, chunk_artifact
from enqueue.ingest.fabric import parse_fabric_html, plain_text
from enqueue.ingest.facets import proper_nouns
from enqueue.ingest.importer import classify_provenance
from enqueue.ingest.secrets import scan

EXPORT = Path.home() / "Downloads" / "Fabric Export 1784999815368"
needs_corpus = pytest.mark.skipif(not EXPORT.is_dir(), reason="Fabric export not present")


def _rows(blocks):
    """Turn ParsedBlocks into the dict shape chunk_artifact expects."""
    ids = {b.uuid: b.uuid for b in blocks}
    return [
        {
            "id": b.uuid,
            "parent_id": ids.get(b.parent_uuid) if b.parent_uuid else None,
            "ordinal": b.ordinal,
            "text": b.text,
        }
        for b in blocks
    ]


class TestFabricParser:
    def test_nesting_survives(self):
        html = """
        <ul><li data-uuid="a"><p>Claim one</p>
              <ul><li data-uuid="b"><p>Elaboration</p></li></ul></li>
            <li data-uuid="c"><p>Claim two</p></li></ul>
        """
        blocks = parse_fabric_html(html)
        assert [b.depth for b in blocks] == [0, 1, 0]
        assert blocks[1].parent_uuid == "a"
        assert blocks[2].parent_uuid is None

    def test_parent_text_excludes_children(self):
        html = "<ul><li><p>Parent</p><ul><li><p>Child</p></li></ul></li></ul>"
        blocks = parse_fabric_html(html)
        assert blocks[0].text == "Parent"

    def test_empty_paragraphs_are_dropped(self):
        assert parse_fabric_html("<p></p><p>  </p>") == []

    def test_code_survives_verbatim(self):
        html = "<pre><code>line one\nline two</code></pre>"
        assert "\n" in parse_fabric_html(html)[0].text

    @needs_corpus
    def test_epictetus_ground_truth(self):
        blocks = parse_fabric_html(
            (EXPORT / "books" / "Discourses_by_Epictetus.html").read_text(encoding="utf-8")
        )
        assert len(blocks) == 19
        assert sum(1 for b in blocks if b.depth == 0) == 8
        assert sum(1 for b in blocks if b.depth == 1) == 11
        assert all(b.created_at for b in blocks)

        boxer = next(b for b in blocks if "boxer" in b.text)
        assert boxer.depth == 0
        assert sum(1 for b in blocks if b.parent_uuid == boxer.uuid) == 3


class TestSecretScan:
    def test_detects_and_redacts(self):
        hits = scan('transport.connect(username="minh", password="hunter2!")')
        assert [h.kind for h in hits] == ["assignment"]
        assert "hunter2!" not in hits[0].excerpt
        assert "***" in hits[0].excerpt

    @pytest.mark.parametrize(
        "text,kind",
        [
            ("AKIAIOSFODNN7EXAMPLE", "aws_access_key_id"),
            ("-----BEGIN RSA PRIVATE KEY-----", "private_key"),
            ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345", "bearer_token"),
            ("ghp_abcdefghijklmnopqrstuvwxyz0123456789", "github_token"),
        ],
    )
    def test_shapes(self, text, kind):
        assert kind in {h.kind for h in scan(text)}

    def test_clean_text_is_clean(self):
        assert scan("The true man is revealed during difficult times.") == []

    @needs_corpus
    def test_corpus_credential_is_caught_and_never_leaked(self):
        text = plain_text(
            parse_fabric_html(
                (EXPORT / "snippets" / "sftp_command.html").read_text(encoding="utf-8")
            )
        )
        hits = scan(text)
        assert hits
        assert not any("testMinh" in h.excerpt for h in hits)


class TestChunking:
    def test_claim_with_children_is_one_unit(self):
        blocks = parse_fabric_html(
            "<ul><li><p>Claim</p><ul><li><p>Because</p></li><li><p>And</p></li></ul></li></ul>"
        )
        chunks = chunk_artifact("a", _rows(blocks))
        assert len(chunks) == 1
        assert chunks[0].chunker == "blocks-v1"
        assert "Because" in chunks[0].text

    def test_childless_paragraphs_merge(self):
        html = "".join(f"<p>{'word ' * 20}</p>" for _ in range(10))
        chunks = chunk_artifact("a", _rows(parse_fabric_html(html)))
        assert len(chunks) < 10
        assert all(c.chunker == "blocks-v1+merged" for c in chunks)
        assert all(len(c.text.split()) >= MERGE_FLOOR_WORDS * 0.5 for c in chunks[:-1])

    def test_claims_are_never_merged_into_paragraphs(self):
        html = "<p>loose one</p><ul><li><p>Claim</p><ul><li><p>Sub</p></li></ul></li></ul>"
        chunks = chunk_artifact("a", _rows(parse_fabric_html(html)))
        claim = [c for c in chunks if "Claim" in c.text]
        assert len(claim) == 1
        assert "loose one" not in claim[0].text


class TestProperNouns:
    def test_finds_mid_sentence_names(self):
        nouns = proper_nouns("The words of Diogenes and Socrates matter.", "Discourses")
        assert "diogenes" in nouns and "socrates" in nouns

    def test_includes_title_words(self):
        assert "antifragility" in proper_nouns("body text", "Antifragility notes")

    def test_excludes_sentence_openers(self):
        assert "walking" not in proper_nouns("Walking makes you a better walker.", "x")


class TestProvenance:
    def test_pasted_llm_output(self):
        text = "That's an excellent question. 🎯 Let's break it down. " + "word " * 900
        assert classify_provenance(text, []) == "pasted"

    def test_own_notes(self):
        assert classify_provenance("Death is a hobgoblin, a scary mask.", []) == "authored"


class TestFacetValidators:
    """The validators are the quality floor. Test that they reject, not that they pass."""

    def _facet(self, level, statement, nouns=frozenset()):
        from pydantic import ValidationError

        from enqueue.schemas import Facet

        return Facet.model_validate(
            {"level": level, "statement": statement}, context={"proper_nouns": set(nouns)}
        )

    def test_rejects_self_reference_above_level_1(self):
        import pytest

        with pytest.raises(Exception, match="refers to the artifact"):
            self._facet(3, "This writing demonstrates that adversity builds character over time.")

    def test_allows_self_reference_at_level_0(self):
        f = self._facet(0, "This text is a compilation of philosophical musings by an author.")
        assert f.level == 0

    def test_rejects_proper_noun_above_level_1(self):
        import pytest

        with pytest.raises(Exception, match="still names"):
            self._facet(
                3,
                "Epictetus argues that character forms under sustained difficulty and strain.",
                nouns={"epictetus"},
            )

    def test_accepts_a_real_climb(self):
        f = self._facet(3, "Character forms under sustained difficulty rather than under comfort.")
        assert f.level == 3

    def test_set_requires_two_high_facets(self):
        import pytest

        from enqueue.schemas import FacetSet

        low = [
            {"level": 1, "statement": "The book is about preparing for difficult circumstances."}
        ] * 5
        with pytest.raises(Exception, match="has not climbed"):
            FacetSet.model_validate({"facets": low})


class TestJudgmentValidators:
    """Every one of these was written after seeing a real model produce the bad case."""

    EV = "A lack of routine causes more problems than poor choices."
    CTX = {"artifact_text": EV, "lens": "antifragility"}

    def _judge(self, placard, **over):
        from enqueue.schemas import Judgment

        payload = {
            "artifact_id": "x",
            "verdict": "belongs",
            "strength": 4,
            "evidence": self.EV,
            "placard": placard,
            **over,
        }
        return Judgment.model_validate(payload, context=self.CTX)

    def test_rejects_paraphrased_evidence(self):
        import pytest

        with pytest.raises(Exception, match="verbatim"):
            self._judge(
                "A lack of routine costs more than bad decisions do here.",
                evidence="Routine matters a lot",
            )

    def test_rejects_filing_note_placard(self):
        import pytest

        with pytest.raises(Exception, match="filing decision|refers to the artifact"):
            self._judge(
                "This artifact belongs in the theme because it describes routine and habit."
            )

    def test_rejects_placard_using_the_lens_word(self):
        import pytest

        with pytest.raises(Exception, match="theme's own words"):
            self._judge(
                "Routines promote stability and therefore build genuine antifragility over time."
            )

    def test_rejects_hedged_placard(self):
        import pytest

        with pytest.raises(Exception, match="hedges"):
            self._judge("A lack of routine perhaps costs more than a run of bad decisions.")

    def test_accepts_real_wall_text(self):
        assert (
            self._judge("A lack of routine costs more than a run of bad decisions does.").strength
            == 4
        )

    def test_no_verdict_skips_every_check(self):
        assert self._judge("", verdict="no", evidence="").verdict.value == "no"


class TestExhibitValidators:
    def test_grouping_of_one_is_rejected(self):
        import pytest

        from enqueue.schemas import Grouping

        with pytest.raises(Exception):
            Grouping.model_validate({"name": "X", "artifact_ids": ["a"], "claim": "c"})

    def test_tension_may_not_be_a_question(self):
        import pytest

        from enqueue.schemas import Tension

        with pytest.raises(Exception, match="question"):
            Tension.model_validate({"between": ("A", "B"), "claim": "Does this imply something?"})

    def test_through_line_may_not_restate_the_lens(self):
        import pytest

        from enqueue.schemas import Exhibit

        with pytest.raises(Exception, match="restates the lens"):
            Exhibit.model_validate(
                {"suggested_name": "A room", "through_line": "antifragility."},
                context={"lens": "antifragility", "kept_artifact_ids": []},
            )

    def test_thin_room_must_say_why(self):
        import pytest

        from enqueue.schemas import Exhibit

        with pytest.raises(Exception, match="why it is thin"):
            Exhibit.model_validate(
                {"suggested_name": "A room", "through_line": "Something was found.", "thin": True},
                context={"lens": "x", "kept_artifact_ids": []},
            )
