"""Query-side half of the design: bring the lens down toward document space.

Ingest raises artifacts toward concepts by writing facets. This does the opposite,
turning a concept into the kind of sentences a document would actually contain. Both
have to fail for retrieval to miss.
"""

from __future__ import annotations

from ..prompts import LENS_EXPANSION
from ..providers.base import get_provider
from ..schemas import LensExpansion


def expand(lens: str) -> list[str]:
    """Return the lens plus its restatements and hypothetical passages.

    Falls back to the bare lens if the model fails, so a bad expansion degrades
    retrieval rather than breaking it.
    """
    try:
        result = get_provider().complete(
            system=LENS_EXPANSION,
            user=f"Lens: {lens}",
            response_model=LensExpansion,
        )
    except Exception:  # noqa: BLE001 - degrade, do not break
        return [lens]

    return [lens, *result.restatements, *result.passages]
