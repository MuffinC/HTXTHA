"""Fixtures for live-model tests (``pytest -m ollama``).

These tests call a real Ollama server. They are deselected by default
(``addopts`` in ``pyproject.toml``) and never run in CI. If Ollama is not
reachable or the model is not pulled, they are skipped rather than failed.

Ollama URL: ``OLLAMA_BASE_URL`` if set, otherwise ``http://127.0.0.1:11434``
(a native install), not the Docker hostname used by the app's default.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.config import Settings
from app.llm.ollama import OllamaProvider

# (test name, seconds) collected by tests and printed after the run.
TIMINGS: list[tuple[str, float]] = []
# Free-text observations about model behaviour, printed after the run.
NOTES: list[str] = []


@pytest.fixture
def live_settings(tmp_path: Path) -> Settings:
    """Settings for the real model (environment overrides still apply)."""
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    return Settings(
        llm_provider="ollama", ollama_base_url=base_url, data_dir=tmp_path, log_level="WARNING"
    )


@pytest.fixture
async def live_provider(live_settings: Settings) -> AsyncIterator[OllamaProvider]:
    """The real provider, or skip if Ollama or the model is not available."""
    provider = OllamaProvider(live_settings)
    if not await provider.is_ready():
        pytest.skip(
            f"Ollama at {live_settings.ollama_base_url} is not reachable "
            f"or {live_settings.ollama_model} is not pulled"
        )
    yield provider


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Print per-page model timings and behaviour notes after a live run."""
    if TIMINGS:
        terminalreporter.section("live model timings (per page, wall clock)")
        for name, seconds in TIMINGS:
            terminalreporter.write_line(f"{name:<50} {seconds:6.1f} s")
    if NOTES:
        terminalreporter.section("live model behaviour")
        for note in NOTES:
            terminalreporter.write_line(note)
