"""Stage 1: per-page extraction without any model.

For every page this produces a ``PageContent`` with the text layer, tables as
markdown, and a decision on whether the page needs visual analysis.

A page needs visual analysis when it has any of:
  (a) a non-decorative embedded image,
  (b) significant vector drawings. Charts are often drawn as vector paths, and
      image extraction returns nothing for them. This is why visual analysis
      renders the whole page instead of sending extracted images
      (DECISIONS D-013),
  (c) a likely-scanned layout: under 50 characters of text, and either a raster
      image covering at least half the page, or other (non-blank) content that
      (a) and (b) did not account for. Blank pages are never sent to the model.

Pages are then ranked by visual area and only the top ``MAX_VISUAL_PAGES_PER_DOC``
are selected; a warning records the cap.

Rendering helpers for stage 2 live here too, with a hard pixel cap so a
maliciously huge page cannot exhaust memory.
"""

import logging
import time

import pymupdf

from app.config import Settings
from app.pipeline.pdf_utils import open_pdf
from app.schemas.common import DocumentWarning, WarningCode
from app.schemas.extraction import ExtractedDocument, PageContent, VisualReason
from app.security.injection import injection_warnings

logger = logging.getLogger(__name__)

# ---- Thresholds (see DECISIONS D-014 for the reasoning) ----
# Images smaller than this in either dimension (pixels) are decorative (logos, icons, rules).
DECORATIVE_MIN_PX = 100
# Visuals covering less than this fraction of the page are decorative.
DECORATIVE_MAX_AREA_RATIO = 0.02
# A cluster of vector drawings is "significant" with at least this many path items...
MIN_DRAWING_ITEMS = 5
# ...covering at least this fraction of the page (same threshold as images).
MIN_DRAWING_AREA_RATIO = 0.02
# Drawings covering nearly the whole page are backgrounds or page borders, not content.
BACKGROUND_AREA_RATIO = 0.9
# A page with fewer non-whitespace text characters than this may be scanned.
SCANNED_TEXT_THRESHOLD = 50
# A low-text page whose largest image covers at least this much of it is a scan.
SCANNED_IMAGE_AREA_RATIO = 0.5
# Margin (pt) around a detected table; drawings touching it are the table's own rules.
TABLE_MARGIN = 8.0
# A detected "table" with fewer non-empty cells than this is treated as a grid
# (for example chart gridlines), not as a data table.
MIN_TABLE_FILL_RATIO = 0.5

# Hard cap on rendered image size: about 2000 x 2000 px. A4 at 150 DPI is
# 1240 x 1754 (2.2 MP), so normal pages are never downscaled.
MAX_RENDER_PIXELS = 4_000_000


# --------------------------------------------------------------------------- public API


def extract_document(data: bytes, settings: Settings) -> ExtractedDocument:
    """Extract every page of an already-validated PDF.

    Args:
        data: PDF bytes that passed stage 0 validation.
        settings: Provides ``MAX_VISUAL_PAGES_PER_DOC``.

    Returns:
        Per-page content, the visual-page selection, and warnings
        (prompt injection, table failures, visual cap).
    """
    started = time.perf_counter()
    warnings: list[DocumentWarning] = []
    pages: list[PageContent] = []

    with open_pdf(data) as doc:
        for index, page in enumerate(doc):
            content, page_warnings = _extract_page(page, index + 1)
            pages.append(content)
            warnings.extend(page_warnings)
        page_count = doc.page_count

    # Untrusted text is scanned after extraction; flagged pages are still analysed.
    scan_input = [(p.page, "\n".join([p.text, *p.tables])) for p in pages]
    injection = injection_warnings(scan_input)
    for w in injection:
        logger.warning(
            "Possible prompt injection",
            extra={"event": "security", "code": w.code.value, "page": w.page},
        )
    warnings.extend(injection)

    cap_warning = _select_visual_pages(pages, settings.max_visual_pages_per_doc)
    if cap_warning:
        warnings.append(cap_warning)

    logger.info(
        "Extraction finished: %d pages, %d visual",
        page_count,
        sum(p.selected_for_visual_analysis for p in pages),
        extra={"stage": "extracting", "duration_ms": round((time.perf_counter() - started) * 1000)},
    )
    return ExtractedDocument(page_count=page_count, pages=pages, warnings=warnings)


