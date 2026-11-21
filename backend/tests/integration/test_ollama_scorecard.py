"""Report-only scorecard: does the consolidated report find the planted contradictions?

Opt-in: ``pytest -m ollama``. Uploads the synthetic pair (``incident_report_pdf``
and ``witness_report_pdf``), which describe the same incident with four planted
contradictions:

=================  =====================  ======================
Contradiction      Report A (D1)          Report B (D2)
=================  =====================  ======================
time               about 21:15            around 21:30
weather            dry                    wet from earlier rain
traffic light      green                  red
vehicle count      two cars               three vehicles
=================  =====================  ======================

The pair also contains one genuine contradiction that was not planted: report A
says "nobody appeared to be hurt", report B that "one driver was holding his
arm". Contradictions about injury or driver behaviour are reported as
"genuine, unplanted" rather than false, unless they use absence wording.

It prints found/missed per planted contradiction, the false contradictions
(anything else listed as a contradiction, including "one document does not
mention X"), and whether the pair was grouped as the same incident. Scores are
**reported, not asserted**: the test fails only if the pipeline itself fails.
The M3 baseline is recorded in DECISIONS D-042 and is the M6 acceptance measure.

Matching is keyword-based on each contradiction's topic and positions, so it is
a rough measure. Read the printed topics before trusting a number.
"""

import asyncio
import re
import time
from typing import Any

import pytest

from app.config import Settings
from app.llm.ollama import OllamaProvider
from app.main import create_app
from tests import pdf_factory
from tests.conftest import app_client
from tests.integration.conftest import NOTES
from tests.ticket_factory import PLANTED as TICKET_PLANTED
from tests.ticket_factory import TICKETS, ticket_pdf

pytestmark = pytest.mark.ollama

# Each planted contradiction matches if BOTH patterns occur in one contradiction's text,
# or if its topic matches the optional topic pattern in TOPIC_MATCH.
PLANTED: dict[str, tuple[str, str]] = {
    "time (21:15 vs 21:30)": (r"21[:.]15", r"21[:.]30"),
    "weather (dry vs wet)": (r"\bdry\b", r"\bwet\b|\brain"),
    "traffic light (green vs red)": (r"\bgreen\b", r"\bred\b"),
    "vehicle count (two vs three)": (r"\btwo\b|\b2\b", r"\bthree\b|\b3\b"),
}
# A model often names the vehicles ("silver car, taxi, motorcycle") instead of
# writing "three", so a topic about the number of vehicles also counts.
TOPIC_MATCH = {
    "vehicle count (two vs three)": re.compile(
        r"number of (?:vehicles|cars)|vehicle count|how many vehicles", re.I
    ),
}
# Wording that signals "one side is silent" rather than a real disagreement.
ABSENCE = re.compile(
    r"no mention|not mention|does not (?:say|state|mention)|not stated|silent", re.I
)
UNPLANTED_INJURY = re.compile(r"injur|hurt|driver behaviou?r", re.I)
SEPARATE = re.compile(r"\b(?:separate|different|distinct|unrelated) (?:incidents?|events?)", re.I)


def score(report: dict[str, Any], doc_ids: set[str]) -> list[str]:
    """Turn a consolidated report into printable scorecard lines."""
    texts = [
        " ".join([c["topic"], *(p["position"] for p in c["positions"])])
        for c in report["contradictions"]
    ]
    lines, matched = [], set()
    for name, (a, b) in PLANTED.items():
        topic = TOPIC_MATCH.get(name)
        hits = [
            i
            for i, t in enumerate(texts)
            if (re.search(a, t, re.I) and re.search(b, t, re.I))
            or (topic and topic.search(report["contradictions"][i]["topic"]))
        ]
        matched.update(hits)
        lines.append(f"  {'FOUND ' if hits else 'MISSED'} {name}")
    found = sum(line.startswith("  FOUND") for line in lines)

    topics = [c["topic"] for c in report["contradictions"]]
    absence = [topics[i] for i, t in enumerate(texts) if ABSENCE.search(t)]
    # Absence wording always counts as false, even on the injury topic.
    unplanted = [
        topics[i]
        for i in range(len(texts))
        if i not in matched and topics[i] not in absence and UNPLANTED_INJURY.search(topics[i])
    ]
    false = [
        topics[i] for i in range(len(texts)) if i not in matched and topics[i] not in unplanted
    ]
    grouped = any(set(g["document_ids"]) == doc_ids for g in report["related_document_groups"])
    separate = bool(SEPARATE.search(report["overall_summary"])) or any(
        SEPARATE.search(g["reason"]) for g in report["related_document_groups"]
    )
    return [
        f"planted contradictions found: {found}/4",
        *lines,
        f"  false contradictions: {len(false)} {false}",
        f"    of which 'absence' contradictions: {len(absence)} {absence}",
        f"  genuine but unplanted (injury): {unplanted}",
        f"  grouped as one related group: {'yes' if grouped else 'no'}",
        f"  report calls them separate/different incidents: {'yes' if separate else 'no'}",
        f"  timeline: {[e['time'] for e in report['timeline']]}",
    ]


