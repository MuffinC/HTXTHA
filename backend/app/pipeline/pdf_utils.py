"""Opening PDFs safely with PyMuPDF.

One place to open documents so every stage gets the same behaviour:
  * MuPDF's own error/warning printing to stderr is disabled. It would bypass
    the JSON logger and could echo fragments of the file.
  * Any failure to parse becomes ``PdfOpenError``, which callers map to
    ``CORRUPT_PDF``.

PyMuPDF (AGPL-3.0) is used only in this module, ``pipeline/validation.py``,
``pipeline/extraction.py`` and ``security/pdf_safety.py``. See DECISIONS D-012.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pymupdf

# Silence MuPDF's direct stderr output for the whole process.
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)


class PdfOpenError(Exception):
    """The bytes could not be parsed as a PDF."""


@contextmanager
def open_pdf(data: bytes) -> Iterator[pymupdf.Document]:
    """Open PDF bytes and guarantee the document is closed afterwards.

    Args:
        data: Raw file content. The caller has already checked the magic bytes.

    Yields:
        The open ``pymupdf.Document``.

    Raises:
        PdfOpenError: If MuPDF cannot open the data as a PDF.
    """
    try:
        # filetype="pdf" stops MuPDF guessing other formats (XPS, EPUB, images).
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # MuPDF raises several exception types for bad input
        raise PdfOpenError(str(exc)) from exc
    try:
        yield doc
    finally:
        doc.close()
