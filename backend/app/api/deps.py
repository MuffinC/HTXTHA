"""Shared FastAPI dependencies."""

from fastapi import Request

from app.llm.base import LLMProvider


def get_provider(request: Request) -> LLMProvider:
    """Return the app's LLM provider (built once in ``create_app``)."""
    provider: LLMProvider = request.app.state.provider
    return provider
