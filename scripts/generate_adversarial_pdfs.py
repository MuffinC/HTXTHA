"""Generate the security / edge-case demo PDFs in ``sample_pdfs/adversarial/``.

The files come from the same builders the test-suite uses
(``backend/tests/pdf_factory.py``), so the demo files and the tests cannot
drift apart. After writing, each file is run through the real validation stage
and the script fails if any result differs from the expected one.

Usage (from the repo root, with the backend environment active):

    python scripts/generate_adversarial_pdfs.py

Re-running overwrites the files. Output is byte-identical across runs (fixed
metadata, ``reproducible=True``, no random trailer ``/ID``), except the encrypted
file, whose AES encryption uses a random salt and IV by design.
"""

import sys
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
OUTPUT_DIR = REPO_ROOT / "sample_pdfs" / "adversarial"

# Make the backend package importable without installing it.
sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.pipeline.extraction import extract_document  # noqa: E402
from app.pipeline.validation import validate_file  # noqa: E402
from app.schemas.validation import AcceptedFile  # noqa: E402
from tests import pdf_factory  # noqa: E402

# filename -> (builder, expected validation outcome)
# "ACCEPTED" means the file passes validation; other values are rejection codes.
SAMPLES: dict[str, tuple[Callable[[], bytes], str]] = {
    "prompt_injection.pdf": (pdf_factory.prompt_injection_pdf, "ACCEPTED"),
    "vector_chart.pdf": (pdf_factory.vector_chart_pdf, "ACCEPTED"),
    "fake_pdf.pdf": (pdf_factory.fake_pdf, "UNSUPPORTED_TYPE"),
    "encrypted.pdf": (pdf_factory.encrypted_pdf, "ENCRYPTED_PDF"),
    "javascript.pdf": (pdf_factory.javascript_pdf, "ACTIVE_CONTENT"),
    "too_many_pages.pdf": (pdf_factory.too_many_pages_pdf, "TOO_MANY_PAGES"),
    "empty.pdf": (pdf_factory.empty_pdf, "EMPTY_DOCUMENT"),
    "corrupt.pdf": (pdf_factory.corrupt_pdf, "CORRUPT_PDF"),
}


def main() -> int:
    """Write every sample, validate it with default settings, and report."""
    # Default limits and policies, exactly as a fresh deployment would use them.
    settings = Settings(llm_provider="mock", log_level="ERROR")
    # The expected security warnings would otherwise clutter the report below.
    configure_logging("ERROR")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0

    for filename, (builder, expected) in SAMPLES.items():
        data = builder()
        (OUTPUT_DIR / filename).write_bytes(data)

        result = validate_file(filename, data, settings)
        actual = "ACCEPTED" if isinstance(result, AcceptedFile) else result.code.value
        notes = ""
        if isinstance(result, AcceptedFile):
            extracted = extract_document(data, settings)
            warnings = sorted({f"{w.code.value}@p{w.page}" for w in extracted.warnings})
            notes = f"visual pages={extracted.visual_pages} warnings={warnings}"

        status = "ok" if actual == expected else "MISMATCH"
        failures += actual != expected
        print(f"[{status}] {filename:<22} expected={expected:<16} actual={actual:<16} {notes}")

    print(f"\nWrote {len(SAMPLES)} files to {OUTPUT_DIR.relative_to(REPO_ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
