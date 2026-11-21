"""Unit tests for the deterministic incident rules (no model involved)."""

from datetime import date, time
from typing import Any

import pytest

from app.pipeline import incident_rules as r
from app.schemas.incident import IncidentExtractionOutput, IncidentFacts, SceneObservation

# --------------------------------------------------------------------------- helpers


def facts(**overrides: Any) -> IncidentFacts:
    """Facts with every field not mentioned, except the given (value, quote, page) overrides."""
    base: dict[str, Any] = {
        name: {"value": "not_mentioned"}
        for name in (
            "traffic_light",
            "vehicle_count",
            "weather",
            "road_surface",
            "lighting",
            "injuries",
            "party_left_scene",
        )
    }
    for name, value in overrides.items():
        base[name] = {"value": value, "as_written": f"quote for {value}", "page": 1}
    return IncidentFacts.model_validate(base)


def extraction(**overrides: Any) -> IncidentExtractionOutput:
    base: dict[str, Any] = {
        "reference_no": "TST-1",
        "submitted_at": "14 March 2025, 21:52",
        "occurred_date": "14 March 2025",
        "occurred_time": "about 9.15pm",
        "location": "Junction of Ang Mo Kio Ave 3 and Ave 8",
        "category": "road_traffic",
        "category_confidence": "high",
        "narrative_summary": "Two cars collided.",
        "parties": [],
        "facts": facts().model_dump(),
        "other_claims": [],
        "missing_information": [],
    }
    return IncidentExtractionOutput.model_validate(base | overrides)


def scene(**overrides: Any) -> SceneObservation:
    base: dict[str, Any] = {
        "lighting": "unclear",
        "weather": "unclear",
        "road_surface": "unclear",
        "vehicles_visible": "unclear",
        "traffic_signal": "not_visible",
    }
    return SceneObservation.model_validate(base | overrides)


def ticket(label: str, **kw: Any) -> r.TicketForComparison:
    defaults: dict[str, Any] = {
        "document_id": f"id-{label}",
        "label": label,
        "category": "road_traffic",
        "location": "Ang Mo Kio Ave 3 and Ave 8",
        "incident_date": date(2025, 3, 14),
        "incident_time": time(21, 15),
        "time_as_written": "9.15pm",
        "facts": facts(),
    }
    return r.TicketForComparison(**(defaults | kw))


# --------------------------------------------------------------------------- times


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("21:15", time(21, 15)),
        ("about 9.15pm", time(21, 15)),
        ("around 9:30 p.m.", time(21, 30)),
        ("at about 9.20pm", time(21, 20)),
        ("9 pm", time(21, 0)),
        ("12.05am", time(0, 5)),
        ("12:30 pm", time(12, 30)),
        ("2130hrs", time(21, 30)),
        ("last night around 21:30", time(21, 30)),
        ("midnight", time(0, 0)),
        ("noon", time(12, 0)),
    ],
)
def test_parse_time(text: str, expected: time) -> None:
    assert r.parse_time(text) == expected


@pytest.mark.parametrize("text", [None, "", "last night", "14.03.2025", "Ave 3", "13 pm"])
def test_parse_time_rejects_non_times(text: str | None) -> None:
    assert r.parse_time(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("14 March 2025", date(2025, 3, 14)),
        ("14th Mar 2025", date(2025, 3, 14)),
        ("March 14, 2025", date(2025, 3, 14)),
        ("14/03/2025", date(2025, 3, 14)),  # day-first, Singapore usage
        ("14.03.25", date(2025, 3, 14)),
        ("2025-03-14", date(2025, 3, 14)),
        ("about 9 pm on 14 March 2025", date(2025, 3, 14)),  # first number+word is not a date
    ],
)
def test_parse_date(text: str, expected: date) -> None:
    assert r.parse_date(text) == expected


def test_parse_date_uses_default_year_and_rejects_impossible_dates() -> None:
    assert r.parse_date("14 Mar", default_year=2025) == date(2025, 3, 14)
    assert r.parse_date("14 Mar") is None
    assert r.parse_date("31/02/2025") is None


def test_derive_absolute_date_time_and_expected_lighting() -> None:
    derived = r.derive_facts(extraction())
    assert derived.incident_date and derived.incident_date.value == "2025-03-14"
    assert derived.incident_time and derived.incident_time.value == "21:15"
    assert derived.expected_lighting and derived.expected_lighting.value == "night"


