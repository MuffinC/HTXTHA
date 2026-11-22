"""PII masking backstop: NRIC/FIN and phone numbers."""

import pytest

from app.security.pii import NRIC_MASK, PHONE_MASK, mask_pii, mask_pii_in


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("NRIC S1234567D was given.", f"NRIC {NRIC_MASK} was given."),
        ("FIN: G7654321K", f"FIN: {NRIC_MASK}"),
        ("lower case t0123456a too", f"lower case {NRIC_MASK} too"),
        ("Call 9123 4567 now", f"Call {PHONE_MASK} now"),
        ("Call 91234567.", f"Call {PHONE_MASK}."),
        ("Office 6123-4567", f"Office {PHONE_MASK}"),
        ("Mobile +65 8123 4567", f"Mobile {PHONE_MASK}"),
        ("Mobile +6591234567", f"Mobile {PHONE_MASK}"),
        ("UK +44 20 7946 0958", f"UK {PHONE_MASK}"),
    ],
)
def test_pii_masked(text: str, expected: str) -> None:
    assert mask_pii(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Occurred on 2025-03-14 at 21:15.",
        "Reference TST-0001, case 1234567.",
        "Damage estimated at $1,234,567.",
        "Serial 123456789012 recorded.",  # longer number: not partially masked
        "Vehicle count: 3, injuries: 0.",
        "A1234567B is not an NRIC prefix.",
        # Regression (D-053): a UUID whose hex contains a phone-like digit run.
        "a75d14ec-072e-4838-84d5-cb96609844e7",
        "ref ab91234567cd",
    ],
)
def test_non_pii_untouched(text: str) -> None:
    assert mask_pii(text) == text


def test_mask_pii_in_nested_structures() -> None:
    data = {
        "summary": "Reporter (S1234567D) can be reached on 9123 4567.",
        "parties": [{"role": "driver", "description": "phone 8765 4321"}],
        "page": 3,
        "flags": ("ok", None),
        "S1234567D": "keys are field names and stay unchanged",
    }
    masked = mask_pii_in(data)

    assert masked["summary"] == f"Reporter ({NRIC_MASK}) can be reached on {PHONE_MASK}."
    assert masked["parties"][0]["description"] == f"phone {PHONE_MASK}"
    assert masked["page"] == 3
    assert masked["flags"] == ("ok", None)
    assert "S1234567D" in masked


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[PHONE REDACTED]", True),
        (" [NRIC/FIN REDACTED], [PHONE REDACTED] ", True),
        ("Call [PHONE REDACTED]", False),
        ("Driver", False),
    ],
)
def test_is_only_mask(text: str, expected: bool) -> None:
    from app.security.pii import is_only_mask

    assert is_only_mask(text) is expected
