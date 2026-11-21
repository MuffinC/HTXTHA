"""Shared pytest fixtures.

Tests never touch a real model: the default app fixture uses the mock provider.
Fixture PDFs are generated in memory with PyMuPDF by ``tests/pdf_factory.py``
(the same builders produce the demo files in ``sample_pdfs/adversarial/``).
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

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


@asynccontextmanager
async def app_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Run the app's lifespan (storage + worker) and yield an in-process client.

    ``httpx.ASGITransport`` does not run the lifespan by itself.
    """
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """An httpx client bound to an in-process app with the mock provider (no network)."""
    async with app_client(create_app(settings)) as ac:
        yield ac
