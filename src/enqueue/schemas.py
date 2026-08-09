"""The contracts for every model call. Transcribed from docs/CURATION.md.

The validators are the product's quality floor, not defensive plumbing. Instructor
re-prompts on a validation error, so a failing validator is the system working.

Do not soften one because a model keeps failing it. Report it instead.
"""

from __future__ import annotations

import re
from enum import IntEnum, StrEnum

from pydantic import BaseModel, Field, ValidationInfo, model_validator

HEDGES = {"may", "might", "perhaps", "arguably", "possibly", "seems", "suggests"}

# A level-2-or-above facet that talks *about* the artifact has not climbed, it has
# only paraphrased. "This writing demonstrates that adversity builds character" is a
# summary wearing a level-3 badge; "Character forms under sustained difficulty" is
# the claim itself, and only the second one can match a lens it shares no words with.
#
# Found by running the real generator: llama3.1:8b passed every other validator and
# opened all six of its level-2-plus facets this way.
SELF_REFERENCE = (
    "this writing",
    "this text",
    "this collection",
    "this artifact",
    "this document",
    "this note",
    "this piece",
    "this article",
    "the text",
    "the author",
    "the writing",
    "the writings",
    "the book",
    "the article",
    "it shows that",
    "it demonstrates",
    "it argues",
    "it illustrates",
    "the passage",
)


class AbstractionLevel(IntEnum):
    LITERAL = 0  # what it is
    SUBJECT = 1  # what it is about
    MECHANISM = 2  # what it demonstrates
    PRINCIPLE = 3  # what it is an instance of
    STANCE = 4  # what it argues for


class Facet(BaseModel):
    level: AbstractionLevel
    statement: str = Field(description="One complete sentence, 8 to 30 words.")

    @model_validator(mode="after")
    def check_statement(self, info: ValidationInfo):
        words = self.statement.split()
        if not 8 <= len(words) <= 30:
            raise ValueError(
                f"statement is {len(words)} words, must be 8 to 30: {self.statement!r}"
            )
        if not self.statement.rstrip().endswith("."):
            raise ValueError("statement must be one complete sentence ending in a period")

        # The climb check, part one. Above level 1, a facet that still names the
        # artifact's own subject has not generalised, whatever level it claims.
        if self.level >= AbstractionLevel.MECHANISM:
            banned = (info.context or {}).get("proper_nouns", set())
            hit = {w.strip(".,;:'\"()").lower() for w in words} & banned
            if hit:
                raise ValueError(
                    f"level {self.level.value} facet still names {sorted(hit)}; "
                    "restate it so it would apply to something unrelated"
                )

            # Part two. Talking about the artifact is paraphrase, not abstraction.
            lowered = self.statement.lower()
            for phrase in SELF_REFERENCE:
                if phrase in lowered:
                    raise ValueError(
                        f"level {self.level.value} facet refers to the artifact "
                        f"({phrase!r}); state the claim itself, as though it were true "
                        "independently of anything you were given"
                    )
        return self


class FacetSet(BaseModel):
    facets: list[Facet]

    @model_validator(mode="after")
    def check_set(self):
        if not 5 <= len(self.facets) <= 15:
            raise ValueError(f"{len(self.facets)} facets, must be 5 to 15")
        high = [f for f in self.facets if f.level >= AbstractionLevel.PRINCIPLE]
        if len(high) < 2:
            raise ValueError(
                f"only {len(high)} facets at level 3 or above, need at least 2; "
                "the set has not climbed"
            )
        return self


class Verdict(StrEnum):
    BELONGS = "belongs"
    ADJACENT = "adjacent"
    NO = "no"


