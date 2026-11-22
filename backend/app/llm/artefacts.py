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

The model also echoes the system prompt's *wording* about those markers, for
example a notable point reading "The document contains untrusted data and does
not contain instructions to the AI system" (live run, DECISIONS D-080). Such a
statement is about the pipeline, not the document, so it is dropped too: a list
item (string or object) with any string that refers to the system's own
instructions is removed whole, and in a single text field only the offending
sentence is removed. The phrases are narrow on purpose. "contains instructions
to the AI" (a fair description of an injection attempt) is kept; only the
negated form, which only an echo of our prompt produces, is dropped.
"""

import re
from collections.abc import Callable
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

# Wording from our own system prompt and boundary markers (app/llm/prompts/system.md,
# app.security.boundary). Checked BEFORE the markers are stripped, so the marker
# names themselves still match.
_SELF_REFERENCE = re.compile(
    r"\buntrusted\s+(?:data|content|text|input)\b"
    r"|\b(?:no|not\s+contain|does\s*n[o']t\s+contain|without|nor)\s+(?:any\s+)?"
    r"instructions?\s+(?:to|for|directed\s+at|aimed\s+at)\s+(?:the\s+|an\s+)?AI\b"
    # Prose about the markers. A literal copied marker ("<<<UNTRUSTED_CONTENT_BEGIN
    # id=…>>> The light was green.") is NOT matched: _MARKERS strips it and keeps the text.
    r"|\bUNTRUSTED_CONTENT(?:_BEGIN|_END)?\s+(?:and\s+\w+\s+)?markers?\b"
    r"|\b(?:boundary|content)\s+(?:markers?|tokens?|ids?)\b"
    r"|\bmarkers?\s+with\s+id=",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")


def refers_to_system(text: str) -> bool:
    """True if ``text`` talks about the pipeline's own instructions or markers."""
    return bool(_SELF_REFERENCE.search(text))


def _drop_self_reference_sentences(text: str) -> str:
    """Remove only the sentences of ``text`` that refer to the system's instructions."""
    if not refers_to_system(text):
        return text
    kept = (m.group(0).strip() for m in _SENTENCE.finditer(text))
    return " ".join(s for s in kept if s and not refers_to_system(s))


def _any_string(value: Any, test: Callable[[str], bool]) -> bool:
    """True if ``test`` holds for any string nested anywhere in ``value``."""
    if isinstance(value, str):
        return test(value)
    if isinstance(value, dict):
        return any(_any_string(v, test) for v in value.values())
    if isinstance(value, list):
        return any(_any_string(v, test) for v in value)
    return False


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
    """Recursively clean every string; drop strings that become empty from lists.

    List items (strings or objects) that refer to the system's own instructions are
    dropped whole; in other strings only the offending sentences are removed.
    """
    if isinstance(value, str):
        return strip_markers(_drop_self_reference_sentences(value))
    if isinstance(value, dict):
        return {k: strip_markers_in(v) for k, v in value.items()}
    if isinstance(value, list):
        items = [strip_markers_in(v) for v in value if not _any_string(v, refers_to_system)]
        return [v for v in items if not (isinstance(v, str) and not v.strip())]
    return value
