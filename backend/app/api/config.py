"""``GET /api/config``: the settings the frontend needs.

The upload panel checks files against these limits before sending them, so the
browser and the server can never disagree (DECISIONS D-045). Only display-safe
values are exposed: no URLs, paths or model internals.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings

router = APIRouter(tags=["config"])


class ConfigResponse(BaseModel):
    """Limits and policies the UI shows or enforces."""

    max_files: int
    max_file_mb: int
    max_pages: int
    max_visual_pages_per_doc: int
    active_content_policy: Literal["reject", "warn"]
    mask_pii: bool
    retain_uploads: bool


@router.get("/config", response_model=ConfigResponse)
async def get_config(settings: Settings = Depends(get_settings)) -> ConfigResponse:
    """Upload limits and display-relevant policies from the backend settings."""
    return ConfigResponse(
        max_files=settings.max_files,
        max_file_mb=settings.max_file_mb,
        max_pages=settings.max_pages,
        max_visual_pages_per_doc=settings.max_visual_pages_per_doc,
        active_content_policy=settings.active_content_policy,
        mask_pii=settings.mask_pii,
        retain_uploads=settings.retain_uploads,
    )
