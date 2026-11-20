"""Stage 1 extraction: text, tables, decorative filtering, scanned and vector-drawing detection."""

from collections.abc import Callable

import pymupdf
import pytest

from app.config import Settings
from app.pipeline.extraction import (
    MAX_RENDER_PIXELS,
    extract_document,
    page_has_any_content,
    render_page_png,
)
from app.schemas.common import WarningCode
from tests import pdf_factory as pdfs


def _only_page(data: bytes, settings: Settings):  # noqa: ANN202 - returns PageContent
    doc = extract_document(data, settings)
    assert doc.page_count == 1
    return doc.pages[0]


# --------------------------------------------------------------------------- text and tables


def test_text_only_page(settings: Settings) -> None:
    page = _only_page(pdfs.valid_text_pdf(), settings)

    assert "two cars collide" in page.text
    assert page.page == 1
    assert page.tables == []
    assert page.needs_visual_analysis is False
    assert page.visual_reasons == []


def test_table_extracted_as_markdown_and_not_treated_as_drawing(settings: Settings) -> None:
    page = _only_page(pdfs.table_pdf(), settings)

    assert len(page.tables) == 1
    assert "|Car A|White|Front|" in page.tables[0]
    # The table's ruling lines are vector paths, but they belong to the table.
    assert page.needs_visual_analysis is False


# --------------------------------------------------------------------------- images


def test_decorative_logo_is_ignored(settings: Settings) -> None:
    page = _only_page(pdfs.decorative_logo_pdf(), settings)
    assert page.needs_visual_analysis is False


def test_large_photo_needs_visual_analysis(settings: Settings) -> None:
    page = _only_page(pdfs.photo_pdf(), settings)

    assert page.needs_visual_analysis is True
    assert page.visual_reasons == ["embedded_image"]
    assert 0.2 < page.visual_area_ratio < 0.4  # about a third of the page
    assert page.selected_for_visual_analysis is True


def test_scanned_page_detected(settings: Settings) -> None:
    page = _only_page(pdfs.scanned_pdf(), settings)

    assert page.text.strip() == ""
    assert "scanned" in page.visual_reasons
    assert page.visual_area_ratio == 1.0


def test_low_text_page_with_unexplained_content_is_flagged_scanned(settings: Settings) -> None:
    # Rule (c) fallback: almost no text and only content the image/drawing rules
    # ignore (here a small image). The page may hold something the text layer
    # misses, so it is sent for visual analysis.
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Annex B", fontsize=14)
    page.insert_image(pymupdf.Rect(72, 100, 112, 140), pixmap=pdfs.solid_pixmap(64, 64, (0, 0, 0)))
    data = doc.tobytes()
    doc.close()

    assert _only_page(data, settings).visual_reasons == ["scanned"]


def test_blank_page_is_not_flagged_as_scanned(settings: Settings) -> None:
    # A blank page between content pages must not cost a vision call.
    doc = pymupdf.open(stream=pdfs.valid_text_pdf(), filetype="pdf")
    doc.new_page()
    data = doc.tobytes()
    doc.close()

    result = extract_document(data, settings)
    assert [p.needs_visual_analysis for p in result.pages] == [False, False]


# --------------------------------------------------------------------------- vector drawings
# Charts are often pure vector paths. Image extraction returns nothing for them,
# which is why stage 2 renders whole pages instead of sending extracted images.


def test_vector_chart_has_no_embedded_images(settings: Settings) -> None:
    """Precondition: the chart fixture really has no raster images to extract."""
    doc = pymupdf.open(stream=pdfs.vector_chart_pdf(), filetype="pdf")
    try:
        assert doc[0].get_image_info() == []
        assert doc[0].get_images() == []
        assert len(doc[0].get_drawings()) >= 10
    finally:
        doc.close()


def test_vector_chart_needs_visual_analysis(settings: Settings) -> None:
    page = _only_page(pdfs.vector_chart_pdf(), settings)

    assert page.needs_visual_analysis is True
    assert page.visual_reasons == ["vector_drawing"]  # not via images, not via "scanned"
    assert page.visual_area_ratio > 0.1
    assert page.selected_for_visual_analysis is True
    assert page.tables == []  # the gridlines are not mistaken for a data table


def _gridded_scatter_chart() -> bytes:
    """Scatter chart on a full 7x6 grid with 8 data-point labels inside grid cells.

    A scatter series is used because PyMuPDF's table finder sees this layout as a
    table. (A diagonal line series or bars break up the grid and it does not.)
    """
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Figure 2: response times (fictional)", fontsize=12)
    left, top, col_w, row_h, cols, rows = 80, 100, 60, 50, 7, 6
    for c in range(cols + 1):
        x = left + c * col_w
        page.draw_line((x, top), (x, top + rows * row_h), color=(0.7, 0.7, 0.7), width=0.5)
    for r in range(rows + 1):
        y = top + r * row_h
        page.draw_line((left, y), (left + cols * col_w, y), color=(0.7, 0.7, 0.7), width=0.5)
    points = [(110, 330), (170, 270), (230, 290), (290, 180), (350, 210), (410, 130), (470, 150)]
    for point in points:
        page.draw_circle(point, 4, color=None, fill=(0.8, 0.1, 0.1))
    # Data labels sit inside grid cells, which is what makes find_tables see a table.
    labels = [(0, 0), (1, 2), (2, 4), (3, 6), (4, 1), (5, 3), (2, 5), (4, 6)]
    for i, (r, c) in enumerate(labels):
        page.insert_text((left + c * col_w + 5, top + r * row_h + 30), str(80 + i * 7), fontsize=8)
    data = doc.tobytes()
    doc.close()
    return data


