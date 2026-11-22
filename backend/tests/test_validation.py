"""Stage 0 validation: one test per error code plus policy and filename handling."""

from collections.abc import Callable

import pymupdf
import pytest

from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.pipeline.validation import check_file_count, sanitize_filename, validate_file
from app.schemas.common import WarningCode
from app.schemas.validation import AcceptedFile, RejectedFile
from tests import pdf_factory as pdfs


def _rejected(result: object, code: ErrorCode) -> RejectedFile:
    assert isinstance(result, RejectedFile), f"expected rejection {code}, got {result!r}"
    assert result.code == code
    assert result.message  # always a human-readable reason
    return result


# --------------------------------------------------------------------------- accepted


def test_valid_pdf_is_accepted(settings: Settings) -> None:
    data = pdfs.valid_text_pdf(pages=2)
    result = validate_file("report.pdf", data, settings)

    assert isinstance(result, AcceptedFile)
    assert result.page_count == 2
    assert result.size_bytes == len(data)
    assert result.warnings == []


def test_extension_is_not_trusted_content_is(settings: Settings) -> None:
    # A real PDF with a misleading name is accepted; a text file named .pdf is not.
    assert isinstance(validate_file("notes.txt", pdfs.valid_text_pdf(), settings), AcceptedFile)
    _rejected(validate_file("report.pdf", pdfs.fake_pdf(), settings), ErrorCode.UNSUPPORTED_TYPE)


def test_prompt_injection_pdf_is_accepted_at_validation(settings: Settings) -> None:
    # Injection is a content warning raised during extraction, not a rejection.
    assert isinstance(validate_file("x.pdf", pdfs.prompt_injection_pdf(), settings), AcceptedFile)


def test_owner_password_only_pdf_is_accepted(settings: Settings) -> None:
    # Encrypted with permissions only (no password needed to open), so readable.
    doc = pymupdf.open(stream=pdfs.valid_text_pdf(), filetype="pdf")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="")
    doc.close()

    assert isinstance(validate_file("x.pdf", data, settings), AcceptedFile)


def test_benign_open_action_is_not_active_content(settings: Settings) -> None:
    result = validate_file("x.pdf", pdfs.goto_open_action_pdf(), settings)
    assert isinstance(result, AcceptedFile)


# --------------------------------------------------------------------------- rejected, by code


def test_unsupported_type(settings: Settings) -> None:
    _rejected(validate_file("fake.pdf", pdfs.fake_pdf(), settings), ErrorCode.UNSUPPORTED_TYPE)


def test_wrapped_pdf_is_accepted_with_the_ignored_bytes_reported(settings: Settings) -> None:
    # D-074: a multipart envelope before %PDF- (as NHTSA serves its reports).
    inner = pdfs.valid_text_pdf()
    data = pdfs.multipart_wrapped_pdf(inner)
    offset = data.index(b"%PDF-")

    result = validate_file("x.pdf", data, settings)

    assert isinstance(result, AcceptedFile)
    assert result.header_offset == offset > 0
    assert data[result.header_offset :].startswith(inner)  # what the caller stores
    [warning] = result.warnings
    assert warning.code is WarningCode.LEADING_BYTES_IGNORED
    assert f"{offset} bytes before the PDF header were ignored" in warning.message


def test_header_at_the_start_needs_no_warning(settings: Settings) -> None:
    result = validate_file("x.pdf", pdfs.valid_text_pdf(), settings)
    assert isinstance(result, AcceptedFile)
    assert result.header_offset == 0 and result.warnings == []


def test_header_must_start_within_the_first_1024_bytes(settings: Settings) -> None:
    inside = b"x" * 1023 + pdfs.valid_text_pdf()  # header starts at byte 1023
    outside = b"x" * 1024 + pdfs.valid_text_pdf()  # header starts at byte 1024
    assert isinstance(validate_file("x.pdf", inside, settings), AcceptedFile)
    _rejected(validate_file("x.pdf", outside, settings), ErrorCode.UNSUPPORTED_TYPE)


