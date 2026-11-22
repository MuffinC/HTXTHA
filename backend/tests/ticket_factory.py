"""Synthetic incident tickets: realistic-looking e-report forms (fictional content).

Single source for ``scripts/generate_sample_tickets.py`` (files in
``sample_pdfs/tickets/``), the incident tests and the live scorecard.

The portal ("CityWatch e-Report") is fictional. Road names are real public
Singapore roads; the events, reporters and reference numbers are invented.
Contact numbers are the obvious placeholders 9123 4567 / 8123 4567 / 6123 4567
(never random numbers). Every page carries the "SYNTHETIC SAMPLE" footer.

Planted facts (what a perfect extraction gives, and what the rules should find)
are in ``PLANTED`` below and in ``sample_pdfs/README.md``.
"""

from dataclasses import dataclass, field

import pymupdf

from tests.pdf_factory import A4, FOOTER, REAL_PHOTO, _new_doc, _save

PORTAL = "CityWatch e-Report"
PORTAL_SUB = "Online public incident report (fictional portal - synthetic sample)"


@dataclass(frozen=True)
class Ticket:
    """One synthetic ticket: form fields, narrative and an optional photo."""

    key: str
    reference: str
    submitted: str
    category: str
    occurred_date: str
    occurred_time: str
    location: str
    reporter: str
    contact: str
    narrative: list[str]
    photo: bool = False
    # Expected normalised facts (a perfect extraction) and expected findings.
    expected: dict[str, str] = field(default_factory=dict)


T1 = Ticket(
    key="t1_witness",
    reference="CW-24-1001",
    submitted="14 March 2025, 21:52",
    category="Road traffic accident",
    occurred_date="14 March 2025",
    occurred_time="about 9.15pm",
    location="Junction of Ang Mo Kio Ave 3 and Ave 8",
    reporter="Witness (pedestrian)",
    contact="9123 4567",
    narrative=[
        "I was waiting to cross at the junction when two cars collided in the middle of the "
        "junction. The traffic light for traffic on Ave 3 was green at the time.",
        "A grey car turning right hit the rear door of a white car. The weather was dry and the "
        "street lights were on.",
        "Nobody appeared to be hurt and both drivers stayed to exchange details.",
    ],
    expected={
        "traffic_light": "green",
        "vehicle_count": "2",
        "weather": "clear",
        "lighting": "night_street_lit",
        "injuries": "none",
        "party_left_scene": "no",
    },
)

T2 = Ticket(
    key="t2_taxi_driver",
    reference="CW-24-1002",
    submitted="15 March 2025, 08:05",
    category="Road traffic accident",
    occurred_date="last night",
    occurred_time="around 21:30",
    location="AMK Avenue 3 / Avenue 8 junction",
    reporter="Driver (taxi)",
    contact="8123 4567",
    narrative=[
        "I am the taxi driver involved. Last night at around 21:30 my taxi was hit from behind "
        "at the junction while I was stopped. The traffic light had just turned red.",
        "Three vehicles were involved: a silver car hit my taxi, and a motorcycle behind it braked "
        "hard and fell. The road was wet from the rain earlier and it was still drizzling.",
        "The motorcyclist was holding his arm. The silver car drove off before the police arrived.",
    ],
    expected={
        "traffic_light": "red",
        "vehicle_count": "3",
        "weather": "rain",
        "road_surface": "wet",
        "injuries": "injury",
        "party_left_scene": "yes",
    },
)

T3 = Ticket(
    key="t3_passenger",
    reference="CW-24-1003",
    submitted="14 March 2025, 23:10",
    category="Road traffic accident",
    occurred_date="14 March 2025",
    occurred_time="at about 9.20pm",
    location="Ang Mo Kio Ave 8, junction with Ave 3",
    reporter="Passenger (in the taxi)",
    contact="6123 4567",
    narrative=[
        "I was a passenger in the taxi. At about 9.20pm we were stopped at the junction when a car "
        "crashed into the back of the taxi. I did not see the traffic light.",
        "Two vehicles were involved, the taxi and the car. There was a light drizzle.",
        "My driver hurt his wrist.",
    ],
    expected={
        "traffic_light": "not_mentioned",
        "vehicle_count": "2",
        "weather": "rain",
        "injuries": "injury",
    },
)

T4 = Ticket(
    key="t4_unrelated_tree",
    reference="CW-24-1004",
    submitted="18 March 2025, 09:30",
    category="Road traffic accident",
    occurred_date="17 March 2025",
    occurred_time="around 11pm",
    location="Upper Thomson Road near Lower Peirce Reservoir",
    reporter="Driver",
    contact="9123 4567",
    narrative=[
        "My car skidded and hit a roadside tree while I was driving home.",
        "It was raining heavily and it was very dark, so I could not see the bend. Nobody else "
        "was involved and I was not injured.",
        "A photo of my car is attached.",
    ],
    photo=True,
    expected={
        "vehicle_count": "1",
        "weather": "rain",
        "lighting": "night_dark",
        "injuries": "none",
    },
)

TICKETS: list[Ticket] = [T1, T2, T3, T4]

