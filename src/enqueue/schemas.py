"""The contracts for every model call. Transcribed from docs/CURATION.md.

The validators are the product's quality floor, not defensive plumbing. Instructor
re-prompts on a validation error, so a failing validator is the system working.

Do not soften one because a model keeps failing it. Report it instead.
"""

from __future__ import annotations

import re
from enum import IntEnum

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


class Answer(BaseModel):
    """One turn of a chat, answered out of the collection.

    The failure this guards against is the answer that reads as though it came from
    the library and did not. A model that knows the subject will happily answer from
    what it already knows, cite whatever it was shown, and produce something fluent,
    correct, and completely unconnected to anything the person saved. That is the
    worst possible output here: it is indistinguishable from the good case and it
    quietly makes the collection irrelevant.

    So `grounded` is a claim the model has to make, and the citations have to back it.

    A grounded claim the model forgets to cite is salvaged, not rejected: the
    passages actually fed to it stand in for the citations, and only when there is
    nothing fed to point at does the claim downgrade to ungrounded (FIX.1).
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
            # FIX.1: a correct grounded answer the model forgot to cite is not a
            # failed turn. Backfill the passages that were actually fed to it; only
            # when there is nothing fed to point at do we downgrade the claim to
            # ungrounded and keep the answer rather than nuking a correct one.
            if offered:
                self.cited = sorted(offered)
            else:
                self.grounded = False
        if not self.grounded and self.cited:
            raise ValueError(
                "grounded is false but artifacts are cited; if they carried the answer, "
                "grounded is true"
            )
        return self


class Standalone(BaseModel):
    """A follow-up restated so it can be searched for without the conversation."""

    question: str = Field(min_length=1, description="The latest message as one question.")
    claims: list[str] = Field(
        default_factory=list, description="2 to 4 general claims the question is after."
    )


class SettingsAnswer(BaseModel):
    """An answer to a question about the app's settings (setup.answer)."""

    answer: str = Field(min_length=1, description="Two to four plain sentences.")
    guide: str | None = Field(
        default=None, description="The id of the one guide that covers it, or null."
    )


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

            # Found in the wild: "NotesNotFetched", "CollectionDump". A concatenated
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