def page_has_any_content(page: pymupdf.Page) -> bool:
    """True if the page has any text, image or vector drawing at all.

    Used by validation to detect ``EMPTY_DOCUMENT``. Deliberately lenient: any
    content counts, including decorative content.
    """
    return bool(page.get_text("text").strip() or page.get_image_info() or page.get_drawings())


def render_page_png(data: bytes, page_number: int, dpi: int) -> bytes:
    """Render one page to PNG at ``dpi``, downscaled to at most ``MAX_RENDER_PIXELS``.

    Args:
        data: PDF bytes.
        page_number: 1-based page number.
        dpi: Requested resolution (``RENDER_DPI``).

    Returns:
        PNG-encoded image bytes.
    """
    with open_pdf(data) as doc:
        page = doc[page_number - 1]
        scale = effective_render_scale(page.rect, dpi)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, annots=False)
        return pix.tobytes("png")


def effective_render_scale(rect: pymupdf.Rect, dpi: int) -> float:
    """Zoom factor for rendering ``rect`` at ``dpi`` without exceeding the pixel cap.

    The size is computed *before* rendering, so an oversized page never allocates
    an oversized pixmap.
    """
    scale = dpi / 72.0
    pixels = (rect.width * scale) * (rect.height * scale)
    if pixels > MAX_RENDER_PIXELS:
        scale *= (MAX_RENDER_PIXELS / pixels) ** 0.5
    return scale


# --------------------------------------------------------------------------- per page


def _extract_page(page: pymupdf.Page, number: int) -> tuple[PageContent, list[DocumentWarning]]:
    warnings: list[DocumentWarning] = []
    page_area = abs(page.rect) or 1.0

    text = page.get_text("text")
    text_chars = len("".join(text.split()))

    tables_md, table_rects = [], []
    try:
        tables_md, table_rects = _extract_tables(page)
    except Exception:  # find_tables can fail on unusual layouts; keep the text
        logger.warning(
            "Table extraction failed",
            exc_info=True,
            extra={"event": "table_extraction_failed", "page": number},
        )
        warnings.append(
            DocumentWarning(
                code=WarningCode.TABLE_EXTRACTION_FAILED,
                message="Tables on this page could not be extracted; text was kept.",
                page=number,
            )
        )

    image_infos = page.get_image_info()
    drawings = page.get_drawings()

    image_area = _non_decorative_image_area(page, image_infos)
    drawing_area = _significant_drawing_area(page, drawings, table_rects)

    reasons: list[VisualReason] = []
    if image_area > 0:
        reasons.append("embedded_image")
    if drawing_area > 0:
        reasons.append("vector_drawing")

    likely_scanned = False
    if text_chars < SCANNED_TEXT_THRESHOLD:
        is_blank = not (text_chars or image_infos or drawings)
        # Without the "unexplained" condition, a chart with a short caption would
        # also be labelled "scanned"; the label would be wrong and its rank inflated.
        unexplained = not is_blank and not reasons
        likely_scanned = _largest_image_ratio(page, image_infos) >= SCANNED_IMAGE_AREA_RATIO or (
            unexplained
        )
    if likely_scanned:
        reasons.append("scanned")

    # A scanned page is visual end to end, so it ranks as fully visual.
    ratio = 1.0 if likely_scanned else min(1.0, (image_area + drawing_area) / page_area)

    content = PageContent(
        page=number,
        text=text,
        tables=tables_md,
        needs_visual_analysis=bool(reasons),
        visual_reasons=reasons,
        visual_area_ratio=round(ratio, 4),
    )
    return content, warnings


