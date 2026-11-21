"""Shared FastAPI dependencies.

Everything here is created once per app (provider in ``create_app``; storage and
worker in the lifespan) and kept on ``app.state``.
"""

from fastapi import Request

from app.llm.base import LLMProvider
from app.pipeline.worker import JobWorker
from app.storage.repository import Repository
from app.storage.uploads import UploadStore


def get_provider(request: Request) -> LLMProvider:
    """Return the app's LLM provider."""
    provider: LLMProvider = request.app.state.provider
    return provider


def get_repo(request: Request) -> Repository:
    """Return the app's SQLite repository."""
    repo: Repository = request.app.state.repo
    return repo


def get_uploads(request: Request) -> UploadStore:
    """Return the app's upload store."""
    uploads: UploadStore = request.app.state.uploads
    return uploads


def get_worker(request: Request) -> JobWorker:
    """Return the app's job worker."""
    worker: JobWorker = request.app.state.worker
    return worker
