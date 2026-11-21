"""Checks on citations the model produced.

Schema validation proves a citation is *shaped* correctly (an integer page),
not that it points anywhere real. A small model sometimes cites page 7 of a
3-page document, or a document label that does not exist. Every citation is
checked after validation. Invalid ones are removed, counted in the logs, and
reported to the analyst as a ``CITATIONS_REMOVED`` warning (DECISIONS D-034),
because a citation that leads nowhere is worse than none (principle 3).
"""

import logging

from app.schemas.common import DocumentWarning, WarningCode

logger = logging.getLogger(__name__)


def is_valid_page(page: int, page_count: int) -> bool:
    """True if ``page`` is a real 1-based page of a ``page_count``-page document."""
    return 1 <= page <= page_count


def removed_citations_warning(removed: int, where: str) -> DocumentWarning | None:
    """Log the count and build the analyst-facing warning (``None`` if nothing was removed).

    Args:
        removed: Number of citations (or cited items) dropped.
        where: Short description for the message, e.g. "this document's analysis".
    """
    if not removed:
        return None
    logger.warning(
        "Removed invalid citations from model output",
        extra={"event": "citations_removed", "count": removed},
    )
    return DocumentWarning(
        code=WarningCode.CITATIONS_REMOVED,
        message=(
            f"{removed} citation(s) in {where} pointed to pages or documents that do not "
            "exist and were removed. Treat this AI output with extra care."
        ),
    )