async def _run(
    provider: OllamaProvider, settings: Settings, files: list[tuple[str, bytes]], profile: str
) -> tuple[dict[str, Any], float]:
    """Upload through the API and poll until the job finishes; returns (job, seconds)."""
    async with app_client(create_app(settings, provider=provider)) as client:
        started = time.perf_counter()
        created = (
            await client.post(
                "/api/jobs",
                files=[("files", (n, d, "application/pdf")) for n, d in files],
                data={"profile": profile},
            )
        ).json()
        job: dict[str, Any] = {}
        while time.perf_counter() - started < 900:
            job = (await client.get(f"/api/jobs/{created['job_id']}")).json()
            if job["status"] in {"completed", "partial", "failed"}:
                break
            await asyncio.sleep(1)
    return job, time.perf_counter() - started


@pytest.mark.parametrize("profile", ["general", "incident"])
async def test_contradiction_scorecard(
    live_provider: OllamaProvider, live_settings: Settings, profile: str
) -> None:
    """The M3 measure on the original synthetic pair, under either profile."""
    files = [
        ("report_a.pdf", pdf_factory.incident_report_pdf()),
        ("report_b.pdf", pdf_factory.witness_report_pdf()),
    ]
    job, seconds = await _run(live_provider, live_settings, files, profile)

    # The only hard requirement: the pipeline produced a consolidated report.
    assert job["status"] == "completed", job
    doc_ids = {d["document_id"] for d in job["documents"]}
    NOTES.append(f"CONTRADICTION SCORECARD, M3 measure, profile={profile} ({seconds:.0f}s)")
    NOTES.extend(score(job["consolidated"], doc_ids))
    entities = [e["name"] for d in job["documents"] for e in d["analysis"]["key_entities"]]
    artefacts = [
        e for e in entities if re.search(r"synthetic sample|ai visual description", e, re.I)
    ]
    NOTES.append(f"  pipeline artefacts listed as entities: {artefacts}")


def score_tickets(job: dict[str, Any]) -> list[str]:
    """Ticket scorecard lines: extraction accuracy, contradictions, checks, grouping."""
    by_key = {d["filename"].removesuffix(".pdf"): d for d in job["documents"]}
    key_by_id = {d["document_id"]: k for k, d in by_key.items()}
    lines: list[str] = []

    correct = total = 0
    misses: list[str] = []
    for ticket in TICKETS:
        incident = by_key[ticket.key]["analysis"]["incident"]
        if incident is None:
            misses.append(f"{ticket.key}: extraction failed")
            total += len(ticket.expected)
            continue
        for name, expected in ticket.expected.items():
            actual = incident["facts"][name]["value"]
            total += 1
            if actual == expected:
                correct += 1
            else:
                misses.append(f"{ticket.key}.{name}: {actual} (expected {expected})")
    lines.append(f"field extraction: {correct}/{total} correct")
    lines += [f"  wrong: {m}" for m in misses]

    report = job["consolidated"]
    groups = [{key_by_id[i] for i in g["document_ids"]} for g in report["related_document_groups"]]
    grouped_ok = TICKET_PLANTED["same_incident"] in groups
    separate_ok = not any(TICKET_PLANTED["separate"] & g for g in groups)
    lines.append(
        f"grouping: same-incident group {'OK' if grouped_ok else 'WRONG'} {groups}; "
        f"T4 separate {'OK' if separate_ok else 'WRONG'}; "
        f"possibly related: {len(report['possibly_related_groups'])}"
    )

    topics = {c["topic"]: c for c in report["contradictions"]}
    found = TICKET_PLANTED["contradictions"] & set(topics)
    false = set(topics) - TICKET_PLANTED["contradictions"]
    lines.append(
        f"planted contradictions found: {len(found)}/{len(TICKET_PLANTED['contradictions'])}"
    )
    lines += [f"  MISSED {t}" for t in sorted(TICKET_PLANTED["contradictions"] - found)]
    topic, absent_key = TICKET_PLANTED["absence_check"]
    absence_violation = topic in topics and absent_key in {
        key_by_id[p["citation"]["document_id"]] for p in topics[topic]["positions"]
    }
    lines.append(
        f"false contradictions: {len(false)} {sorted(false)}; "
        f"absence check (T3 not in traffic light): {'FAILED' if absence_violation else 'OK'}"
    )

    for topic_name in sorted(false):
        positions = "; ".join(
            f"{key_by_id[p['citation']['document_id']]}: {p['position'].split(': ', 1)[1]}"
            for p in topics[topic_name]["positions"]
        )
        lines.append(f"  false '{topic_name}': {positions}")

    for key, expected in TICKET_PLANTED["inconsistent_checks"].items():
        checks = by_key[key]["analysis"]["incident"]
        got = (
            {
                c["check"].split(":")[0]
                for c in checks["consistency_checks"]
                if c["result"] == "inconsistent"
            }
            if checks
            else set()
        )
        lines.append(
            f"{key} narrative-vs-photo inconsistencies: {len(expected & got)}/{len(expected)} "
            f"found {sorted(got)}"
        )
        if checks:
            photo = by_key[key]["analysis"]["visual_elements"]
            scene = photo[0]["scene"] if photo and photo[0].get("scene") else None
            lines.append(f"  photo scene: {scene}")
    return lines


async def test_ticket_scorecard(live_provider: OllamaProvider, live_settings: Settings) -> None:
    """The M6 ticket scorecard: four synthetic e-report tickets, incident profile."""
    files = [(f"{t.key}.pdf", ticket_pdf(t)) for t in TICKETS]
    job, seconds = await _run(live_provider, live_settings, files, "incident")
    assert job["status"] == "completed", job
    NOTES.append(f"TICKET SCORECARD (report only, {seconds:.0f}s for 4 tickets)")
    NOTES.extend(f"  {line}" for line in score_tickets(job))
