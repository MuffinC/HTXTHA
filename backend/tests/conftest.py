"""Shared pytest fixtures.

Tests never touch a real model: the default app fixture uses the mock provider.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings for an isolated test app using the mock provider."""
    return Settings(llm_provider="mock", data_dir=tmp_path, log_level="WARNING")


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """An httpx client bound to an in-process app (no network)."""
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
