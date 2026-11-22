"""Stage 0: synchronous file validation at upload time.

Each uploaded file is checked independently. A rejected file never stops the
other files in the same upload (CLAUDE.md section 6). Checks run cheapest-first
and stop at the first failure:

    size -> magic bytes -> parse -> encryption -> page count -> active content -> emptiness

The PDF header may start anywhere in the first 1024 bytes, as PDF viewers allow
(D-074). Bytes before it are ignored: validation runs on the PDF from its header,
the caller stores only those bytes, and a warning says how many were dropped.

The user's filename is only *displayed* (after sanitising) and never used in a
filesystem path. Storage under a generated UUID is added with job storage in M3.
"""

import logging
import re
import unicodedata

import pymupdf

from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.pipeline.extraction import page_has_any_content
from app.pipeline.pdf_utils import PdfOpenError, open_pdf
from app.schemas.common import DocumentWarning, WarningCode
from app.schemas.validation import AcceptedFile, FileValidationResult, RejectedFile
from app.security.pdf_safety import describe_findings, find_active_content

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
#: The header must start within this many bytes (the window PDF viewers accept).
HEADER_SEARCH_BYTES = 1024
# A real header has a version ("%PDF-1.7", "%PDF-2.0"). Requiring it stops a text file
# that merely mentions "%PDF-" from being taken for a PDF.
_PDF_HEADER = re.compile(rb"%PDF-\d\.\d")
#: Active-content kinds that can execute; embedded files are governed separately.
_EXECUTABLE_KINDS = {"javascript", "launch_action"}
MAX_DISPLAY_FILENAME = 200
DEFAULT_FILENAME = "document.pdf"

# Control characters plus bidi overrides/isolates (used for "gpj.exe"-style spoofing).
_UNSAFE_FILENAME_CHARS = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]")


