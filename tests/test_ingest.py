"""Tests for the parts that run without a model or a vector store.

Every fixture here is inline. Tests that depended on an external corpus were deleted
with the importer that read it: a test that silently skips when a file is missing is
a test that reports green while checking nothing.
"""

from __future__ import annotations


import pytest

from enqueue.ingest.facets import proper_nouns
from enqueue.ingest.secrets import scan


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

    def test_realistic_snippet_is_caught_and_never_leaked(self):
        # Shaped after a real credential found in the first corpus. The value must
        # never reach the excerpt, because that excerpt is what gets displayed.
        text = (
            "import paramiko\n"
            'transport = paramiko.Transport("partners.sftp.example.com")\n'
            'transport.connect(username="minh", password="hunter2!")\n'
        )
        hits = scan(text)
        assert hits
        assert not any("hunter2!" in h.excerpt for h in hits)


class TestProperNouns:
    def test_finds_mid_sentence_names(self):
        nouns = proper_nouns("The words of Diogenes and Socrates matter.", "Discourses")
        assert "diogenes" in nouns and "socrates" in nouns

    def test_includes_title_words(self):
        assert "antifragility" in proper_nouns("body text", "Antifragility notes")

    def test_excludes_sentence_openers(self):
        assert "walking" not in proper_nouns("Walking makes you a better walker.", "x")


class TestFacetValidators:
    """The validators are the quality floor. Test that they reject, not that they pass."""

    def _facet(self, level, statement, nouns: frozenset[str] | set[str] = frozenset()):

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
