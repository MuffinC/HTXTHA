"""Deterministic rules for the incident profile: the model extracts, code compares.

Everything here is a pure function of extracted values, so results are
repeatable and every finding has a stated reason (DECISIONS D-057):

* parsing times ("9.15pm", "2130hrs") and dates, including a small set of
  relative phrases ("last night") resolved against the submission date;
* the lighting expected at a given time of day in Singapore;
* location normalisation and matching (offline, no geocoding);
* same-incident grouping across tickets;
* contradictions and agreements across tickets in the same incident (both
  tickets must state a value: absence is never a contradiction);
* consistency checks between a ticket's narrative and its own photos;
* the spec's ``claims`` (with corroboration), missing information and timeline.

All tunable values are the named constants below.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from itertools import combinations
from typing import Literal

from app.schemas.common import Citation
from app.schemas.consolidated import (
    Agreement,
    Contradiction,
    DocumentGroup,
    Position,
    TimelineEvent,
)
from app.schemas.incident import (
    Claim,
    ConsistencyCheck,
    DerivedFacts,
    DerivedValue,
    IncidentExtractionOutput,
    IncidentFacts,
    SceneObservation,
)

# --------------------------------------------------------------------------- constants

#: Times further apart than this (minutes) are a contradiction between tickets.
CONTRADICTION_TIME_TOLERANCE_MIN = 10
#: Tickets can only be the same incident if their times are within this window (minutes).
SAME_INCIDENT_WINDOW_MIN = 60
#: Location token overlap (Jaccard) for a "partial" location match.
LOCATION_PARTIAL_JACCARD = 0.5
#: Approximate Singapore daylight (it varies by only ~30 minutes over the year).
DAYLIGHT_START, DAYLIGHT_END = time(7, 15), time(19, 0)
DAWN_START, DUSK_END = time(6, 45), time(19, 30)

FactField = Literal[
    "traffic_light",
    "vehicle_count",
    "weather",
    "road_surface",
    "lighting",
    "injuries",
    "party_left_scene",
    "weapon",
]

FIELD_LABELS: dict[str, str] = {
    "occurred_time": "Time of the incident",
    "traffic_light": "Traffic light",
    "vehicle_count": "Number of vehicles",
    "weather": "Weather",
    "road_surface": "Road surface",
    "lighting": "Lighting",
    "injuries": "Injuries",
    "party_left_scene": "A party left the scene",
    "weapon": "Weapon",
}

VALUE_LABELS: dict[str, str] = {
    "4_or_more": "4 or more",
    "not_working": "not working",
    "night_street_lit": "night (street lights on)",
    "night_dark": "night (dark)",
    "dusk_or_dawn": "dusk or dawn",
    "serious_or_fatal": "serious or fatal injury",
    "injury": "injury reported",
    "none": "none",
    "yes": "yes",
    "no": "no",
}

COMPARED_FIELDS: tuple[FactField, ...] = (
    "traffic_light",
    "vehicle_count",
    "weather",
    "road_surface",
    "lighting",
    "injuries",
    "party_left_scene",
    "weapon",
)


def label(value: str) -> str:
    """Human-readable form of a closed-list value."""
    return VALUE_LABELS.get(value, value.replace("_", " "))


# --------------------------------------------------------------------------- times and dates

# Not preceded by a digit or separator, and not followed by a digit or separator+digit,
# so the "14.03" inside the date "14.03.2025" is not read as a time.
_TIME_COLON = re.compile(
    r"(?<![\d./])(\d{1,2})[:.](\d{2})(?!\d|[./]\d)\s*(a\.?m\.?|p\.?m\.?)?", re.I
)
_TIME_AMPM = re.compile(r"\b(\d{1,2})\s*(a\.?m\.?|p\.?m\.?)(?![a-z])", re.I)
_TIME_HRS = re.compile(r"\b([01]\d|2[0-3])([0-5]\d)\s*(?:hrs?|hours|h)\b", re.I)
_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_DATE_DMY_WORDS = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?,?\s*(\d{4})?\b", re.I)
_DATE_MDY_WORDS = re.compile(r"\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?\b", re.I)
_DATE_NUMERIC = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})\b")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# Relative phrases resolved against the submission date: (pattern, days before submission).
_RELATIVE = [
    (re.compile(r"\blast night\b|\byesterday\b", re.I), 1),
    (
        re.compile(
            r"\btonight\b|\bthis (?:morning|afternoon|evening)\b|\b(?:earlier )?today\b", re.I
        ),
        0,
    ),
]


def parse_time(text: str | None) -> time | None:
    """First clock time in ``text`` ("21:15", "9.15pm", "9 pm", "2130hrs"), or None."""
    if not text:
        return None
    lowered = text.lower()
    if "midnight" in lowered:
        return time(0, 0)
    if re.search(r"\bnoon\b|\bmidday\b", lowered):
        return time(12, 0)
    for pattern in (_TIME_COLON, _TIME_HRS, _TIME_AMPM):
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groups()
        hour = int(groups[0])
        minute = int(groups[1]) if pattern is not _TIME_AMPM else 0
        meridiem = (
            groups[2] if pattern is _TIME_COLON else groups[1] if pattern is _TIME_AMPM else None
        )
        if meridiem:
            is_pm = meridiem.lower().startswith("p")
            if not 1 <= hour <= 12:
                continue
            hour = (hour % 12) + (12 if is_pm else 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour, minute)
    return None


def parse_date(text: str | None, default_year: int | None = None) -> date | None:
    """First calendar date in ``text``. Numeric dates are day-first (Singapore usage)."""
    if not text:
        return None
    if m := _DATE_ISO.search(text):
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))
    if m := _DATE_NUMERIC.search(text):
        year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        return _safe_date(year, int(m[2]), int(m[1]))
    # Try every match: "about 9 pm on 14 March" first matches "9 pm", which is no month.
    for m in _DATE_DMY_WORDS.finditer(text):
        month = _MONTHS.get(m[2].lower())
        year = int(m[3]) if m[3] else default_year
        if month and year:
            return _safe_date(year, month, int(m[1]))
    for m in _DATE_MDY_WORDS.finditer(text):
        month = _MONTHS.get(m[1].lower())
        year = int(m[3]) if m[3] else default_year
        if month and year:
            return _safe_date(year, month, int(m[2]))
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def derive_facts(extraction: IncidentExtractionOutput) -> DerivedFacts:
    """Incident date and time (with how they were derived) and the expected lighting."""
    submitted_date = parse_date(extraction.submitted_at)
    year = submitted_date.year if submitted_date else None
    stated = " ".join(t for t in (extraction.occurred_date, extraction.occurred_time) if t)

    incident_date: DerivedValue | None = None
    absolute = parse_date(extraction.occurred_date, year) or parse_date(
        extraction.occurred_time, year
    )
    if absolute:
        incident_date = DerivedValue(value=absolute.isoformat(), source="as stated")
    elif submitted_date and stated:
        for pattern, days in _RELATIVE:
            if match := pattern.search(stated):
                resolved = submitted_date - timedelta(days=days)
                incident_date = DerivedValue(
                    value=resolved.isoformat(),
                    source=f"from '{match.group(0)}' and the submission date "
                    f"{submitted_date.strftime('%d %b %Y')}",
                )
                break

    incident_time: DerivedValue | None = None
    parsed = parse_time(extraction.occurred_time) or parse_time(extraction.occurred_date)
    if parsed:
        incident_time = DerivedValue(
            value=parsed.strftime("%H:%M"), source=f"from '{extraction.occurred_time or stated}'"
        )

    # ASSUMPTION (A-121): a report that gives a time but no date describes the most
    # recent occurrence of that time before it was submitted. Shown as "assumed".
    submitted_time = parse_time(extraction.submitted_at)
    if incident_date is None and parsed and submitted_date and submitted_time:
        same_day = parsed <= submitted_time
        resolved = submitted_date if same_day else submitted_date - timedelta(days=1)
        incident_date = DerivedValue(
            value=resolved.isoformat(),
            source=f"assumed: no date stated; {parsed.strftime('%H:%M')} is the latest such "
            f"time before submission ({submitted_date.strftime('%d %b %Y')} "
            f"{submitted_time.strftime('%H:%M')})",
        )

    expected: DerivedValue | None = None
    if parsed:
        expected = DerivedValue(
            value=expected_lighting(parsed),
            source=f"Singapore daylight at {parsed.strftime('%H:%M')}",
        )
    return DerivedFacts(
        incident_date=incident_date, incident_time=incident_time, expected_lighting=expected
    )


def expected_lighting(at: time) -> Literal["daylight", "dusk_or_dawn", "night"]:
    """Coarse lighting expected at a time of day in Singapore."""
    if DAYLIGHT_START <= at < DAYLIGHT_END:
        return "daylight"
    if DAWN_START <= at < DAYLIGHT_START or DAYLIGHT_END <= at < DUSK_END:
        return "dusk_or_dawn"
    return "night"


def minutes_apart(a: time, b: time) -> int:
    """Absolute difference in minutes, assuming the same day."""
    return abs((a.hour * 60 + a.minute) - (b.hour * 60 + b.minute))


# --------------------------------------------------------------------------- locations

_ABBREVIATIONS = {
    "ave": "avenue",
    "av": "avenue",
    "rd": "road",
    "st": "street",
    "jln": "jalan",
    "blk": "block",
    "ctr": "centre",
    "center": "centre",
    "bt": "bukit",
    "upp": "upper",
    "amk": "ang mo kio",
    "lor": "lorong",
    "dr": "drive",
    "cres": "crescent",
    "pk": "park",
    "nth": "north",
    "sth": "south",
    "expy": "expressway",
    "tpy": "toa payoh",
    "cck": "choa chu kang",
    "pl": "place",
    "hwy": "highway",
    "sq": "square",
}
_FILLER = {
    "near",
    "at",
    "the",
    "of",
    "junction",
    "jct",
    "outside",
    "opposite",
    "opp",
    "beside",
    "and",
    "by",
    "along",
    "in",
    "on",
    "with",
    "between",
    "corner",
    "cnr",
    "area",
    "around",
    "about",
    "next",
    "to",
    "from",
    "a",
    "an",
}
_POSTAL = re.compile(r"\b\d{6}\b")

LocationMatch = Literal["strong", "partial", "none", "unknown"]


@dataclass(frozen=True)
class NormalisedLocation:
    tokens: frozenset[str]
    postal_codes: frozenset[str]


def normalise_location(text: str | None) -> NormalisedLocation | None:
    """Lower-case, expand abbreviations, drop filler words; keep postal codes apart."""
    if not text or not text.strip():
        return None
    postal = frozenset(_POSTAL.findall(text))
    cleaned = re.sub(r"[^\w\s]", " ", _POSTAL.sub(" ", text.lower()))
    tokens: set[str] = set()
    for word in cleaned.split():
        for part in _ABBREVIATIONS.get(word, word).split():
            if part not in _FILLER:
                tokens.add(part)
    return NormalisedLocation(frozenset(tokens), postal) if tokens or postal else None


def match_locations(a: str | None, b: str | None) -> tuple[LocationMatch, str]:
    """Compare two stated locations. Returns the verdict and a short reason."""
    la, lb = normalise_location(a), normalise_location(b)
    if la is None or lb is None:
        return "unknown", "a location is missing"
    if la.postal_codes & lb.postal_codes:
        return "strong", f"same postal code {sorted(la.postal_codes & lb.postal_codes)[0]}"
    shared = la.tokens & lb.tokens
    union = la.tokens | lb.tokens
    jaccard = len(shared) / len(union) if union else 0.0
    words = ", ".join(sorted(shared))
    if la.tokens == lb.tokens:
        return "strong", f"same place words ({words})"
    if jaccard >= LOCATION_PARTIAL_JACCARD:
        return "partial", f"shared place words ({words})"
    return "none", "locations do not match"


# --------------------------------------------------------------------------- tickets for grouping


@dataclass
class TicketForComparison:
    """What the grouping and contradiction rules need from one analysed document."""

    document_id: str
    label: str  # D1, D2...
    category: str
    location: str | None
    incident_date: date | None
    incident_time: time | None
    time_as_written: str | None
    facts: IncidentFacts
    time_page: int = 1


@dataclass
class Grouping:
    same_incident: list[DocumentGroup] = field(default_factory=list)
    possibly_related: list[DocumentGroup] = field(default_factory=list)
    #: Groups as lists of tickets, for the contradiction rules.
    groups: list[list[TicketForComparison]] = field(default_factory=list)


def _pair_verdict(
    a: TicketForComparison, b: TicketForComparison
) -> tuple[Literal["same", "possible", "unrelated"], str]:
    if a.category != b.category:
        return "unrelated", "different categories"
    reasons: list[str] = []
    if a.incident_date and b.incident_date:
        if a.incident_date != b.incident_date:
            return "unrelated", "different dates"
        reasons.append(f"same date ({a.incident_date.strftime('%d %b %Y')})")
    date_known = bool(a.incident_date and b.incident_date)
    if a.incident_time and b.incident_time:
        gap = minutes_apart(a.incident_time, b.incident_time)
        if gap > SAME_INCIDENT_WINDOW_MIN:
            return "unrelated", f"times {gap} min apart"
        reasons.append(
            f"times {a.incident_time.strftime('%H:%M')} and {b.incident_time.strftime('%H:%M')} "
            f"within {SAME_INCIDENT_WINDOW_MIN} min"
        )
    verdict, location_reason = match_locations(a.location, b.location)
    if verdict == "none":
        return "unrelated", location_reason
    reasons.append(location_reason)
    if date_known and verdict in ("strong", "partial"):
        return "same", "; ".join(reasons)
    return "possible", "; ".join(reasons)


def group_incidents(tickets: list[TicketForComparison]) -> Grouping:
    """Same-incident groups (transitive) and "possibly related" pairs, with reasons."""
    parent = {t.document_id: t.document_id for t in tickets}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    same_reasons: dict[tuple[str, str], str] = {}
    possible: list[tuple[TicketForComparison, TicketForComparison, str]] = []
    for a, b in combinations(tickets, 2):
        verdict, reason = _pair_verdict(a, b)
        if verdict == "same":
            parent[find(a.document_id)] = find(b.document_id)
            same_reasons[(a.document_id, b.document_id)] = reason
        elif verdict == "possible":
            possible.append((a, b, reason))

    clusters: dict[str, list[TicketForComparison]] = {}
    for t in tickets:
        clusters.setdefault(find(t.document_id), []).append(t)

    result = Grouping()
    for members in clusters.values():
        if len(members) < 2:
            continue
        ids = {m.document_id for m in members}
        reason = next(
            r for (x, y), r in same_reasons.items() if x in ids and y in ids
        )  # the first pair's evidence; all pairs are recorded in the timeline/contradictions
        labels = ", ".join(m.label for m in members)
        result.same_incident.append(
            DocumentGroup(
                document_ids=[m.document_id for m in members],
                reason=f"Same incident by rule ({labels}): {reason}.",
            )
        )
        result.groups.append(members)
    for a, b, reason in possible:
        if find(a.document_id) == find(b.document_id):
            continue
        result.possibly_related.append(
            DocumentGroup(
                document_ids=[a.document_id, b.document_id],
                reason=f"Possibly related ({a.label}, {b.label}): {reason}. Check before "
                "treating them as one incident.",
            )
        )
    return result


# --------------------------------------------------------------------------- across tickets


def _reports(n: int) -> str:
    return f"{n} report{'s' if n != 1 else ''}"


def photo_summary(with_photos: list[str], total: int) -> str:
    """One sentence, generated by code, stating which reports include photos.

    Computed from the visual elements (stage 2), so the model-written summary cannot
    claim that no report has photos when one does (L-007). A photo whose visual
    analysis failed is not counted.

    Args:
        with_photos: Labels (D1, D2…) of reports with at least one photo element.
        total: Number of reports in the job.
    """
    if not with_photos:
        return "No report includes photos." if total != 1 else "The report includes no photos."
    n = len(with_photos)
    verb = "includes" if n == 1 else "include"
    return f"{_reports(n)} {verb} photos ({', '.join(with_photos)})."


def grouping_summary(grouping: Grouping, compared: int, excluded: int = 0) -> str:
    """One sentence, generated by code, stating how many incidents the reports describe.

    Shown above the model-written summary so the count can never contradict the
    groups (in one live run the model called one incident "three incidents", L-007).
    """
    grouped = sum(len(g) for g in grouping.groups)
    separate = compared - grouped
    parts: list[str] = []
    if grouping.groups:
        sizes = [len(g) for g in grouping.groups]
        incidents = len(sizes)
        detail = f" ({' and '.join(str(n) for n in sizes)} reports)" if incidents > 1 else ""
        verb = "describe" if grouped != 1 else "describes"
        parts.append(
            f"{_reports(grouped)} {verb} {incidents} incident{'s' if incidents > 1 else ''}{detail}"
        )
    if separate:
        if grouping.groups:
            parts.append(
                f"{_reports(separate)} {'describes' if separate == 1 else 'describe'} "
                f"{'a separate incident' if separate == 1 else 'separate incidents'}"
            )
        else:
            parts.append(f"{_reports(separate)}, each describing a separate incident")
    if grouping.possibly_related:
        n = len(grouping.possibly_related)
        parts.append(f"{n} pair{'s' if n != 1 else ''} may be related (not confirmed)")
    if excluded:
        parts.append(f"{_reports(excluded)} could not be compared")
    return "; ".join(parts) + "." if parts else "No reports could be compared."


def _citation(t: TicketForComparison, page: int | None) -> Citation:
    return Citation(document_id=t.document_id, page=page or 1)


def _quote(text: str | None) -> str:
    return f" (“{text.strip()}”)" if text and text.strip() else ""


def compare_group(
    group: list[TicketForComparison], suffix: str = ""
) -> tuple[list[Contradiction], list[Agreement]]:
    """Contradictions and agreements within one same-incident group.

    A field is compared only between tickets that STATE a value: "not_mentioned"
    never creates a contradiction (it is a gap, reported elsewhere).
    """
    contradictions: list[Contradiction] = []
    agreements: list[Agreement] = []

    # Time: a contradiction if any two stated times are more than the tolerance apart.
    timed = [t for t in group if t.incident_time]
    if len(timed) >= 2:
        spread = max(
            minutes_apart(a.incident_time, b.incident_time)  # type: ignore[arg-type]
            for a, b in combinations(timed, 2)
        )
        cites = [_citation(t, t.time_page) for t in timed]
        if spread > CONTRADICTION_TIME_TOLERANCE_MIN:
            contradictions.append(
                Contradiction(
                    topic=f"{FIELD_LABELS['occurred_time']}{suffix}",
                    positions=[
                        Position(
                            position=f"{t.label}: {t.incident_time.strftime('%H:%M')}"  # type: ignore[union-attr]
                            f"{_quote(t.time_as_written)}",
                            citation=c,
                        )
                        for t, c in zip(timed, cites, strict=True)
                    ],
                )
            )
        else:
            agreements.append(
                Agreement(
                    point=f"{FIELD_LABELS['occurred_time']}: within "
                    f"{CONTRADICTION_TIME_TOLERANCE_MIN} min across reports{suffix}",
                    citations=cites,
                )
            )

    for name in COMPARED_FIELDS:
        stated = [
            (t, getattr(t.facts, name))
            for t in group
            if getattr(t.facts, name).value != "not_mentioned"
        ]
        if len(stated) < 2:
            continue
        # Lighting is compared coarsely (daylight / dusk or dawn / night): "street lights
        # on" and "dark" are both night, not a contradiction between reporters (D-058).
        values = {
            _COARSE_LIGHT[fact.value] if name == "lighting" else fact.value for _, fact in stated
        }
        cites = [_citation(t, fact.page) for t, fact in stated]
        if len(values) > 1:
            contradictions.append(
                Contradiction(
                    topic=f"{FIELD_LABELS[name]}{suffix}",
                    positions=[
                        Position(
                            position=f"{t.label}: {label(fact.value)}{_quote(fact.as_written)}",
                            citation=c,
                        )
                        for (t, fact), c in zip(stated, cites, strict=True)
                    ],
                )
            )
        else:
            agreements.append(
                Agreement(
                    point=f"{FIELD_LABELS[name]}: {label(values.pop())} "
                    f"(every report that mentions it){suffix}",
                    citations=cites,
                )
            )
    return contradictions, agreements


def build_timeline(tickets: list[TicketForComparison]) -> list[TimelineEvent]:
    """Each ticket's stated incident time, in order; undated ones last."""
    events: list[tuple[tuple[int, date, time], TimelineEvent]] = []
    for t in tickets:
        if not (t.incident_date or t.incident_time):
            continue
        parts = []
        if t.incident_date:
            parts.append(t.incident_date.strftime("%d %b %Y"))
        if t.incident_time:
            parts.append(t.incident_time.strftime("%H:%M"))
        events.append(
            (
                (
                    0 if t.incident_date else 1,
                    t.incident_date or date.max,
                    t.incident_time or time.max,
                ),
                TimelineEvent(
                    time=" ".join(parts),
                    event=f"Incident as reported by {t.label}{_quote(t.time_as_written)}",
                    citations=[_citation(t, t.time_page)],
                ),
            )
        )
    return [event for _, event in sorted(events, key=lambda e: e[0])]


