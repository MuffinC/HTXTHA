"""Build the configured LLM provider from settings."""

from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.mock import MockProvider
from app.llm.ollama import OllamaProvider


def build_provider(settings: Settings) -> LLMProvider:
    """Return the provider selected by ``LLM_PROVIDER``."""
    if settings.llm_provider == "mock":
        return MockProvider()
    return OllamaProvider(settings)
