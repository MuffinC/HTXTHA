"""Heuristic detection of prompt-injection attempts in document text.

This is one layer of several (CLAUDE.md section 7). It does NOT block or strip
anything: flagged content is still analysed as data. It attaches an
``INJECTION_SUSPECTED`` warning with the page number, so the analyst knows the
document tried to steer the AI and can judge the output accordingly.

The main defences are elsewhere: a system prompt that marks document content
as untrusted, randomly-delimited content blocks, and schema-validated output.
A regex list cannot catch every phrasing, and that limitation is documented.

Before matching, text is normalised (Unicode NFKC, zero-width characters
removed, whitespace collapsed, lower-cased). This defeats cheap evasions such as
"Ignore​ all previous instructions" or full-width characters.
"""

import re
import unicodedata
from dataclasses import dataclass

from app.schemas.common import DocumentWarning, WarningCode

# Zero-width and bidirectional control characters used to hide or break up words.
_INVISIBLE_CHARS = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿­]")
_WHITESPACE = re.compile(r"\s+")

# (label, pattern). Patterns run on normalised, lower-cased text.
# Kept deliberately specific to avoid false positives on ordinary prose. For
# example, "act as" and "override" alone are too common in reports to flag.
INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ignore_instructions",
        re.compile(
            r"\b(?:ignore|disregard|forget|skip|bypass)\s+(?:all\s+|any\s+)?"
            r"(?:of\s+)?(?:the\s+|your\s+|my\s+)?"
            r"(?:previous|prior|above|earlier|preceding|foregoing|original|system|existing)?\s*"
            r"(?:instructions?|prompts?|rules|directions|guidelines|context)\b"
        ),
    ),
    (
        "disregard_generic",
        re.compile(r"\bdisregard\s+(?:all|everything|the\s+above|previous|prior)\b"),
    ),
    ("role_reassignment", re.compile(r"\byou\s+are\s+now\s+(?:a|an|in|the|my|no\s+longer)\b")),
    ("system_prompt", re.compile(r"\bsystem\s+prompt\b")),
    ("new_instructions", re.compile(r"\bnew\s+(?:instructions?|rules|directives?)\s*[:\-]")),
    (
        "reveal_instructions",
        re.compile(
            r"\b(?:reveal|print|show|repeat|output)\s+(?:your|the)\s+"
            r"(?:instructions|prompt|system\s+message|rules)\b"
        ),
    ),
    ("mode_switch", re.compile(r"\b(?:developer|maintenance|jailbreak|god|dan)\s+mode\b")),
    (
        "addressing_the_ai",
        re.compile(r"\b(?:note|message|instruction)s?\s+to\s+the\s+(?:ai|llm|model|assistant)\b"),
    ),
    (
        "chat_template_tokens",
        re.compile(
            r"<\|im_start\|>|<\|im_end\|>|\[/?inst\]|<<sys>>|^\s*#{2,}\s*system\b", re.MULTILINE
        ),
    ),
    (
        "output_override",
        re.compile(
            r"\b(?:respond|reply|answer)\s+only\s+with\b|\bdo\s+not\s+(?:analy[sz]e|summari[sz]e|report)\b"
        ),
    ),
]


@dataclass(frozen=True)
class InjectionMatch:
    """A suspicious phrase found on a page."""

    page: int | None
    label: str


def normalise(text: str) -> str:
    """Normalise text for matching: NFKC, strip invisible chars, collapse spaces, lower-case."""
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE_CHARS.sub("", text)
    return _WHITESPACE.sub(" ", text).strip().lower()


def scan_text(text: str, page: int | None = None) -> list[InjectionMatch]:
    """Return one match per pattern label that occurs in ``text``.

    Args:
        text: Untrusted text (document text, table text or, later, a vision transcription).
        page: 1-based page number the text came from, if known.

    Returns:
        Matches in pattern order; empty if nothing suspicious was found.
    """
    normalised = normalise(text)
    return [
        InjectionMatch(page=page, label=label)
        for label, pattern in INJECTION_PATTERNS
        if pattern.search(normalised)
    ]


def injection_warnings(
    pages: list[tuple[int, str]], subject: str = "This page contains text"
) -> list[DocumentWarning]:
    """Scan ``(page_number, text)`` pairs and build one warning per flagged page.

    The message names the matched *categories* only, never the matched text:
    warnings are shown in the UI and the matched text is attacker-controlled.

    Args:
        pages: ``(page_number, text)`` pairs to scan.
        subject: Start of the warning sentence, so the analyst can tell text-layer
            hits from text the model read out of an image.
    """
    warnings: list[DocumentWarning] = []
    for page, text in pages:
        matches = scan_text(text, page)
        if matches:
            labels = ", ".join(sorted({m.label for m in matches}))
            warnings.append(
                DocumentWarning(
                    code=WarningCode.INJECTION_SUSPECTED,
                    message=(
                        f"{subject} that looks like instructions to an AI "
                        f"system ({labels}). It was analysed as data only; review the "
                        "AI output for this document with extra care."
                    ),
                    page=page,
                )
            )
    return warnings