class _Rejection(Exception):
    """Internal: carries the rejection reason out of the check sequence."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def sanitize_filename(name: str | None) -> str:
    """Make a user-supplied filename safe to display.

    Keeps only the final path component (handles ``/`` and ``\\``), normalises
    Unicode, removes control and bidi characters, collapses whitespace and caps
    the length while keeping the extension.

    Args:
        name: Filename as sent by the client (may be ``None`` or empty).

    Returns:
        A display-safe filename, or ``"document.pdf"`` if nothing usable remains.
    """
    if not name:
        return DEFAULT_FILENAME
    name = unicodedata.normalize("NFKC", name)
    name = re.split(r"[\\/]", name)[-1]
    name = _UNSAFE_FILENAME_CHARS.sub("", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if not name:
        return DEFAULT_FILENAME
    if len(name) > MAX_DISPLAY_FILENAME:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 10:
            name = stem[: MAX_DISPLAY_FILENAME - len(ext) - 1] + "." + ext
        else:
            name = name[:MAX_DISPLAY_FILENAME]
    return name


def check_file_count(count: int, settings: Settings) -> None:
    """Reject the whole upload if it has more than ``MAX_FILES`` files.

    Raises:
        ApiError: ``TOO_MANY_FILES`` (HTTP 400).
    """
    if count > settings.max_files:
        raise ApiError(
            ErrorCode.TOO_MANY_FILES,
            f"{count} files were uploaded; the limit is {settings.max_files} per upload.",
            status_code=400,
            details={"max_files": settings.max_files, "received": count},
        )


def validate_file(filename: str | None, data: bytes, settings: Settings) -> FileValidationResult:
    """Validate one uploaded file.

    Args:
        filename: Client-supplied filename (display only).
        data: Complete file content.
        settings: Limits and policies.

    Returns:
        ``AcceptedFile`` (possibly with warnings) or ``RejectedFile`` with an error code.
    """
    display_name = sanitize_filename(filename)
    try:
        page_count, warnings, offset = _run_checks(data, settings)
    except _Rejection as rejection:
        # Security-relevant rejections at WARNING, the rest at INFO. Filenames are
        # not logged: they can contain personal data (see ASSUMPTIONS A-105).
        level = logging.WARNING if rejection.code == ErrorCode.ACTIVE_CONTENT else logging.INFO
        logger.log(
            level,
            "File rejected",
            extra={"event": "validation_rejected", "code": rejection.code.value},
        )
        return RejectedFile(filename=display_name, code=rejection.code, message=rejection.message)

    return AcceptedFile(
        filename=display_name,
        size_bytes=len(data) - offset,
        page_count=page_count,
        warnings=warnings,
        header_offset=offset,
    )


def find_pdf_header(data: bytes) -> int:
    """Offset of a PDF header (``%PDF-`` plus a version) starting in the first 1024 bytes.

    Returns:
        The offset, or -1 if there is no header there.
    """
    match = _PDF_HEADER.search(data, 0, HEADER_SEARCH_BYTES + len(b"%PDF-1.7"))
    return match.start() if match and match.start() < HEADER_SEARCH_BYTES else -1


def _run_checks(data: bytes, settings: Settings) -> tuple[int, list[DocumentWarning], int]:
    """Run all checks in order.

    Returns:
        ``(page_count, warnings, header_offset)``.

    Raises:
        _Rejection: On the first failed check.
    """
    max_bytes = settings.max_file_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise _Rejection(
            ErrorCode.FILE_TOO_LARGE,
            f"File is {len(data) / (1024 * 1024):.1f} MB; the limit is {settings.max_file_mb} MB.",
        )

    # The header may start within the first 1024 bytes (D-074): real downloads can carry a
    # wrapper before it (NHTSA serves PDFs inside an HTTP multipart envelope). The bytes
    # before it are dropped, so whatever they were (a wrapper, or the other half of a
    # polyglot) is never stored or parsed.
    offset = find_pdf_header(data)
    if offset < 0:
        raise _Rejection(
            ErrorCode.UNSUPPORTED_TYPE,
            "This file is not a PDF (no PDF header in its first 1024 bytes), "
            "whatever its extension says. Only PDF files are supported.",
        )
    pdf = data[offset:]
    warnings: list[DocumentWarning] = []
    if offset:
        logger.info(
            "Bytes before the PDF header ignored",
            extra={"event": "leading_bytes_ignored", "count": offset},
        )
        warnings.append(
            DocumentWarning(
                code=WarningCode.LEADING_BYTES_IGNORED,
                message=(
                    f"{offset} bytes before the PDF header were ignored (for example a "
                    "download wrapper). The PDF itself was analysed from its header."
                ),
            )
        )

    try:
        with open_pdf(pdf) as doc:
            page_count, doc_warnings = _check_document(doc, settings)
            return page_count, warnings + doc_warnings, offset
    except PdfOpenError as exc:
        raise _Rejection(
            ErrorCode.CORRUPT_PDF, "The PDF is damaged or unreadable and could not be opened."
        ) from exc


def _check_document(doc: pymupdf.Document, settings: Settings) -> tuple[int, list[DocumentWarning]]:
    """Checks that need the parsed document."""
    warnings: list[DocumentWarning] = []

    # ASSUMPTION: "password-protected" means a password is needed to open the file.
    # PDFs that are encrypted only with an owner password (permissions such as
    # "no printing") open without one, are readable, and are accepted.
    if doc.needs_pass:
        raise _Rejection(
            ErrorCode.ENCRYPTED_PDF,
            "The PDF is password-protected. Remove the password and upload it again.",
        )

    page_count = doc.page_count
    if page_count == 0:
        raise _Rejection(ErrorCode.CORRUPT_PDF, "The PDF has no pages.")
    if page_count > settings.max_pages:
        raise _Rejection(
            ErrorCode.TOO_MANY_PAGES,
            f"The PDF has {page_count} pages; the limit is {settings.max_pages}.",
        )

    findings = find_active_content(doc)
    if findings:
        summary = describe_findings(findings)
        kinds = ",".join(f.kind for f in findings)
        logger.warning(
            "Active content detected: %s",
            kinds,
            extra={"event": "security", "code": ErrorCode.ACTIVE_CONTENT.value},
        )
        # JavaScript and launch actions can execute in a viewer; embedded files are only
        # dangerous if someone opens them, and they are never extracted here (D-075).
        rejected = [
            f
            for f in findings
            if (f.kind in _EXECUTABLE_KINDS and settings.active_content_policy == "reject")
            or (f.kind == "embedded_file" and settings.embedded_file_policy == "reject")
        ]
        if rejected:
            raise _Rejection(
                ErrorCode.ACTIVE_CONTENT,
                f"The PDF contains active content ({describe_findings(rejected)}), "
                "which is not allowed.",
            )
        warnings.append(
            DocumentWarning(
                code=WarningCode.ACTIVE_CONTENT,
                message=(
                    f"The PDF contains active content ({summary}). It was not executed or "
                    "extracted. Take care when opening the original file."
                ),
            )
        )

    if not any(page_has_any_content(page) for page in doc):
        raise _Rejection(
            ErrorCode.EMPTY_DOCUMENT, "The PDF has no text and no visual content to analyse."
        )

    return page_count, warnings