# --------------------------------------------------------------------------- narrative vs photo


@dataclass
class PhotoScene:
    page: int
    scene: SceneObservation


_COARSE_LIGHT = {
    "daylight": "daylight",
    "dusk_or_dawn": "dusk_or_dawn",
    "night_street_lit": "night",
    "night_dark": "night",
    "night": "night",
}


def _combine(
    results: list[tuple[str, str, int]],
) -> tuple[Literal["consistent", "inconsistent", "unclear"], str, list[int]] | None:
    """Combine per-photo results: any inconsistent wins, then consistent, else unclear."""
    if not results:
        return None
    for wanted in ("inconsistent", "consistent"):
        hits = [r for r in results if r[0] == wanted]
        if hits:
            return wanted, "; ".join(f"{d} (p.{p})" for _, d, p in hits), [p for _, _, p in hits]  # type: ignore[return-value]
    return "unclear", "; ".join(f"{d} (p.{p})" for _, d, p in results), [p for _, _, p in results]


def _weather_vs_photo(value: str, s: SceneObservation) -> tuple[str, str]:
    if value == "rain":
        if s.weather == "rain" or s.road_surface in ("wet", "flooded"):
            return "consistent", "photo shows rain or a wet road"
        if s.road_surface == "dry":
            return "inconsistent", "photo shows a dry road"
        if s.weather in ("clear", "overcast"):
            return "inconsistent", f"photo shows {label(s.weather)} weather"
        return "unclear", "weather not clear in the photo"
    if s.weather == "unclear":
        return "unclear", "weather not clear in the photo"
    if value in ("clear", "overcast") and s.weather in ("clear", "overcast"):
        return "consistent", f"photo shows {label(s.weather)} weather"
    if value == s.weather:
        return "consistent", f"photo shows {label(s.weather)}"
    return "inconsistent", f"photo shows {label(s.weather)}"


