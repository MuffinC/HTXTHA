"""Deterministic triage rules (incident profile; DECISIONS D-062).

* ``rule_floor``: the CLAUDE.md section-8 rubric applied to one report's own
  extracted facts. This is the minimum priority; nothing can lower it.
* ``ground_escalation``: a model raise counts only if it quotes the page
  verbatim (checked here, normalised for whitespace and case).
* ``combine``: the final suggestion is the more severe of rule and model.
* ``group_priority``: a same-incident group's priority is the highest of its
  reports, lifted to P2 when reports contradict each other on a
  safety-relevant field (traffic light, injuries, a party leaving the scene,
  vehicle count). Other contradictions are listed as factors but do not lift.

Rubric (verbatim from CLAUDE.md section 8):
- P1: Ongoing danger to life, serious injury or death, weapons, or a suspect at large posing a risk.
- P2: Injury reported, a party left the scene, significant property damage, or major
  contradictions needing follow-up.
- P3: Property damage only, no injuries, parties identified.
- P4: Informational, duplicate of another report, or insufficient detail to act on.

The fixed fields cover serious injury, injury, a party leaving the scene and
"no injuries". Weapons, a suspect at large and significant property damage are
not fixed fields; only a grounded model raise can bring them in.
"""

import re
from dataclasses import dataclass

from app.schemas.common import Citation
from app.schemas.consolidated import Contradiction
from app.schemas.incident import IncidentExtension
from app.schemas.triage import PRIORITY_ORDER, Priority, TriageFactor, TriageModelOutput

#: Contradiction topics (incident_rules.FIELD_LABELS) that lift a group to P2.
SAFETY_TOPICS: tuple[str, ...] = (
    "Traffic light",
    "Injuries",
    "A party left the scene",
    "Number of vehicles",
)
GROUP_LIFT: Priority = "P2"


def more_severe(a: Priority, b: Priority) -> Priority:
    """The more urgent of two priorities (P1 is the most urgent)."""
    return a if PRIORITY_ORDER.index(a) <= PRIORITY_ORDER.index(b) else b


def is_raise(proposed: Priority, floor: Priority) -> bool:
    """True if ``proposed`` is strictly more urgent than ``floor``."""
    return PRIORITY_ORDER.index(proposed) < PRIORITY_ORDER.index(floor)


@dataclass
class RuleResult:
    priority: Priority
    factors: list[TriageFactor]
    rationale: str


def rule_floor(incident: IncidentExtension, document_id: str) -> RuleResult:
    """Minimum priority from one report's own facts (the rubric's fixed-field parts)."""
    facts = incident.facts
    candidates: list[tuple[Priority, str, int | None]] = []

    def cite(page: int | None) -> Citation:
        return Citation(document_id=document_id, page=page or 1)

    if facts.injuries.value == "serious_or_fatal":
        candidates.append(("P1", "Serious injury or death reported", facts.injuries.page))
    elif facts.injuries.value == "injury":
        candidates.append(("P2", "Injury reported", facts.injuries.page))
    if facts.party_left_scene.value == "yes":
        candidates.append(("P2", "A party left the scene", facts.party_left_scene.page))
    if not candidates and facts.injuries.value == "none":
        candidates.append(("P3", "No injuries reported", facts.injuries.page))
    d = incident.derived
    insufficient = (
        d.incident_date is None and d.incident_time is None and not incident.location_stated
    )
    if not candidates:
        reason = (
            "Insufficient detail to act on (no recognisable date, time or location)"
            if insufficient
            else "No rubric condition met by the extracted facts"
        )
        candidates.append(("P4", reason, None))

    priority = candidates[0][0]
    for p, _, _ in candidates[1:]:
        priority = more_severe(priority, p)
    factors = [
        TriageFactor(factor=f, citation=cite(page), source="rule") for _, f, page in candidates
    ]
    rationale = f"Rule floor {priority}: " + "; ".join(f for _, f, _ in candidates) + "."
    return RuleResult(priority=priority, factors=factors, rationale=rationale)


# --------------------------------------------------------------------------- model raise

_WS = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Lower-case and collapse whitespace (and smart quotes), for quote matching."""
    text = text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return _WS.sub(" ", text).strip().lower()


@dataclass
class Escalation:
    accepted: bool
    priority: Priority | None
    factors: list[TriageFactor]
    note: str


def ground_escalation(
    proposal: TriageModelOutput,
    floor: Priority,
    page_texts: dict[int, str],
    document_id: str,
) -> Escalation:
    """Accept a model raise only if a verbatim quote supports it on the cited page.

    A proposal at or below the floor is not a raise and changes nothing. A raise
    with no quote that actually appears on its page (normalised for whitespace
    and case) is ignored; injected text cannot conjure evidence that is not there.
    """
    if not is_raise(proposal.proposed_priority, floor):
        return Escalation(False, None, [], "Model did not propose a higher priority.")
    grounded: list[TriageFactor] = []
    for ev in proposal.evidence:
        quote = _normalise(ev.quote)
        page_text = _normalise(page_texts.get(ev.page, ""))
        if len(quote) >= 4 and quote in page_text:
            grounded.append(
                TriageFactor(
                    factor=f"{proposal.reason} (“{ev.quote.strip()}”)",
                    citation=Citation(document_id=document_id, page=ev.page),
                    source="model",
                )
            )
    if not grounded:
        return Escalation(
            False,
            None,
            [],
            f"Model proposed {proposal.proposed_priority} but no quote was found on the cited "
            "page; the raise was ignored.",
        )
    return Escalation(True, proposal.proposed_priority, grounded, "")


def combine(floor: RuleResult, escalation: Escalation, confidence: str) -> tuple[Priority, str]:
    """Final suggestion (more severe of rule and grounded raise) and its rationale."""
    if escalation.accepted and escalation.priority:
        final = more_severe(floor.priority, escalation.priority)
        return final, f"{floor.rationale} Raised to {final} by the model, with quoted evidence."
    note = f" {escalation.note}" if escalation.note and "ignored" in escalation.note else ""
    return floor.priority, floor.rationale + note


# --------------------------------------------------------------------------- groups


@dataclass
class GroupPriority:
    priority: Priority
    reason: str


def group_priority(
    member_priorities: dict[str, Priority], contradictions: list[Contradiction]
) -> GroupPriority:
    """Highest of the group's reports, lifted to P2 by a safety-relevant contradiction.

    Args:
        member_priorities: document_id -> that report's suggested priority.
        contradictions: the group's rule-based contradictions.
    """
    priority: Priority = "P4"
    for p in member_priorities.values():
        priority = more_severe(priority, p)
    highest = priority
    safety = [c.topic for c in contradictions if c.topic.startswith(SAFETY_TOPICS)]
    other = [c.topic for c in contradictions if not c.topic.startswith(SAFETY_TOPICS)]
    parts = [f"highest report priority {highest}"]
    if safety:
        priority = more_severe(priority, GROUP_LIFT)
        parts.append(
            f"contradictions needing follow-up on {', '.join(t.split(' (')[0] for t in safety)} "
            f"(at least {GROUP_LIFT})"
        )
    if other:
        parts.append(f"also differ on {', '.join(t.split(' (')[0] for t in other)} (does not lift)")
    return GroupPriority(priority=priority, reason=f"Group {priority}: " + "; ".join(parts) + ".")
