"""Output of pipeline stage 1 (per-page extraction).

These are internal pipeline records, not the final analysis schema. They feed
visual analysis (M2) and document analysis (M3).
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import DocumentWarning

VisualReason = Literal["embedded_image", "vector_drawing", "scanned"]


class PageContent(BaseModel):
    """Everything extracted from one page without a model."""

    page: int = Field(ge=1, description="1-based page number")
    text: str = Field(description="Plain text from the PDF text layer")
    tables: list[str] = Field(default_factory=list, description="Tables as markdown")
    needs_visual_analysis: bool
    visual_reasons: list[VisualReason] = Field(
        default_factory=list, description="Why the page needs visual analysis"
    )
    visual_area_ratio: float = Field(
        ge=0,
        le=1,
        description="Fraction of the page covered by non-decorative visuals; used to "
        "prioritise pages when MAX_VISUAL_PAGES_PER_DOC is reached",
    )
    margin_lines: list[str] = Field(
        default_factory=list,
        description="Text lines in the top/bottom margin band (header/footer candidates)",
    )
    selected_for_visual_analysis: bool = Field(
        default=False, description="True if this page is within the per-document visual cap"
    )


class ExtractedDocument(BaseModel):
    """Per-page extraction for one document, plus extraction-time warnings."""

    page_count: int
    pages: list[PageContent]
    warnings: list[DocumentWarning] = Field(default_factory=list)
    boilerplate_lines: list[str] = Field(
        default_factory=list,
        description="Header/footer lines repeated on most pages, removed from page text",
    )

    @property
    def visual_pages(self) -> list[int]:
        """Page numbers selected for visual analysis, in page order."""
        return [p.page for p in self.pages if p.selected_for_visual_analysis]