def _road_vs_photo(value: str, s: SceneObservation) -> tuple[str, str]:
    if s.road_surface == "unclear":
        return "unclear", "road surface not clear in the photo"
    if value == s.road_surface or (value == "wet" and s.road_surface == "flooded"):
        return "consistent", f"photo shows a {label(s.road_surface)} road"
    return "inconsistent", f"photo shows a {label(s.road_surface)} road"


def _light_vs_photo(expected: str, s: SceneObservation) -> tuple[str, str]:
    photo = _COARSE_LIGHT.get(s.lighting)
    if photo is None:
        return "unclear", "lighting not clear in the photo"
    if "dusk_or_dawn" in (expected, photo) and expected != photo:
        return "unclear", f"photo shows {label(s.lighting)}"
    if expected == photo:
        return "consistent", f"photo shows {label(s.lighting)}"
    return "inconsistent", f"photo shows {label(s.lighting)}"


def check_narrative_against_photos(
    facts: IncidentFacts, derived: DerivedFacts, photos: list[PhotoScene]
) -> tuple[list[ConsistencyCheck], dict[str, tuple[str, str]]]:
    """Consistency checks between the reporter's account and their own photos.

    Returns the checks and, per fact field, (result, details) for claim corroboration.
    Vehicle count is never checked against a photo: vehicles can be out of frame.
    """
    checks: list[ConsistencyCheck] = []
    by_field: dict[str, tuple[str, str]] = {}
    if not photos:
        return checks, by_field

    def add(
        field_name: str,
        title: str,
        claim_page: int | None,
        claim_text: str,
        per_photo: list[tuple[str, str, int]],
    ) -> None:
        combined = _combine(per_photo)
        if combined is None:
            return
        result, details, pages = combined
        all_pages = sorted({*pages, *([claim_page] if claim_page else [])})
        checks.append(
            ConsistencyCheck(
                check=title,
                result=result,
                details=f"Reporter: {claim_text}. Photo: {details}.",
                pages=all_pages,
            )
        )
        by_field[field_name] = (result, details)

    if facts.weather.value != "not_mentioned":
        add(
            "weather",
            "Weather: narrative vs photo",
            facts.weather.page,
            f"{label(facts.weather.value)}{_quote(facts.weather.as_written)}",
            [(*_weather_vs_photo(facts.weather.value, p.scene), p.page) for p in photos],
        )
    if facts.road_surface.value != "not_mentioned":
        add(
            "road_surface",
            "Road surface: narrative vs photo",
            facts.road_surface.page,
            f"{label(facts.road_surface.value)}{_quote(facts.road_surface.as_written)}",
            [(*_road_vs_photo(facts.road_surface.value, p.scene), p.page) for p in photos],
        )

    # Lighting: what the reporter states, or else what the stated time implies.
    if facts.lighting.value != "not_mentioned":
        expected = _COARSE_LIGHT[facts.lighting.value]
        claim_text = f"{label(facts.lighting.value)}{_quote(facts.lighting.as_written)}"
        claim_page = facts.lighting.page
    elif derived.expected_lighting:
        expected = derived.expected_lighting.value
        claim_text = (
            f"{label(expected)} expected at the stated time ({derived.expected_lighting.source})"
        )
        claim_page = None
    else:
        expected = ""
    if expected:
        add(
            "lighting",
            "Lighting: narrative vs photo",
            claim_page,
            claim_text,
            [(*_light_vs_photo(expected, p.scene), p.page) for p in photos],
        )

    if facts.traffic_light.value in ("red", "amber", "green"):
        visible = [p for p in photos if p.scene.traffic_signal in ("red", "amber", "green")]
        add(
            "traffic_light",
            "Traffic light: narrative vs photo",
            facts.traffic_light.page,
            f"{label(facts.traffic_light.value)}{_quote(facts.traffic_light.as_written)}",
            [
                (
                    "consistent"
                    if p.scene.traffic_signal == facts.traffic_light.value
                    else "inconsistent",
                    f"signal shows {p.scene.traffic_signal}",
                    p.page,
                )
                for p in visible
            ],
        )

    if facts.damage_locations:
        claimed = set(facts.damage_locations)
        per_photo = []
        for p in photos:
            seen = {d for d in p.scene.damage_locations if d not in ("none_visible", "unclear")}
            if not seen:
                continue
            overlap = claimed & seen
            per_photo.append(
                ("consistent", f"damage visible at {', '.join(sorted(overlap))}", p.page)
                if overlap
                else ("unclear", f"damage visible at {', '.join(sorted(seen))}", p.page)
            )
        add(
            "damage_locations",
            "Damage: narrative vs photo",
            None,
            f"damage at {', '.join(sorted(claimed))}",
            per_photo,
        )

    if derived.incident_time:
        stated = parse_time(derived.incident_time.value)
        per_photo = []
        for p in photos:
            shown = parse_time(p.scene.timestamp_visible)
            if stated and shown:
                gap = minutes_apart(stated, shown)
                per_photo.append(
                    (
                        "consistent" if gap <= CONTRADICTION_TIME_TOLERANCE_MIN else "inconsistent",
                        f"timestamp {shown.strftime('%H:%M')}",
                        p.page,
                    )
                )
        add(
            "occurred_time",
            "Time: narrative vs photo timestamp",
            None,
            f"{derived.incident_time.value}",
            per_photo,
        )
    return checks, by_field


