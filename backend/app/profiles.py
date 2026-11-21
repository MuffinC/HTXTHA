"""Analysis profiles offered by ``GET /api/profiles``.

A profile picks the prompts and the schema extension. Profiles are listed
before they are implemented (``available=False``) so the frontend can show what
is coming, but ``POST /api/jobs`` only accepts available ones.
"""

from app.schemas.jobs import ProfileInfo

PROFILES: list[ProfileInfo] = [
    ProfileInfo(
        id="general",
        name="General",
        description="Any document: summary, topics, key entities and notable points with page "
        "references, plus descriptions of photos, charts and tables.",
        available=True,
    ),
    ProfileInfo(
        id="incident",
        name="Incident",
        description="Incident tickets and reports: the reporter's facts with page references, "
        "checks against their own photos, and same-incident grouping with contradictions "
        "across reports.",
        available=True,
    ),
    ProfileInfo(
        id="statistical",
        name="Statistical",
        description="Statistical reports: reporting period, key figures and trends.",
        available=False,  # statistical extension arrives in M8
    ),
]


def is_available(profile_id: str) -> bool:
    """True if jobs can be created with this profile."""
    return any(p.id == profile_id and p.available for p in PROFILES)
