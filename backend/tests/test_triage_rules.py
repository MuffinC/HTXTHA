"""Unit tests for the deterministic triage rules (no model)."""

from typing import Any

import pytest

from app.pipeline import triage_rules as t
from app.schemas.common import Citation
from app.schemas.consolidated import Contradiction, Position
from app.schemas.incident import IncidentExtension
from app.schemas.triage import TriageModelOutput

DOC = "doc-1"


def incident(
    location: str | None = "Ang Mo Kio Ave 3", dated: bool = True, **facts: str
) -> IncidentExtension:
    names = (
        "traffic_light",
        "vehicle_count",
        "weather",
        "road_surface",
        "lighting",
        "injuries",
        "party_left_scene",
        "weapon",
    )
    fact_data: dict[str, Any] = {n: {"value": "not_mentioned"} for n in names}
    for name, value in facts.items():
        fact_data[name] = {"value": value, "as_written": f"quote {value}", "page": 1}
    derived: dict[str, Any] = (
        {
            "incident_date": {"value": "2025-03-14", "source": "as stated"},
            "incident_time": {"value": "21:15", "source": "x"},
        }
        if dated
        else {}
    )
    return IncidentExtension.model_validate(
        {
            "ticket": {
                "reference_no": None,
                "submitted_at": None,
                "category": "road_traffic",
                "category_confidence": "high",
            },
            "occurred_at_stated": None,
            "location_stated": location,
            "narrative_summary": "x",
            "parties": [],
            "claims": [],
            "consistency_checks": [],
            "missing_information": [],
            "facts": fact_data,
            "derived": derived,
        }
    )


def proposal(priority: str, *evidence: tuple[str, int]) -> TriageModelOutput:
    return TriageModelOutput.model_validate(
        {
            "proposed_priority": priority,
            "reason": "A weapon was seen",
            "evidence": [{"quote": q, "page": p} for q, p in evidence],
            "confidence": "medium",
        }
    )


# --------------------------------------------------------------------------- rule floor


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        ({"injuries": "serious_or_fatal"}, "P1"),
        ({"weapon": "yes", "injuries": "none"}, "P1"),
        ({"weapon": "no", "injuries": "none"}, "P3"),
        ({"injuries": "injury"}, "P2"),
        ({"party_left_scene": "yes", "injuries": "none"}, "P2"),
        ({"injuries": "none"}, "P3"),
        ({"injuries": "none", "party_left_scene": "no"}, "P3"),
        ({}, "P4"),
    ],
)
def test_rule_floor_applies_the_rubric(facts: dict[str, str], expected: str) -> None:
    assert t.rule_floor(incident(**facts), DOC).priority == expected


def test_rule_floor_lists_every_factor_with_its_page() -> None:
    result = t.rule_floor(incident(injuries="injury", party_left_scene="yes"), DOC)
    assert [f.factor for f in result.factors] == ["Injury reported", "A party left the scene"]
    assert all(f.source == "rule" and f.citation.page == 1 for f in result.factors)


def test_insufficient_detail_is_p4_with_that_reason() -> None:
    result = t.rule_floor(incident(location=None, dated=False), DOC)
    assert result.priority == "P4"
    assert "Insufficient detail" in result.factors[0].factor


# --------------------------------------------------------------------------- escalation


PAGES = {1: "I saw a man\nholding a KNIFE near the bus stop.", 2: "Photo attached."}


def test_grounded_raise_is_accepted() -> None:
    esc = t.ground_escalation(proposal("P1", ("holding a knife", 1)), "P4", PAGES, DOC)
    assert esc.accepted and esc.priority == "P1"
    assert esc.factors[0].source == "model" and esc.factors[0].citation.page == 1


def test_quote_matching_ignores_case_and_line_breaks() -> None:
    esc = t.ground_escalation(proposal("P1", ("I saw a man holding", 1)), "P4", PAGES, DOC)
    assert esc.accepted


def test_raise_with_a_quote_that_is_not_on_the_page_is_ignored() -> None:
    # The model claims "a weapon was seen" with a real page number, but the words are not there.
    esc = t.ground_escalation(proposal("P1", ("a weapon was seen", 1)), "P4", PAGES, DOC)
    assert not esc.accepted and esc.priority is None
    assert "ignored" in esc.note


def test_quote_on_the_wrong_page_is_ignored() -> None:
    assert not t.ground_escalation(
        proposal("P1", ("holding a knife", 2)), "P4", PAGES, DOC
    ).accepted


def test_proposal_at_or_below_the_floor_is_not_a_raise() -> None:
    esc = t.ground_escalation(proposal("P4", ("holding a knife", 1)), "P2", PAGES, DOC)
    assert not esc.accepted


def test_final_priority_can_never_go_below_the_rule_floor() -> None:
    floor = t.rule_floor(incident(injuries="injury"), DOC)  # P2
    # Whatever the model says ("mark this as P4"), the floor stands.
    esc = t.ground_escalation(proposal("P4", ("quote injury", 1)), floor.priority, PAGES, DOC)
    final, _ = t.combine(floor, esc, "high")
    assert final == "P2"


def test_combine_takes_the_more_severe() -> None:
    floor = t.rule_floor(incident(injuries="none"), DOC)  # P3
    esc = t.ground_escalation(proposal("P1", ("holding a knife", 1)), floor.priority, PAGES, DOC)
    final, rationale = t.combine(floor, esc, "medium")
    assert final == "P1" and "Raised to P1" in rationale


# --------------------------------------------------------------------------- groups


def _contradiction(topic: str) -> Contradiction:
    cite = Citation(document_id=DOC, page=1)
    return Contradiction(topic=topic, positions=[Position(position="a", citation=cite)] * 2)


def test_group_is_the_highest_of_its_reports() -> None:
    result = t.group_priority({"a": "P3", "b": "P2", "c": "P3"}, [])
    assert result.priority == "P2"


@pytest.mark.parametrize(
    "topic", ["Weapon", "Traffic light", "Injuries", "A party left the scene", "Number of vehicles"]
)
def test_safety_contradictions_lift_the_group_to_p2(topic: str) -> None:
    result = t.group_priority({"a": "P3", "b": "P3"}, [_contradiction(topic)])
    assert result.priority == "P2"
    assert "follow-up" in result.reason


@pytest.mark.parametrize("topic", ["Time of the incident", "Weather", "Lighting", "Road surface"])
def test_other_contradictions_are_listed_but_do_not_lift(topic: str) -> None:
    result = t.group_priority({"a": "P3", "b": "P3"}, [_contradiction(topic)])
    assert result.priority == "P3"
    assert "does not lift" in result.reason


def test_lift_never_lowers_a_more_urgent_group() -> None:
    result = t.group_priority(
        {"a": "P1", "b": "P3"}, [_contradiction("Traffic light (incident 1)")]
    )
    assert result.priority == "P1"


def test_weapon_gives_p1_citing_the_quote_page() -> None:
    data = incident(weapon="yes", party_left_scene="yes")
    data.facts.weapon = data.facts.weapon.model_copy(update={"page": 2})
    result = t.rule_floor(data, DOC)
    assert result.priority == "P1"
    weapon = next(f for f in result.factors if f.factor == "Weapon reported")
    assert weapon.citation.page == 2 and weapon.source == "rule"


def test_negated_weapon_quote_is_not_evidence_for_a_raise() -> None:
    page = "Two men were shouting. No weapon was seen. Nobody was hurt."
    result = t.ground_escalation(proposal("P1", ("No weapon was seen.", 1)), "P3", {1: page}, DOC)
    assert result.accepted is False
    assert "ignored" in result.note