class Judgment(BaseModel):
    artifact_id: str
    verdict: Verdict
    strength: int = Field(ge=1, le=5)
    matched_facet_id: str | None = None
    evidence: str = Field(default="", description="Verbatim span from the artifact.")
    placard: str = Field(default="", description="Why this is in this room. 8 to 25 words.")
    reason: str | None = Field(
        default=None, description="Why it does not belong, a few words; for rejected verdicts."
    )

    @model_validator(mode="after")
    def check(self, info: ValidationInfo):
        if self.verdict is Verdict.NO:
            return self

        source = (info.context or {}).get("artifact_text", "")
        if source and self.evidence not in source:
            raise ValueError("evidence is not a verbatim span of the artifact; quote exactly")

        words = self.placard.split()
        if not 8 <= len(words) <= 25:
            raise ValueError(f"placard is {len(words)} words, must be 8 to 25")
        hedged = {w.lower().strip(".,") for w in words} & HEDGES
        if hedged:
            raise ValueError(f"placard hedges with {sorted(hedged)}; state it or drop the artifact")

        # Same disease the facets had. A placard is wall text about the idea, not a
        # note about the filing decision. "This artifact belongs in the antifragility
        # theme because it describes X" is the machine narrating its own reasoning.
        lowered = self.placard.lower()
        for phrase in (*SELF_REFERENCE, "belongs in", "is in the room", "this is included"):
            if phrase in lowered:
                raise ValueError(
                    f"placard refers to the artifact or to the filing decision ({phrase!r}); "
                    "write the wall text a visitor would read, about the idea itself"
                )

        # A placard naming the lens is circular. "Routines promote antifragility" only
        # asserts membership; the room is already about antifragility. Say the thing
        # the artifact actually says and let the reader see why it hangs here.
        lens_words = {w for w in (info.context or {}).get("lens", "").lower().split() if len(w) > 3}
        placard_words = {w.strip(".,;:'\"()-").lower() for w in words}
        overlap = lens_words & placard_words
        if overlap:
            raise ValueError(
                f"placard uses the theme's own words {sorted(overlap)}; that only restates "
                "membership. Say what the artifact claims, not that it fits."
            )
        if not self.placard.rstrip().endswith((".", "!", "?")):
            raise ValueError("placard must be a complete sentence")
        return self


class Grouping(BaseModel):
    name: str
    artifact_ids: list[str] = Field(min_length=2)
    claim: str = Field(description="What these hold in common. One sentence.")

    @model_validator(mode="after")
    def check(self):
        # A grouping of one is a rename, not a grouping. The whole value of the
        # cluster is that several artifacts turn out to share something.
        if len(set(self.artifact_ids)) < 2:
            raise ValueError(
                f"grouping {self.name!r} holds one artifact; a grouping needs at least two "
                "that genuinely share something, or it should not exist"
            )
        return self


class Tension(BaseModel):
    between: tuple[str, str] = Field(description="Two grouping names.")
    claim: str = Field(description="What they disagree about. One sentence.")

    @model_validator(mode="after")
    def check(self):
        # A question is not a tension. It is the model filling a slot it could not
        # fill with a finding.
        if "?" in self.claim:
            raise ValueError(
                "tension claim is a question; state the disagreement as a claim, "
                "or return no tension"
            )
        return self


class Room(BaseModel):
    """The synthesized room: the ephemeral output of a curate run.

    Named after the artifact, not the thing that used to be saved from it. The
    room is returned by /curate and is never persisted; a saved grouping
    (saved_pivots) is the only persistent grouping concept.
    """

    suggested_name: str = Field(min_length=2)
    through_line: str = Field(description="One or two sentences. The finding.")
    groupings: list[Grouping] = Field(default_factory=list)
    tensions: list[Tension] = Field(default_factory=list, max_length=3)
    thin: bool = False
    thin_reason: str | None = None

    @model_validator(mode="after")
    def check(self, info: ValidationInfo):
        ctx = info.context or {}
        kept = set(ctx.get("kept_artifact_ids", []))
        lens = (ctx.get("lens") or "").strip().lower()

        if kept:
            for g in self.groupings:
                unknown = set(g.artifact_ids) - kept
                if unknown:
                    raise ValueError(
                        f"grouping {g.name!r} cites artifacts not in the room: {sorted(unknown)}"
                    )

        names = {g.name for g in self.groupings}
        seen_pairs = set()
        for t in self.tensions:
            unknown = set(t.between) - names
            if unknown:
                raise ValueError(f"tension cites groupings that do not exist: {sorted(unknown)}")
            if t.between[0] == t.between[1]:
                raise ValueError("a tension needs two different groupings")
            pair = frozenset(t.between)
            if pair in seen_pairs:
                raise ValueError(
                    f"two tensions between the same pair {sorted(pair)}; "
                    "state one disagreement per pair, or find a different pair"
                )
            seen_pairs.add(pair)

        # The report guard. A room that restates the question has told the
        # person what they already own instead of what they think.
        if lens and lens in self.through_line.strip().lower().rstrip("."):
            raise ValueError(
                "through_line restates the lens; say what the artifacts revealed, "
                "not what was asked"
            )
        if self.thin and not self.thin_reason:
            raise ValueError("a thin room must say why it is thin")
        return self