def test_derive_relative_date_from_submission() -> None:
    derived = r.derive_facts(
        extraction(
            submitted_at="15 March 2025, 08:05",
            occurred_date=None,
            occurred_time="last night around 21:30",
        )
    )
    assert derived.incident_date and derived.incident_date.value == "2025-03-14"
    assert "last night" in derived.incident_date.source
    assert "15 Mar 2025" in derived.incident_date.source


def test_unresolvable_date_stays_unknown() -> None:
    derived = r.derive_facts(extraction(occurred_date="the other day", occurred_time=None))
    assert derived.incident_date is None and derived.incident_time is None


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        (time(12, 0), "daylight"),
        (time(7, 0), "dusk_or_dawn"),
        (time(19, 10), "dusk_or_dawn"),
        (time(21, 15), "night"),
        (time(5, 0), "night"),
    ],
)
def test_expected_lighting(at: time, expected: str) -> None:
    assert r.expected_lighting(at) == expected


# --------------------------------------------------------------------------- locations


def test_location_normalisation_expands_and_drops_filler() -> None:
    loc = r.normalise_location("Junction of AMK Ave 3 and Ave 8, near the hawker centre")
    assert loc is not None
    assert loc.tokens == {"ang", "mo", "kio", "avenue", "3", "8", "hawker", "centre"}


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("Junction of Ang Mo Kio Ave 3 and Ave 8", "AMK Avenue 3 / Avenue 8 junction", "strong"),
        ("Ang Mo Kio Ave 8, junction with Ave 3", "Ang Mo Kio Avenue 3 & Avenue 8", "strong"),
        ("Blk 123 Toa Payoh 310123", "Toa Payoh Lor 1, S(310123)", "strong"),  # postal code
        ("Ang Mo Kio Ave 3 near the MRT", "Ang Mo Kio Ave 3", "partial"),
        ("Upper Thomson Road near Lower Peirce", "Ang Mo Kio Ave 3 and Ave 8", "none"),
        (None, "Ang Mo Kio Ave 3", "unknown"),
    ],
)
def test_match_locations(a: str | None, b: str, expected: str) -> None:
    assert r.match_locations(a, b)[0] == expected


# --------------------------------------------------------------------------- grouping


def test_three_tickets_of_one_incident_group_and_unrelated_one_stays_apart() -> None:
    t1 = ticket("D1")
    t2 = ticket("D2", location="AMK Avenue 3 / Avenue 8 junction", incident_time=time(21, 30))
    t3 = ticket("D3", location="Ang Mo Kio Ave 8, junction with Ave 3", incident_time=time(21, 20))
    t4 = ticket(
        "D4",
        location="Upper Thomson Road near Lower Peirce",
        incident_date=date(2025, 3, 17),
        incident_time=time(23, 0),
    )

    grouping = r.group_incidents([t1, t2, t3, t4])

    assert [sorted(g.document_ids) for g in grouping.same_incident] == [["id-D1", "id-D2", "id-D3"]]
    reason = grouping.same_incident[0].reason
    assert "same date (14 Mar 2025)" in reason and "within 60 min" in reason
    assert grouping.possibly_related == []


def test_times_outside_the_window_are_not_the_same_incident() -> None:
    grouping = r.group_incidents([ticket("D1"), ticket("D2", incident_time=time(22, 30))])
    assert grouping.same_incident == []


def test_missing_location_makes_a_pair_only_possibly_related() -> None:
    grouping = r.group_incidents([ticket("D1"), ticket("D2", location=None)])
    assert grouping.same_incident == []
    assert len(grouping.possibly_related) == 1
    assert "location is missing" in grouping.possibly_related[0].reason


def test_different_category_never_groups() -> None:
    grouping = r.group_incidents([ticket("D1"), ticket("D2", category="theft")])
    assert grouping.same_incident == [] and grouping.possibly_related == []


# --------------------------------------------------------------------------- across tickets


def test_contradictions_need_both_tickets_to_state_a_value() -> None:
    t1 = ticket("D1", facts=facts(traffic_light="green", vehicle_count="2", injuries="none"))
    t2 = ticket(
        "D2",
        incident_time=time(21, 30),
        facts=facts(traffic_light="red", vehicle_count="3", injuries="injury"),
    )
    t3 = ticket("D3", incident_time=time(21, 20), facts=facts(vehicle_count="2", injuries="injury"))

    contradictions, agreements = r.compare_group([t1, t2, t3])

    topics = {c.topic: c for c in contradictions}
    assert set(topics) == {
        "Time of the incident",
        "Traffic light",
        "Number of vehicles",
        "Injuries",
    }
    # D3 does not mention the light: only D1 and D2 take part, so absence is not a position.
    assert [p.position.split(":")[0] for p in topics["Traffic light"].positions] == ["D1", "D2"]
    assert agreements == []


