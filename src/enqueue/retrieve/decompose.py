"""Split a two-sided question into its sides: "compare my notes on X and Y".

One search for a comparison embeds both subjects into one vector and returns
whichever side dominates, so the answer quotes one side and guesses at the other.
Each side searched on its own gets its own passages. Plain rules, no model call:
the patterns people use for comparisons are few and fixed.
"""

from __future__ import annotations

import re

_LEAD = r"(?:please\s+)?(?:can\s+you\s+)?"
_NOTES = r"(?:(?:my\s+)?notes\s+(?:on|about)\s+|what\s+i\s+(?:saved|wrote)\s+(?:on|about)\s+)?"
_PATTERNS = [
    _LEAD
    + r"(?:compare|contrast)\s+"
    + _NOTES
    + r"(?P<a>.+?)\s+(?:and|with|to|vs\.?|versus|against)\s+"
    + _NOTES
    + r"(?P<b>.+)",
    r"(?:what(?:'s|\s+is|\s+are)\s+)?(?:the\s+)?differences?\s+between\s+"
    + _NOTES
    + r"(?P<a>.+?)\s+and\s+(?P<b>.+)",
    r"how\s+(?:does|do|is|are)\s+(?P<a>.+?)\s+(?:compare\s+(?:to|with)|differ\s+from)\s+(?P<b>.+)",
    r"(?P<a>.+?)\s+(?:vs\.?|versus)\s+(?P<b>.+)",
]
MAX_WORDS = 12


def parts(question: str) -> list[str]:
    """The two sides of a comparison, or [] when the question is not one."""
    q = " ".join(question.split()).rstrip("?.! ")
    for pattern in _PATTERNS:
        m = re.fullmatch(pattern, q, re.IGNORECASE)
        if not m:
            continue
        sides = [m.group("a").strip(" ,"), m.group("b").strip(" ,")]
        if all(1 <= len(s.split()) <= MAX_WORDS for s in sides):
            return sides
    return []
