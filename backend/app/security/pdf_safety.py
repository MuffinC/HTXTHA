"""Detection of active content inside a PDF.

"Active content" is anything that can execute or launch something when a PDF
is opened in a viewer: JavaScript, launch actions and embedded files. Our
pipeline never executes any of it, but the analyst may later open the original
file, so the policy (``ACTIVE_CONTENT_POLICY``) is to reject such files by
default or, if set to ``warn``, accept them with a visible warning.

Approach: walk every object in the cross-reference table and look for the
relevant PDF keys in each object's *dictionary* (not in stream data, so text
that merely mentions "/JS" in page content does not trigger a false positive).
"""

import re
from dataclasses import dataclass

import pymupdf

# PDF name tokens that indicate active content. ``\b`` stops "/JS" matching "/JSON".
#   /JS, /JavaScript  - JavaScript actions or the document-level JavaScript name tree
#   /Launch           - launch an external application or file
#   /EmbeddedFile(s)  - file attachments (could carry executables)
# A /OpenAction is only dangerous when it points at one of the above (for example
# a JavaScript action). A plain "go to page 1" OpenAction is benign and is not flagged.
_ACTIVE_KEYS: dict[str, re.Pattern[str]] = {
    "javascript": re.compile(r"/(?:JS|JavaScript)\b"),
    "launch_action": re.compile(r"/Launch\b"),
    "embedded_file": re.compile(r"/EmbeddedFiles?\b"),
}


@dataclass(frozen=True)
class ActiveContentFinding:
    """One kind of active content found in the document."""

    kind: str  # "javascript" | "launch_action" | "embedded_file"
    xref: int  # first PDF object where it was found (for diagnostics)


def find_active_content(doc: pymupdf.Document) -> list[ActiveContentFinding]:
    """Return one finding per kind of active content present in ``doc``.

    Args:
        doc: An open, decrypted PDF document.

    Returns:
        Findings, at most one per kind, or an empty list if the file is clean.
    """
    found: dict[str, ActiveContentFinding] = {}

    if doc.embfile_count() > 0:
        found["embedded_file"] = ActiveContentFinding("embedded_file", 0)

    for xref in range(1, doc.xref_length()):
        try:
            # Dictionary source only; stream bodies are not included.
            obj = doc.xref_object(xref, compressed=True)
        except Exception:  # noqa: S112 - a damaged object must not stop the scan
            continue
        for kind, pattern in _ACTIVE_KEYS.items():
            if kind not in found and pattern.search(obj):
                found[kind] = ActiveContentFinding(kind, xref)
        if len(found) == len(_ACTIVE_KEYS):
            break

    return list(found.values())


def describe_findings(findings: list[ActiveContentFinding]) -> str:
    """Human-readable summary, e.g. ``"JavaScript, embedded file"``."""
    labels = {
        "javascript": "JavaScript",
        "launch_action": "a launch action",
        "embedded_file": "an embedded file",
    }
    return ", ".join(labels[f.kind] for f in findings)