# --------------------------------------------------------------------------- quote grounding

# A stated value must be supported by its quote. Live scorecard runs showed the 4B
# model over-extracting: lighting "night (dark)" from the quote "at about 9.20pm",
# road surface "dry" from "The weather was dry", and a value with the quote
# "not mentioned". Each field's quote must contain at least one of these cue words
# (vehicle_count has no cue list: counts are phrased too many ways).
GROUNDING_CUES: dict[str, tuple[str, ...]] = {
    "traffic_light": ("light", "signal"),
    "weather": (
        "rain",
        "drizzl",
        "shower",
        "downpour",
        "storm",
        "weather",
        "dry",
        "fine",
        "clear",
        "sunny",
        "sun",
        "cloud",
        "overcast",
        "fog",
        "mist",
        "haz",
        "wet",
    ),
    "road_surface": ("road", "surface", "street", "ground", "tarmac", "puddle", "flood", "slipper"),
    "lighting": (
        "light",
        "dark",
        "night",
        "daylight",
        "day",
        "dusk",
        "dawn",
        "lamp",
        "bright",
        "dim",
        "sun",
    ),
    "injuries": (
        "hurt",
        "injur",
        "bleed",
        "blood",
        "arm",
        "wrist",
        "leg",
        "head",
        "pain",
        "ambulance",
        "hospital",
        "unhurt",
        "wound",
        "fatal",
        "dead",
        "died",
        "okay",
        "fine",
    ),
    "party_left_scene": (
        "drove",
        "rode",
        "left",
        "fled",
        "stayed",
        "remained",
        "away",
        "off",
        "scene",
    ),
}
# Weapon cues are matched as whole words: substrings would let "gun" match "begun" and
# "armed" match "alarmed". The quote must contain one of these for any weapon value.
_WEAPON_CUE = re.compile(
    r"\b(?:weapons?|knife|knives|guns?|firearms?|pistols?|rifles?|shotguns?|revolvers?|"
    r"blades?|parangs?|machetes?|swords?|axes?|cleavers?|daggers?|armed|unarmed|"
    r"stabb?(?:ed|ing)?|shot (?:at|him|her|someone))\b",
    re.I,
)
# Negation anywhere in the (short) quote. Crude on purpose; see ASSUMPTIONS L-020.
_NEGATION = re.compile(
    r"\b(?:no|not|never|without|nobody|none|neither|nor|unarmed|"
    r"didn'?t|did not|wasn'?t|was not|weren'?t|were not|couldn'?t|could not)\b|\bno one\b",
    re.I,
)