class Answer(BaseModel):
    """One turn of a chat, answered out of the collection.

    The failure this guards against is the answer that reads as though it came from
    the museum and did not. A model that knows the subject will happily answer from
    what it already knows, cite whatever it was shown, and produce something fluent,
    correct, and completely unconnected to anything the person saved. That is the
    worst possible output here: it is indistinguishable from the good case and it
    quietly makes the collection irrelevant.

    So `grounded` is a claim the model has to make, and the citations have to back it.
    """

    answer: str = Field(min_length=1)
    grounded: bool = Field(
        description="True only if the answer came from the artifacts you were shown."
    )
    cited: list[str] = Field(
        default_factory=list, description="Ids of the artifacts the answer actually used."
    )

    @model_validator(mode="after")
    def check(self, info: ValidationInfo):
        offered = set((info.context or {}).get("offered_artifact_ids", []))

        invented = set(self.cited) - offered if offered else set()
        if invented:
            raise ValueError(
                f"cited artifacts that were not provided: {sorted(invented)}; "
                "cite only from the numbered list you were given"
            )

        if self.grounded and not self.cited:
            raise ValueError(
                "grounded is true but nothing is cited; either name the artifacts the "
                "answer came from, or set grounded to false and say the collection "
                "does not hold this"
            )
        if not self.grounded and self.cited:
            raise ValueError(
                "grounded is false but artifacts are cited; if they carried the answer, "
                "grounded is true"
            )
        return self


class ChatTitle(BaseModel):
    """What a conversation gets called in the list of conversations."""

    title: str = Field(description="2 to 6 words naming the subject, not the exchange.")

    @model_validator(mode="after")
    def check(self):
        words = self.title.split()
        if not 2 <= len(words) <= 6:
            raise ValueError(f"title is {len(words)} words, must be 2 to 6: {self.title!r}")
        if self.title.rstrip().endswith(("?", ".", "!")):
            raise ValueError("a title is a name, not a sentence; drop the final punctuation")
        lowered = self.title.lower()
        # "Chat about X" and "Question regarding X" are the model naming the container
        # instead of the contents. Every one of them sorts identically in a sidebar.
        for phrase in (
            "chat about",
            "conversation about",
            "discussion of",
            "question about",
            "questions about",
            "inquiry into",
            "exploring",
        ):
            if lowered.startswith(phrase):
                raise ValueError(
                    f"title names the exchange ({phrase!r}) rather than the subject; "
                    "name what it is about"
                )
        return self


class ChatTopics(BaseModel):
    """The concepts a conversation turned out to circle.

    These are the same kind of object a lens is, which is the point: a topic drawn
    out of a conversation can be handed straight back to the curator to hang a room.
    A topic that only makes sense next to this transcript cannot do that, so the
    validators push toward standalone concepts.
    """

    topics: list[str] = Field(description="2 to 5 concepts, each 1 to 4 words.")

    @model_validator(mode="after")
    def check(self, info: ValidationInfo):
        if not 2 <= len(self.topics) <= 5:
            raise ValueError(f"{len(self.topics)} topics, must be 2 to 5")

        seen = set()
        for topic in self.topics:
            words = topic.split()
            if not 1 <= len(words) <= 4:
                raise ValueError(f"topic {topic!r} is {len(words)} words, must be 1 to 4")
            if topic.endswith(("?", ".")):
                raise ValueError(f"topic {topic!r} is a sentence; a topic is a noun phrase")

            # Found in the wild: "NotesNotFetched", "MuseumCollection". A concatenated
            # identifier passes the word count because it contains no spaces, and it is
            # not a phrase anyone would write on a wall. It also cannot be handed to
            # the curator as a lens, which is the only reason topics exist.
            if re.search(r"[a-z][A-Z]", topic):
                raise ValueError(
                    f"topic {topic!r} runs words together like an identifier; "
                    "write it as ordinary words with spaces"
                )
            if "_" in topic or "-" in topic.strip("-"):
                raise ValueError(
                    f"topic {topic!r} is punctuated like a slug; write it as ordinary words"
                )

            lowered = topic.lower()
            for phrase in SELF_REFERENCE:
                if phrase in lowered:
                    raise ValueError(
                        f"topic {topic!r} refers to the conversation or its material; "
                        "name the idea on its own"
                    )
            if lowered in seen:
                raise ValueError(f"topic {topic!r} appears twice")
            seen.add(lowered)
        return self


class AssistantRoute(BaseModel):
    """The router's one field: which skill a request should run.

    The model answers with a skill name from the registry's own list. The
    router clamps whatever comes back to the floor: a name outside the
    registry is `answer`, never an unknown skill.
    """

    skill: str


class LensExpansion(BaseModel):
    """Query-side move: bring the concept down toward how documents actually talk."""

    restatements: list[str] = Field(description="5 facet-style restatements of the lens.")
    passages: list[str] = Field(description="3 hypothetical passages exemplifying it.")

    @model_validator(mode="after")
    def check(self):
        if not 3 <= len(self.restatements) <= 8:
            raise ValueError(f"{len(self.restatements)} restatements, want 5")
        if not 2 <= len(self.passages) <= 5:
            raise ValueError(f"{len(self.passages)} passages, want 3")
        return self