#: Triage demo (M7), kept out of TICKETS so the M6 scorecard set is unchanged. Since
#: D-068 the knife is an extracted, quote-grounded weapon fact, so the rule floor is P1.
WEAPON_TICKET = Ticket(
    key="t5_weapon_variant",
    reference="CW-24-1005",
    submitted="19 March 2025, 22:40",
    category="Public disturbance",
    occurred_date="19 March 2025",
    occurred_time="about 10.30pm",
    location="Hougang Avenue 1, near the bus interchange",
    reporter="Witness",
    contact="9123 4567",
    narrative=[
        "Two men were shouting at each other outside the coffee shop.",
        "One of them was holding a knife and waving it at the other man.",
        "Nobody was hurt as far as I could see. The man with the knife walked off towards the "
        "bus interchange.",
    ],
    expected={"injuries": "none", "weapon": "yes"},
)

#: What the rules should find with a perfect extraction (used by tests and the scorecard).
PLANTED = {
    "same_incident": {"t1_witness", "t2_taxi_driver", "t3_passenger"},
    "separate": {"t4_unrelated_tree"},
    # Contradiction topics expected within the same-incident group.
    "contradictions": {
        "Time of the incident",
        "Traffic light",
        "Number of vehicles",
        "Weather",
        "Injuries",
        "A party left the scene",
    },
    # T3 does not mention the light: it must never be a position in that contradiction.
    "absence_check": ("Traffic light", "t3_passenger"),
    # T4's narrative against its own photo (daylight, dry road).
    "inconsistent_checks": {"t4_unrelated_tree": {"Weather", "Lighting"}},
}


# --------------------------------------------------------------------------- rendering

_INK = (0.1, 0.13, 0.18)
_MUTED = (0.38, 0.42, 0.48)
_ACCENT = (0.06, 0.43, 0.45)
_RULE = (0.85, 0.87, 0.9)


def _header(page: pymupdf.Page, ticket: Ticket, title: str) -> None:
    page.draw_rect(pymupdf.Rect(0, 0, A4.width, 64), color=None, fill=_ACCENT)
    page.insert_text((40, 30), PORTAL, fontsize=15, fontname="hebo", color=(1, 1, 1))
    page.insert_text((40, 48), PORTAL_SUB, fontsize=8.5, color=(0.86, 0.94, 0.94))
    page.insert_text((40, 96), title, fontsize=12.5, fontname="hebo", color=_INK)
    page.insert_text(
        (A4.width - 200, 96), f"Reference No: {ticket.reference}", fontsize=9.5, color=_MUTED
    )


def _footer(page: pymupdf.Page, number: int) -> None:
    page.insert_text((40, A4.height - 28), FOOTER, fontsize=7, color=(0.45, 0.45, 0.45))
    page.insert_text(
        (A4.width - 80, A4.height - 28), f"Page {number} of 2", fontsize=7, color=(0.45, 0.45, 0.45)
    )


def _form(page: pymupdf.Page, ticket: Ticket) -> float:
    """Label/value rows; returns the y position after the table."""
    rows = [
        ("Reference No:", ticket.reference),
        ("Submitted on:", ticket.submitted),
        ("Category:", ticket.category),
        ("Date of incident:", ticket.occurred_date),
        ("Approx. time of incident:", ticket.occurred_time),
        ("Location:", ticket.location),
        ("Reporter:", ticket.reporter),
        ("Contact number:", ticket.contact),
        ("Attachments:", "Photo 1 (see page 2)" if ticket.photo else "None"),
    ]
    y = 116.0
    for i, (label, value) in enumerate(rows):
        if i % 2 == 0:
            page.draw_rect(
                pymupdf.Rect(40, y, A4.width - 40, y + 22), color=None, fill=(0.96, 0.97, 0.98)
            )
        page.insert_text((50, y + 15), label, fontsize=9.5, fontname="hebo", color=_MUTED)
        page.insert_text((200, y + 15), value, fontsize=10, color=_INK)
        y += 22
    page.draw_rect(pymupdf.Rect(40, 116, A4.width - 40, y), color=_RULE, width=0.8)
    return y


def ticket_pdf(ticket: Ticket) -> bytes:
    """Render one ticket as a two-page e-report printout."""
    doc = _new_doc()
    page = doc.new_page(width=A4.width, height=A4.height)
    _header(page, ticket, "Public incident report")
    y = _form(page, ticket) + 26
    page.insert_text(
        (40, y), "What happened (in the reporter's words)", fontsize=11, fontname="hebo", color=_INK
    )
    box = pymupdf.Rect(40, y + 10, A4.width - 40, y + 260)
    page.draw_rect(box, color=_RULE, width=0.8)
    page.insert_textbox(
        box + (10, 10, -10, -10),
        "\n\n".join(ticket.narrative),
        fontsize=10.5,
        color=_INK,
        lineheight=1.35,
    )
    page.insert_text(
        (40, box.y1 + 24),
        "Declaration: the reporter confirmed the information is true to the best of their "
        "knowledge.",
        fontsize=8.5,
        color=_MUTED,
    )
    _footer(page, 1)

    page2 = doc.new_page(width=A4.width, height=A4.height)
    _header(page2, ticket, "Attachments")
    if ticket.photo:
        page2.insert_text(
            (40, 130),
            "Photo 1 (submitted with the report)",
            fontsize=10,
            fontname="hebo",
            color=_INK,
        )
        page2.insert_image(
            pymupdf.Rect(40, 142, A4.width - 40, 142 + 386), filename=str(REAL_PHOTO)
        )
    else:
        page2.insert_text(
            (40, 130), "No photos were attached to this report.", fontsize=10, color=_MUTED
        )
    _footer(page2, 2)
    return _save(doc)
