"""Shared pytest fixtures.

Tests never touch a real model: the default app fixture uses the mock provider.
Fixture PDFs are generated in memory with PyMuPDF by ``tests/pdf_factory.py``
(the same builders produce the demo files in ``sample_pdfs/adversarial/``).
"""

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings for an isolated test app using the mock provider."""
    return Settings(llm_provider="mock", data_dir=tmp_path, log_level="WARNING")


@pytest.fixture
def make_settings(tmp_path: Path) -> Callable[..., Settings]:
    """Factory for test settings with overrides, e.g. ``make_settings(max_pages=2)``."""

    def _make(**overrides: Any) -> Settings:
        base: dict[str, Any] = {
            "llm_provider": "mock",
            "data_dir": tmp_path,
            "log_level": "WARNING",
        }
        return Settings(**(base | overrides))

    return _make


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """An httpx client bound to an in-process app (no network)."""
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