def test_file_too_large(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(max_file_mb=1)
    data = b"%PDF-1.7\n" + b"0" * (1024 * 1024)  # just over 1 MB; size is checked first

    result = _rejected(validate_file("big.pdf", data, settings), ErrorCode.FILE_TOO_LARGE)
    assert "1 MB" in result.message


def test_too_many_pages_default_limit(settings: Settings) -> None:
    result = validate_file("long.pdf", pdfs.too_many_pages_pdf(61), settings)
    assert "61" in _rejected(result, ErrorCode.TOO_MANY_PAGES).message


def test_too_many_pages_respects_setting(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(max_pages=2)
    _rejected(validate_file("x.pdf", pdfs.valid_text_pdf(3), settings), ErrorCode.TOO_MANY_PAGES)
    assert isinstance(validate_file("x.pdf", pdfs.valid_text_pdf(2), settings), AcceptedFile)


def test_corrupt_pdf(settings: Settings) -> None:
    _rejected(validate_file("bad.pdf", pdfs.corrupt_pdf(), settings), ErrorCode.CORRUPT_PDF)


def test_encrypted_pdf(settings: Settings) -> None:
    _rejected(validate_file("locked.pdf", pdfs.encrypted_pdf(), settings), ErrorCode.ENCRYPTED_PDF)


def test_empty_document(settings: Settings) -> None:
    _rejected(validate_file("blank.pdf", pdfs.empty_pdf(), settings), ErrorCode.EMPTY_DOCUMENT)


@pytest.mark.parametrize(
    ("builder", "label"),
    [
        (pdfs.javascript_pdf, "JavaScript"),
        (pdfs.launch_action_pdf, "launch action"),
    ],
)
def test_executable_active_content_rejected_by_default(
    settings: Settings, builder: Callable[[], bytes], label: str
) -> None:
    result = _rejected(validate_file("x.pdf", builder(), settings), ErrorCode.ACTIVE_CONTENT)
    assert label in result.message


def test_embedded_file_accepted_with_warning_by_default(settings: Settings) -> None:
    # D-075: attachments are never extracted or opened, so the default is warn.
    result = validate_file("x.pdf", pdfs.embedded_file_pdf(), settings)

    assert isinstance(result, AcceptedFile)
    [warning] = result.warnings
    assert warning.code is WarningCode.ACTIVE_CONTENT
    assert "embedded file" in warning.message and "not executed or extracted" in warning.message


def test_embedded_file_rejected_when_policy_is_reject(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(embedded_file_policy="reject")
    result = _rejected(
        validate_file("x.pdf", pdfs.embedded_file_pdf(), settings), ErrorCode.ACTIVE_CONTENT
    )
    assert "embedded file" in result.message


def test_active_content_warn_policy_accepts_with_warning(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(active_content_policy="warn")
    result = validate_file("x.pdf", pdfs.javascript_pdf(), settings)

    assert isinstance(result, AcceptedFile)
    assert [w.code for w in result.warnings] == [WarningCode.ACTIVE_CONTENT]


def test_too_many_files(settings: Settings) -> None:
    check_file_count(settings.max_files, settings)  # at the limit: fine

    with pytest.raises(ApiError) as excinfo:
        check_file_count(settings.max_files + 1, settings)

    assert excinfo.value.code == ErrorCode.TOO_MANY_FILES
    assert excinfo.value.status_code == 400
    assert excinfo.value.details == {"max_files": 10, "received": 11}


def test_rejection_logs_code_but_not_filename(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    validate_file("S1234567D_private_name.pdf", pdfs.encrypted_pdf(), settings)

    assert any(getattr(r, "code", None) == "ENCRYPTED_PDF" for r in caplog.records)
    assert "private_name" not in caplog.text


# --------------------------------------------------------------------------- filenames


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\x\\Desktop\\ticket 1.pdf", "ticket 1.pdf"),
        ("evil\u202egnp.pdf", "evilgnp.pdf"),  # right-to-left override removed
        ("tab\tand\nnewline.pdf", "tabandnewline.pdf"),
        ("  spaced   name .pdf  ", "spaced name .pdf"),
        ("", "document.pdf"),
        (None, "document.pdf"),
        ("...", "document.pdf"),
    ],
)
def test_sanitize_filename(raw: str | None, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_caps_length_and_keeps_extension() -> None:
    name = sanitize_filename("a" * 500 + ".pdf")
    assert len(name) == 200
    assert name.endswith(".pdf")


def test_text_that_mentions_the_header_is_not_a_pdf(settings: Settings) -> None:
    # The fake PDF's text contains "%PDF-." but no versioned header.
    data = b"Notes about the format: every file starts with %PDF- and a version.\n"
    _rejected(validate_file("x.pdf", data, settings), ErrorCode.UNSUPPORTED_TYPE)
