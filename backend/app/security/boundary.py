"""Random-boundary delimiters around untrusted document content (CLAUDE.md section 7).

Document text is wrapped as::

    <<<UNTRUSTED_CONTENT_BEGIN id=3f9c1a7e5b2d4c60>>>
    ...document text...
    <<<UNTRUSTED_CONTENT_END id=3f9c1a7e5b2d4c60>>>

The identifier is 64 random bits, generated for every request. A document
cannot close the block early because its author cannot know the identifier in
advance, whereas a fixed delimiter (triple quotes, ``</document>``) could simply
be typed into the PDF. The system prompt tells the model that only markers with
the identifier from the request are real.

Used for document text in stage 3 (M3). Stage 2 sends no document text, only
the page image (DECISIONS D-027).
"""

import secrets

BEGIN_MARKER = "<<<UNTRUSTED_CONTENT_BEGIN id={boundary}>>>"
END_MARKER = "<<<UNTRUSTED_CONTENT_END id={boundary}>>>"

# 8 random bytes = 16 hex characters.
BOUNDARY_BYTES = 8


def new_boundary() -> str:
    """Return a fresh random boundary identifier."""
    return secrets.token_hex(BOUNDARY_BYTES)


def wrap_untrusted(content: str, boundary: str | None = None) -> tuple[str, str]:
    """Wrap ``content`` in begin/end markers with a random boundary.

    Args:
        content: Untrusted text (document text, or model output derived from it).
        boundary: Optional fixed boundary, for tests. If it occurs in the content,
            a new random one is drawn instead.

    Returns:
        ``(wrapped_text, boundary)``. Put the boundary in the instructions
        that come with the content ("the document is between the markers with id=...").
    """
    boundary = boundary or new_boundary()
    # Practically impossible for a random 64-bit value, but cheap to guarantee.
    while boundary in content:
        boundary = new_boundary()
    begin = BEGIN_MARKER.format(boundary=boundary)
    end = END_MARKER.format(boundary=boundary)
    return f"{begin}\n{content}\n{end}", boundary