def is_negated_weapon_mention(quote: str) -> bool:
    """True for a quote that names a weapon only to deny it ("no weapon was seen")."""
    return bool(_WEAPON_CUE.search(quote)) and bool(_NEGATION.search(quote))


def weapon_polarity(value: str, quote: str) -> str:
    """Check a grounded weapon value against negation in its quote (safety-first).

    "No weapon was seen" labelled yes becomes no. A weapon quote without any negation
    labelled no ("he was holding a knife") becomes yes, because under-reading a weapon
    is the costly error; every result is reviewed by an analyst.
    """
    negated = bool(_NEGATION.search(quote))
    if value == "yes" and negated:
        return "no"
    if value == "no" and not negated:
        return "yes"
    return value


_NOT_A_QUOTE = re.compile(r"^\W*(?:not (?:mentioned|stated)|n/?a|none|unknown|null)\W*$", re.I)


def ground_facts(facts: IncidentFacts) -> tuple[IncidentFacts, list[str]]:
    """Downgrade stated values whose quote does not support them to "not_mentioned".

    The weapon fact is also checked for negation (``weapon_polarity``).

    Returns:
        The grounded facts and the names of the fields that were changed: a plain
        name means downgraded to not_mentioned, ``weapon:polarity`` means corrected.
    """
    downgraded: list[str] = []
    updated = facts.model_copy()
    for name in COMPARED_FIELDS:
        fact = getattr(facts, name)
        if fact.value == "not_mentioned":
            continue
        quote = (fact.as_written or "").strip()
        cues = GROUNDING_CUES.get(name, ())
        grounded = bool(quote) and not _NOT_A_QUOTE.match(quote)
        if grounded and name == "weapon":
            grounded = bool(_WEAPON_CUE.search(quote))
        elif grounded and cues:
            grounded = any(cue in quote.lower() for cue in cues)
        if grounded and name == "weapon":
            corrected = weapon_polarity(fact.value, quote)
            if corrected != fact.value:
                setattr(updated, name, fact.model_copy(update={"value": corrected}))
                downgraded.append(f"{name}:polarity")
            continue
        if not grounded:
            setattr(
                updated,
                name,
                fact.model_copy(
                    update={"value": "not_mentioned", "as_written": None, "page": None}
                ),
            )
            downgraded.append(name)
    return updated, downgraded