def test_vector_chart_with_full_grid_is_not_swallowed_by_table_detection(
    settings: Settings,
) -> None:
    """A chart on a full grid with data labels looks like a sparse table.

    ``find_tables`` reports it as a table, so without the fill-ratio filter its
    paths would be excluded as "table rules" and the chart would be missed.
    """
    data = _gridded_scatter_chart()
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        # Precondition: PyMuPDF really does mistake this chart for a table.
        assert len(doc[0].find_tables().tables) == 1
    finally:
        doc.close()

    result = _only_page(data, settings)
    assert result.tables == []  # rejected as a table: 8 of 42 cells filled
    assert result.visual_reasons == ["vector_drawing"]


def test_simple_rules_are_not_significant_drawings(settings: Settings) -> None:
    """Header/footer rules and a single border box are layout, not charts."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_line((50, 60), (545, 60), width=0.5)
    page.draw_line((50, 790), (545, 790), width=0.5)
    page.draw_rect(pymupdf.Rect(60, 100, 535, 300), width=0.8)
    page.insert_textbox(pymupdf.Rect(70, 110, 525, 290), " ".join(pdfs.INCIDENT_TEXT))
    data = doc.tobytes()
    doc.close()

    assert _only_page(data, settings).needs_visual_analysis is False


# --------------------------------------------------------------------------- visual page cap


def test_visual_cap_keeps_largest_pages_and_warns(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(max_visual_pages_per_doc=3)
    result = extract_document(pdfs.many_visual_pages_pdf(5), settings)

    # Later pages have larger photos, so pages 3-5 win.
    assert result.visual_pages == [3, 4, 5]
    assert all(p.needs_visual_analysis for p in result.pages)  # detection is unchanged
    capped = [w for w in result.warnings if w.code == WarningCode.VISUAL_PAGES_CAPPED]
    assert len(capped) == 1
    assert "pages 1, 2" in capped[0].message


def test_no_warning_when_under_cap(settings: Settings) -> None:
    result = extract_document(pdfs.many_visual_pages_pdf(3), settings)
    assert result.visual_pages == [1, 2, 3]
    assert not any(w.code == WarningCode.VISUAL_PAGES_CAPPED for w in result.warnings)


def test_visual_cap_of_zero_disables_visual_analysis(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(max_visual_pages_per_doc=0)
    result = extract_document(pdfs.many_visual_pages_pdf(2), settings)
    assert result.visual_pages == []


# --------------------------------------------------------------------------- security in extraction


def test_injection_warnings_attached_with_page_numbers(settings: Settings) -> None:
    result = extract_document(pdfs.prompt_injection_pdf(), settings)

    flagged = [w.page for w in result.warnings if w.code == WarningCode.INJECTION_SUSPECTED]
    # Page 1: visible injection. Page 2: hidden white 1-pt text, invisible to a reader.
    assert flagged == [1, 2]
    # The content is still extracted and analysed as data.
    assert "Ignore all previous instructions" in result.pages[0].text


def test_clean_document_has_no_injection_warning(settings: Settings) -> None:
    result = extract_document(pdfs.valid_text_pdf(), settings)
    assert result.warnings == []


# --------------------------------------------------------------------------- rendering


def _png_size(png: bytes) -> tuple[int, int]:
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    pix = pymupdf.Pixmap(png)
    return pix.width, pix.height


def test_render_a4_at_150_dpi() -> None:
    width, height = _png_size(render_page_png(pdfs.vector_chart_pdf(), 1, dpi=150))
    assert (width, height) == pytest.approx((1240, 1754), abs=2)


def test_render_huge_page_is_capped() -> None:
    # 5000 x 5000 pt at 150 DPI would be about 108 megapixels without the cap.
    width, height = _png_size(render_page_png(pdfs.huge_page_pdf(), 1, dpi=150))
    assert width * height <= MAX_RENDER_PIXELS * 1.01
    assert width == pytest.approx(height, abs=1)  # aspect ratio preserved


def test_page_has_any_content() -> None:
    blank = pymupdf.open(stream=pdfs.empty_pdf(), filetype="pdf")
    text = pymupdf.open(stream=pdfs.valid_text_pdf(), filetype="pdf")
    chart = pymupdf.open(stream=pdfs.vector_chart_pdf(), filetype="pdf")
    try:
        assert page_has_any_content(blank[0]) is False
        assert page_has_any_content(text[0]) is True
        assert page_has_any_content(chart[0]) is True
    finally:
        for d in (blank, text, chart):
            d.close()
