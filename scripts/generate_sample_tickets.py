"""Generate the synthetic incident tickets in ``sample_pdfs/tickets/``.

The tickets come from ``backend/tests/ticket_factory.py`` (the same builders the
tests and the live scorecard use). Four e-report forms from a fictional portal:
three reports of one incident with planted contradictions, and one unrelated
incident whose narrative contradicts its own photo. See ``sample_pdfs/README.md``.

Usage (from the repo root, with the backend environment active):

    python scripts/generate_sample_tickets.py

After writing, each file is checked: it must pass upload validation, and its
form fields must be readable from the text layer.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
OUTPUT_DIR = REPO_ROOT / "sample_pdfs" / "tickets"

sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.pipeline.extraction import extract_document  # noqa: E402
from app.pipeline.validation import validate_file  # noqa: E402
from app.schemas.validation import AcceptedFile  # noqa: E402
from tests.ticket_factory import TICKETS, ticket_pdf  # noqa: E402


def main() -> int:
    """Write every ticket, validate it, and report."""
    settings = Settings(llm_provider="mock", log_level="ERROR")
    configure_logging("ERROR")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0
    for ticket in TICKETS:
        name = f"{ticket.key}.pdf"
        data = ticket_pdf(ticket)
        (OUTPUT_DIR / name).write_bytes(data)
        result = validate_file(name, data, settings)
        extracted = extract_document(data, settings)
        text = extracted.pages[0].text
        readable = ticket.reference in text and ticket.location in text
        ok = isinstance(result, AcceptedFile) and readable
        failures += not ok
        print(
            f"[{'ok' if ok else 'FAIL'}] {name:<26} pages={extracted.page_count} "
            f"visual_pages={extracted.visual_pages} "
            f"removed_footer={bool(extracted.boilerplate_lines)}"
        )
    print(f"\nWrote {len(TICKETS)} tickets to {OUTPUT_DIR.relative_to(REPO_ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