# --------------------------------------------------------------------------- claims and gaps

_CORROBORATION = {
    "consistent": "supported",
    "inconsistent": "contradicted",
    "unclear": "not_verifiable",
}


def build_claims(
    extraction: IncidentExtractionOutput,
    by_field: dict[str, tuple[str, str]],
    has_photo: bool,
) -> list[Claim]:
    """The spec's ``claims``: one per stated fact, plus the model's free-text claims."""
    claims: list[Claim] = []
    for name in COMPARED_FIELDS:
        fact = getattr(extraction.facts, name)
        if fact.value == "not_mentioned":
            continue
        if name in by_field:
            result, details = by_field[name]
            corroboration, note = _CORROBORATION[result], f"Photo: {details}."
        elif not has_photo:
            corroboration, note = "not_verifiable", "No photo attached."
        else:
            corroboration, note = "not_verifiable", "Not checkable against the photo."
        claims.append(
            Claim(
                claim=f"{FIELD_LABELS[name]}: {label(fact.value)}{_quote(fact.as_written)}",
                page=fact.page,
                corroboration=corroboration,  # type: ignore[arg-type]
                note=note,
            )
        )
    for other in extraction.other_claims:
        claims.append(
            Claim(
                claim=other.claim,
                page=other.page,
                corroboration="not_verifiable",
                note="Free-text claim; not compared automatically.",
            )
        )
    return claims


