"""Remove the pipeline's own markers from model output.

The pipeline puts markers into prompts: ``[AI VISUAL DESCRIPTION - page N]``
blocks, ``<<<UNTRUSTED_CONTENT_BEGIN id=…>>>`` boundaries and ``--- Page N ---``
headings. A small model sometimes copies them into its answer, for example
listing "AI VISUAL DESCRIPTION" as an entity. They mean nothing to an analyst,
so every string in every model output is cleaned deterministically, in one
place (``app.llm.structured.parse_output``), before anything else sees it.

Strings that become empty are dropped from lists of strings. Structured list
items that end up empty (an entity with no name, say) are dropped by each
stage's own clean-up, which knows which field matters.
"""

import re
from typing import Any

_MARKERS = re.compile(
    r"\[/?\s*AI\s+VISUAL\s+DESCRIPTION[^\]]*\]"  # [AI VISUAL DESCRIPTION - page 2], [/AI ...]
    r"|\bAI[\s_-]+VISUAL[\s_-]+DESCRIPTIONS?\b"  # the bare phrase, e.g. as an entity name
    r"|<<<\s*/?\s*UNTRUSTED_CONTENT_(?:BEGIN|END)[^>]*>>>"  # boundary markers
    r"|\bUNTRUSTED_CONTENT_(?:BEGIN|END)\b(?:\s*id=[0-9a-f]+)?"
    r"|-{3}\s*Page\s+\d+\s*-{3}",  # --- Page 3 ---
    re.IGNORECASE,
)
_SPACES = re.compile(r"[ \t]{2,}")


def strip_markers(text: str) -> str:
    """Remove pipeline markers from ``text`` and tidy the leftover whitespace."""
    cleaned = _MARKERS.sub(" ", text)
    if cleaned == text:
        return text
    cleaned = _SPACES.sub(" ", cleaned)
    # Tidy punctuation left dangling by a removed marker, e.g. "( )" or a leading ":".
    cleaned = re.sub(r"\(\s*\)|\[\s*\]", "", cleaned)
    return cleaned.strip(" \t:;,-")


def strip_markers_in(value: Any) -> Any:
    """Recursively clean every string; drop strings that become empty from lists."""
    if isinstance(value, str):
        return strip_markers(value)
    if isinstance(value, dict):
        return {k: strip_markers_in(v) for k, v in value.items()}
    if isinstance(value, list):
        items = [strip_markers_in(v) for v in value]
        return [v for v in items if not (isinstance(v, str) and not v.strip())]
    return value
