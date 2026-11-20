"""Backstop masking of personal identifiers in model output.

The model is instructed not to transcribe identity numbers, phone numbers,
licence plates or faces (from M2). This module is a deterministic safety net
applied to outputs afterwards, so a model that ignores the instruction still
cannot surface these values in the UI.

Covered patterns:
  * Singapore NRIC / FIN: ``[STFGM]`` + 7 digits + check letter (e.g. S1234567D).
  * Phone numbers: Singapore 8-digit numbers starting 3/6/8/9 (optional +65 or
    65 prefix, optional space or hyphen after 4 digits), and international
    numbers written with a leading ``+``.

Trade-off: any 8-digit number starting with 3, 6, 8 or 9 is masked, even if it
is a reference number. We accept this because masking too much is safer than
leaking a phone number.
"""

import re
from typing import Any

NRIC_MASK = "[NRIC/FIN REDACTED]"
PHONE_MASK = "[PHONE REDACTED]"

# ASSUMPTION: lower-case NRIC/FIN is also masked (OCR and models do not always keep case).
_NRIC = re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE)

# Lookarounds instead of \b so "+65" at the start still anchors correctly,
# and digits that are part of a longer number are not partially masked.
_SG_PHONE = re.compile(r"(?<![\d+])(?:\+?65[\s-]?)?[3689]\d{3}[\s-]?\d{4}(?!\d)")
_INTL_PHONE = re.compile(r"(?<![\w+])\+\d{1,3}(?:[\s-]?\d){7,12}(?!\d)")


def mask_pii(text: str) -> str:
    """Replace NRIC/FIN and phone numbers in ``text`` with fixed placeholders."""
    text = _NRIC.sub(NRIC_MASK, text)
    text = _SG_PHONE.sub(PHONE_MASK, text)
    return _INTL_PHONE.sub(PHONE_MASK, text)


def mask_pii_in[T](value: T) -> T:
    """Recursively mask every string inside dicts, lists and tuples.

    Intended for ``model.model_dump()`` output before it is re-validated,
    stored or returned. Dict keys are left untouched (they are schema field names).
    """
    result: Any
    if isinstance(value, str):
        result = mask_pii(value)
    elif isinstance(value, dict):
        result = {k: mask_pii_in(v) for k, v in value.items()}
    elif isinstance(value, list):
        result = [mask_pii_in(v) for v in value]
    elif isinstance(value, tuple):
        result = tuple(mask_pii_in(v) for v in value)
    else:
        result = value
    return result