def test_close_times_and_equal_values_are_agreements() -> None:
    t1 = ticket("D1", facts=facts(weather="rain"))
    t2 = ticket("D2", incident_time=time(21, 25), facts=facts(weather="rain"))

    contradictions, agreements = r.compare_group([t1, t2])

    assert contradictions == []
    assert {a.point.split(":")[0] for a in agreements} == {"Time of the incident", "Weather"}


def test_time_contradiction_is_strictly_beyond_the_tolerance() -> None:
    edge = ticket("D2", incident_time=time(21, 25))  # exactly 10 minutes
    beyond = ticket("D3", incident_time=time(21, 26))
    assert r.compare_group([ticket("D1"), edge])[0] == []
    assert r.compare_group([ticket("D1"), beyond])[0][0].topic == "Time of the incident"


def test_timeline_is_ordered_and_skips_undated_tickets() -> None:
    events = r.build_timeline(
        [
            ticket("D2", incident_time=time(21, 30)),
            ticket("D1"),
            ticket("D3", incident_date=None, incident_time=None),
        ]
    )
    assert [e.time for e in events] == ["14 Mar 2025 21:15", "14 Mar 2025 21:30"]


# --------------------------------------------------------------------------- narrative vs photo


def test_rain_at_night_against_a_dry_daylight_photo_is_inconsistent() -> None:
    f = facts(weather="rain", lighting="night_dark")
    derived = r.derive_facts(extraction(occurred_time="around 11pm"))
    photos = [
        r.PhotoScene(page=2, scene=scene(lighting="daylight", weather="clear", road_surface="dry"))
    ]

    checks, by_field = r.check_narrative_against_photos(f, derived, photos)

    results = {c.check.split(":")[0]: c.result for c in checks}
    assert results == {"Weather": "inconsistent", "Lighting": "inconsistent"}
    assert by_field["weather"][0] == "inconsistent"
    assert all(2 in c.pages for c in checks)


def test_lighting_falls_back_to_the_stated_time() -> None:
    derived = r.derive_facts(extraction(occurred_time="9.15pm"))
    photos = [r.PhotoScene(page=2, scene=scene(lighting="night_street_lit"))]
    checks, _ = r.check_narrative_against_photos(facts(), derived, photos)
    assert [(c.check, c.result) for c in checks] == [("Lighting: narrative vs photo", "consistent")]
    assert "expected at the stated time" in checks[0].details


def test_unclear_photo_fields_give_unclear_results() -> None:
    f = facts(weather="clear", road_surface="dry")
    checks, _ = r.check_narrative_against_photos(
        f, r.derive_facts(extraction(occurred_time=None)), [r.PhotoScene(page=2, scene=scene())]
    )
    assert {c.result for c in checks} == {"unclear"}


def test_no_photos_means_no_checks() -> None:
    checks, by_field = r.check_narrative_against_photos(
        facts(weather="rain"), r.derive_facts(extraction()), []
    )
    assert checks == [] and by_field == {}


def test_visible_signal_and_timestamp_are_checked() -> None:
    f = facts(traffic_light="green")
    derived = r.derive_facts(extraction(occurred_time="21:15"))
    photos = [
        r.PhotoScene(
            page=2,
            scene=scene(
                traffic_signal="red",
                timestamp_visible="14/03/2025 21:16",
                lighting="night_street_lit",
            ),
        )
    ]
    results = {
        c.check.split(":")[0]: c.result
        for c in r.check_narrative_against_photos(f, derived, photos)[0]
    }
    assert results["Traffic light"] == "inconsistent"
    assert results["Time"] == "consistent"


def test_vehicle_count_is_never_checked_against_a_photo() -> None:
    f = facts(vehicle_count="3")
    photos = [r.PhotoScene(page=2, scene=scene(vehicles_visible="1"))]
    checks, _ = r.check_narrative_against_photos(
        f, r.derive_facts(extraction(occurred_time=None)), photos
    )
    assert checks == []


# --------------------------------------------------------------------------- claims and gaps


def test_claims_take_corroboration_from_the_photo_checks() -> None:
    ex = extraction(
        facts=facts(weather="rain", vehicle_count="1").model_dump(),
        other_claims=[{"claim": "The driver was speeding.", "page": 1}],
    )
    claims = r.build_claims(
        ex, {"weather": ("inconsistent", "photo shows a dry road")}, has_photo=True
    )

    by_text = {c.claim.split(" (")[0]: c for c in claims}
    assert by_text["Weather: rain"].corroboration == "contradicted"
    assert by_text["Number of vehicles: 1"].corroboration == "not_verifiable"
    assert by_text["The driver was speeding."].note.startswith("Free-text claim")