def _extract_tables(page: pymupdf.Page) -> tuple[list[str], list[pymupdf.Rect]]:
    """Return markdown for real data tables and the rects of those tables.

    Grids whose cells are mostly empty (for example chart gridlines) are skipped,
    so they stay eligible for vector-drawing detection.
    """
    markdown: list[str] = []
    rects: list[pymupdf.Rect] = []
    for table in page.find_tables().tables:
        cells = [c for row in table.extract() for c in row]
        filled = sum(1 for c in cells if c and str(c).strip())
        if not cells or filled / len(cells) < MIN_TABLE_FILL_RATIO:
            continue
        markdown.append(table.to_markdown().strip())
        rects.append(pymupdf.Rect(table.bbox))
    return markdown, rects


def _non_decorative_image_area(page: pymupdf.Page, image_infos: list[dict]) -> float:
    """Total on-page area (pt^2) of images that are not decorative."""
    page_rect = page.rect
    page_area = abs(page_rect) or 1.0
    total = 0.0
    for info in image_infos:
        if info.get("width", 0) < DECORATIVE_MIN_PX or info.get("height", 0) < DECORATIVE_MIN_PX:
            continue  # icon / logo / thin rule
        visible = pymupdf.Rect(info["bbox"]) & page_rect  # clip parts outside the page
        area = abs(visible)
        if area / page_area < DECORATIVE_MAX_AREA_RATIO:
            continue
        total += area
    return min(total, page_area)


def _largest_image_ratio(page: pymupdf.Page, image_infos: list[dict]) -> float:
    """Fraction of the page covered by its single largest image (0 if none)."""
    page_rect = page.rect
    page_area = abs(page_rect) or 1.0
    areas = [abs(pymupdf.Rect(info["bbox"]) & page_rect) for info in image_infos]
    return max(areas, default=0.0) / page_area


def _significant_drawing_area(
    page: pymupdf.Page, drawings: list[dict], table_rects: list[pymupdf.Rect]
) -> float:
    """Area (pt^2) of vector-drawing clusters that look like charts or diagrams.

    Steps:
      1. Drop page-sized backgrounds/borders and the ruling lines of detected tables.
      2. Cluster nearby paths (``Page.cluster_drawings``).
      3. Keep clusters with enough path items and enough area.
    """
    page_area = abs(page.rect) or 1.0
    near_tables = [_padded(r, TABLE_MARGIN) for r in table_rects]

    candidates = []
    for d in drawings:
        rect = _padded(d["rect"])
        if abs(d["rect"]) / page_area >= BACKGROUND_AREA_RATIO:
            continue
        if any(rect.intersects(t) for t in near_tables):
            continue
        candidates.append(d)
    if not candidates:
        return 0.0

    total = 0.0
    for cluster in page.cluster_drawings(drawings=candidates):
        cluster = pymupdf.Rect(cluster)
        items = sum(
            len(d.get("items", ())) for d in candidates if _padded(d["rect"]).intersects(cluster)
        )
        if items >= MIN_DRAWING_ITEMS and abs(cluster) / page_area >= MIN_DRAWING_AREA_RATIO:
            total += abs(cluster)
    return min(total, page_area)


def _padded(rect: pymupdf.Rect, pad: float = 1.0) -> pymupdf.Rect:
    """Grow a rect slightly so zero-height lines still register as intersecting."""
    return pymupdf.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)


# --------------------------------------------------------------------------- selection


def _select_visual_pages(pages: list[PageContent], cap: int) -> DocumentWarning | None:
    """Mark up to ``cap`` pages for visual analysis, largest visual area first.

    Mutates ``pages`` in place. Returns a ``VISUAL_PAGES_CAPPED`` warning when
    some pages that needed visual analysis were left out.
    """
    needing = [p for p in pages if p.needs_visual_analysis]
    # Largest visual area first; ties go to the earlier page.
    ranked = sorted(needing, key=lambda p: (-p.visual_area_ratio, p.page))
    for p in ranked[:cap]:
        p.selected_for_visual_analysis = True

    skipped = sorted(p.page for p in ranked[cap:])
    if not skipped:
        return None
    return DocumentWarning(
        code=WarningCode.VISUAL_PAGES_CAPPED,
        message=(
            f"{len(needing)} pages contain visuals but only {cap} were analysed "
            f"(those with the largest visual area). Not analysed: pages "
            f"{', '.join(map(str, skipped))}."
        ),
    )