def missing_information(
    extraction: IncidentExtractionOutput, derived: DerivedFacts, has_photo: bool
) -> list[str]:
    """Key fields the reporter did not give (by rule), merged with the model's list."""
    gaps: list[str] = []
    if derived.incident_date is None:
        gaps.append("Date of the incident not stated (or not recognisable).")
    if derived.incident_time is None:
        gaps.append("Time of the incident not stated (or not recognisable).")
    if not (extraction.location and extraction.location.strip()):
        gaps.append("Location not stated.")
    facts = extraction.facts
    if facts.vehicle_count.value == "not_mentioned" and extraction.category == "road_traffic":
        gaps.append("Number of vehicles involved not stated.")
    if facts.injuries.value == "not_mentioned":
        gaps.append("Whether anyone was injured is not stated.")
    if not has_photo:
        gaps.append("No photo attached, so the account cannot be checked against images.")
    seen = {g.lower() for g in gaps}
    for item in extraction.missing_information:
        if item.strip() and item.lower() not in seen:
            gaps.append(item)
            seen.add(item.lower())
    return gaps


def ticket_for_comparison(
    document_id: str,
    label_: str,
    category: str,
    location: str | None,
    derived: DerivedFacts,
    time_as_written: str | None,
    facts: IncidentFacts,
) -> TicketForComparison:
    """Build the comparison record from a document's incident extension."""
    incident_date = (
        date.fromisoformat(derived.incident_date.value) if derived.incident_date else None
    )
    incident_time = (
        datetime.strptime(derived.incident_time.value, "%H:%M").time()
        if derived.incident_time
        else None
    )
    return TicketForComparison(
        document_id=document_id,
        label=label_,
        category=category,
        location=location,
        incident_date=incident_date,
        incident_time=incident_time,
        time_as_written=time_as_written,
        facts=facts,
    )