def test_claims_without_photo_say_so() -> None:
    claims = r.build_claims(
        extraction(facts=facts(weather="rain").model_dump()), {}, has_photo=False
    )
    assert claims[0].note == "No photo attached."


def test_missing_information_by_rule_merged_with_model_list() -> None:
    ex = extraction(
        occurred_time=None,
        location=" ",
        missing_information=["Location not stated.", "Witness contact."],
    )
    gaps = r.missing_information(ex, r.derive_facts(ex), has_photo=False)
    assert "Time of the incident not stated (or not recognisable)." in gaps
    assert "Number of vehicles involved not stated." in gaps
    assert "No photo attached, so the account cannot be checked against images." in gaps
    assert gaps.count("Location not stated.") == 1  # deduplicated
    assert gaps[-1] == "Witness contact."


@pytest.mark.parametrize(
    ("submitted", "occurred_time", "expected"),
    [
        ("14 March 2025, 21:40", "At about 21:15", "2025-03-14"),  # earlier the same day
        ("15 March 2025, 08:05", "around 21:30", "2025-03-14"),  # later than submission: day before
    ],
)
def test_date_assumed_from_submission_when_only_a_time_is_given(
    submitted: str, occurred_time: str, expected: str
) -> None:
    derived = r.derive_facts(
        extraction(submitted_at=submitted, occurred_date=None, occurred_time=occurred_time)
    )
    assert derived.incident_date is not None
    assert derived.incident_date.value == expected
    assert derived.incident_date.source.startswith("assumed:")


def test_stated_or_relative_dates_win_over_the_assumption() -> None:
    derived = r.derive_facts(
        extraction(submitted_at="15 March 2025, 08:05", occurred_date="13 March 2025")
    )
    assert derived.incident_date and derived.incident_date.source == "as stated"


# --------------------------------------------------------------------------- quote grounding


def _stated(name: str, value: str, quote: str | None) -> IncidentFacts:
    f = facts()
    setattr(
        f,
        name,
        getattr(f, name).model_copy(update={"value": value, "as_written": quote, "page": 1}),
    )
    return f


@pytest.mark.parametrize(
    ("name", "value", "quote"),
    [
        # Observed in live scorecard runs (D-058):
        ("lighting", "night_dark", "at about 9.20pm"),  # lighting inferred from the time
        ("road_surface", "dry", "The weather was dry"),  # weather quote used for the road
        ("lighting", "night_dark", "not mentioned"),  # a value with no real quote
        ("traffic_light", "green", None),
        ("injuries", "injury", "   "),
    ],
)
def test_ungrounded_values_are_downgraded(name: str, value: str, quote: str | None) -> None:
    grounded, downgraded = r.ground_facts(_stated(name, value, quote))
    assert downgraded == [name]
    assert getattr(grounded, name).value == "not_mentioned"
    assert getattr(grounded, name).as_written is None


@pytest.mark.parametrize(
    ("name", "value", "quote"),
    [
        ("lighting", "night_street_lit", "the street lights were on"),
        ("road_surface", "wet", "The road was wet from the rain earlier"),
        ("weather", "clear", "The weather was dry"),
        ("traffic_light", "red", "The traffic light had just turned red."),
        ("injuries", "injury", "My driver hurt his wrist."),
        ("party_left_scene", "yes", "The silver car drove off"),
        ("vehicle_count", "3", "a silver car hit my taxi, and a motorcycle"),  # no cue list
    ],
)
def test_grounded_values_are_kept(name: str, value: str, quote: str) -> None:
    grounded, downgraded = r.ground_facts(_stated(name, value, quote))
    assert downgraded == []
    assert getattr(grounded, name).value == value


def test_lighting_is_compared_coarsely_across_reports() -> None:
    # Live scorecard (D-058): "street lights were on" vs "last night" (dark) is not a conflict.
    lit = ticket("D1", facts=facts(lighting="night_street_lit"))
    dark = ticket("D2", facts=facts(lighting="night_dark"))
    day = ticket("D3", facts=facts(lighting="daylight"))

    assert [c.topic for c in r.compare_group([lit, dark])[0]] == []
    assert [c.topic for c in r.compare_group([lit, day])[0]] == ["Lighting"]
