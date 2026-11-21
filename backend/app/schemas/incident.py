"""Schemas for the incident profile (tickets and incident reports).

Design (DECISIONS D-057): **the model extracts, code compares.**

* ``SceneObservation``: required, closed-list fields the model must fill for
  every incident photo (each list has an "unclear" option). Asking for these
  in free text was not enough: the 4B model skipped them (ASSUMPTIONS L-006).
* ``IncidentFacts``: what the reporter states, normalised to closed lists
  (each with "not_mentioned"), with the exact quote and its page.
* ``IncidentExtractionOutput``: the extraction call's output (one model call per
  document).
* ``IncidentExtension``: the API schema from CLAUDE.md section 8. ``claims``,
  ``consistency_checks`` and most of ``missing_information`` are built by code
  in ``app.pipeline.incident_rules``. ``facts`` and ``derived`` are additions to
  the spec.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# Length bounds on model-filled fields. Ollama enforces maxLength/maxItems while
# decoding (verified on 0.40.16), so a repetition loop is cut off at the bound and
# the JSON still closes, instead of running to the token cap and leaving invalid
# output. One live run lost a report this way (DECISIONS D-060).
QUOTE_MAX = 200
SHORT_MAX = 80
TEXT_MAX = 300
SUMMARY_MAX = 800
LIST_MAX = 8

Quote = Annotated[str, Field(max_length=QUOTE_MAX)]

# --------------------------------------------------------------------------- closed lists

Lighting = Literal["daylight", "dusk_or_dawn", "night_street_lit", "night_dark"]
Weather = Literal["clear", "overcast", "rain", "fog"]
RoadSurface = Literal["dry", "wet", "flooded"]
VehicleType = Literal["car", "taxi", "motorcycle", "bus", "lorry", "van", "bicycle", "other"]
DamageLocation = Literal["front", "rear", "left_side", "right_side", "windscreen", "roof"]
VehicleCount = Literal["1", "2", "3", "4_or_more"]
SignalState = Literal["red", "amber", "green"]

IncidentCategory = Literal["road_traffic", "theft", "fire", "public_disturbance", "other"]
Confidence = Literal["low", "medium", "high"]

# --------------------------------------------------------------------------- photo scene


class SceneObservation(BaseModel):
    """Required scene fields for an incident photo. "unclear" is always allowed."""

    lighting: Literal[Lighting, "unclear"]
    weather: Literal[Weather, "unclear"]
    road_surface: Literal[RoadSurface, "unclear"]
    vehicles_visible: Literal["none", VehicleCount, "unclear"]
    vehicle_types: list[VehicleType] = Field(default_factory=list)
    damage_locations: list[Literal[DamageLocation, "none_visible", "unclear"]] = Field(
        default_factory=list
    )
    traffic_signal: Literal[SignalState, "not_visible", "unclear"]
    timestamp_visible: str | None = Field(
        default=None, description="Any date/time shown in the image, exactly as shown"
    )


# --------------------------------------------------------------------------- stated facts


class Stated[T](BaseModel):
    """One fact as the reporter states it: normalised value, exact quote, page."""

    value: T
    as_written: str | None = Field(
        default=None,
        max_length=QUOTE_MAX,
        description="The reporter's exact words, or null if not mentioned",
    )
    page: int | None = Field(default=None, description="1-based page of the quote")


# Named subclasses keep the JSON schema (sent to the model) and the TypeScript
# mirror readable, instead of pydantic's generated "Stated_Literal__red____..." names.
class TrafficLightFact(Stated[Literal[SignalState, "not_working", "not_mentioned"]]):
    pass


class VehicleCountFact(Stated[Literal[VehicleCount, "not_mentioned"]]):
    pass


class WeatherFact(Stated[Literal[Weather, "not_mentioned"]]):
    pass


class RoadSurfaceFact(Stated[Literal[RoadSurface, "not_mentioned"]]):
    pass


class LightingFact(Stated[Literal[Lighting, "not_mentioned"]]):
    pass


class InjuriesFact(Stated[Literal["none", "injury", "serious_or_fatal", "not_mentioned"]]):
    pass


class LeftSceneFact(Stated[Literal["yes", "no", "not_mentioned"]]):
    pass


class IncidentFacts(BaseModel):
    """Facts from the reporter's account. "not_mentioned" when the reporter does not say."""

    traffic_light: TrafficLightFact
    vehicle_count: VehicleCountFact
    weather: WeatherFact
    road_surface: RoadSurfaceFact
    lighting: LightingFact
    injuries: InjuriesFact
    party_left_scene: LeftSceneFact
    vehicle_types: list[VehicleType] = Field(default_factory=list, max_length=LIST_MAX)
    damage_locations: list[DamageLocation] = Field(default_factory=list, max_length=LIST_MAX)


class Party(BaseModel):
    """A person or vehicle involved, by role only (never by name)."""

    role: str = Field(max_length=SHORT_MAX)
    description: str = Field(max_length=TEXT_MAX)


class OtherClaim(BaseModel):
    claim: str = Field(max_length=TEXT_MAX)
    page: int


class IncidentExtractionOutput(BaseModel):
    """What the extraction model call produces for one incident document."""

    reference_no: str | None = Field(max_length=SHORT_MAX)
    submitted_at: str | None = Field(
        max_length=SHORT_MAX, description="Submission date/time, exactly as written"
    )
    occurred_date: str | None = Field(
        max_length=SHORT_MAX, description="Incident date, exactly as written"
    )
    occurred_time: str | None = Field(
        max_length=SHORT_MAX, description="Incident time, exactly as written"
    )
    location: str | None = Field(
        max_length=QUOTE_MAX, description="Incident location, exactly as written"
    )
    category: IncidentCategory
    category_confidence: Confidence
    narrative_summary: str = Field(max_length=SUMMARY_MAX)
    parties: list[Party] = Field(max_length=LIST_MAX)
    facts: IncidentFacts
    other_claims: list[OtherClaim] = Field(max_length=LIST_MAX)
    missing_information: list[Quote] = Field(max_length=LIST_MAX)


# --------------------------------------------------------------------------- API output


class TicketInfo(BaseModel):
    reference_no: str | None
    submitted_at: str | None
    category: IncidentCategory
    category_confidence: Confidence


class Claim(BaseModel):
    claim: str
    page: int | None
    corroboration: Literal["supported", "contradicted", "not_verifiable"]
    note: str


class ConsistencyCheck(BaseModel):
    check: str
    result: Literal["consistent", "inconsistent", "unclear"]
    details: str
    pages: list[int]


class DerivedValue(BaseModel):
    """A value computed by code, with how it was derived (shown to the analyst)."""

    value: str
    source: str = Field(description="e.g. \"from 'last night' and submission 15 Mar 2025\"")


class DerivedFacts(BaseModel):
    """Values code worked out from the extracted text (never guessed by the model)."""

    incident_date: DerivedValue | None = None  # ISO date, e.g. "2025-03-14"
    incident_time: DerivedValue | None = None  # 24-hour "HH:MM"
    expected_lighting: DerivedValue | None = None  # from the time of day (Singapore)


class IncidentExtension(BaseModel):
    """Incident-profile results for one document (CLAUDE.md section 8, plus two additions)."""

    ticket: TicketInfo
    occurred_at_stated: str | None
    location_stated: str | None
    narrative_summary: str
    parties: list[Party]
    claims: list[Claim]
    consistency_checks: list[ConsistencyCheck]
    missing_information: list[str]
    # Additions to the spec (DECISIONS D-057): normalised facts and code-derived values.
    facts: IncidentFacts
    derived: DerivedFacts
