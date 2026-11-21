"""FastAPI application factory and lifespan.

``create_app`` builds the app so tests can construct isolated instances with
their own settings. The module-level ``app`` is what Uvicorn serves
(``uvicorn app.main:app``).

The lifespan opens SQLite and the upload store under ``DATA_DIR``, fails any
jobs a previous run left unfinished, and starts the job worker. Storage is
created in the lifespan rather than here, so importing the module (as Uvicorn
and the tests do) never touches the filesystem.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app import __version__
from app.api import config, health, jobs
from app.api.errors import error_response, register_error_handlers
from app.config import Settings, get_settings
from app.errors import ErrorCode
from app.llm.base import LLMProvider
from app.llm.factory import build_provider
from app.logging_config import configure_logging
from app.pipeline.worker import JobWorker
from app.storage.repository import Repository
from app.storage.uploads import UploadStore

logger = logging.getLogger(__name__)

API_PREFIX = "/api"
DB_FILENAME = "htx.sqlite3"
# Multipart framing overhead allowed on top of MAX_FILES x MAX_FILE_MB.
UPLOAD_OVERHEAD_BYTES = 1024 * 1024


def create_app(settings: Settings | None = None, provider: LLMProvider | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Optional settings override (used by tests). Defaults to
            settings read from the environment.
        provider: Optional LLM provider override (used by tests). Defaults to
            the provider selected by ``LLM_PROVIDER``.

    Returns:
        A configured ``FastAPI`` instance.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    llm_provider = provider or build_provider(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Log an explicit allow-list of config values, never the whole object.
        logger.info(
            "Backend starting: provider=%s model=%s",
            llm_provider.name,
            llm_provider.model,
            extra={"event": "startup"},
        )
        repo = Repository(settings.data_dir / DB_FILENAME)
        uploads = UploadStore(settings.data_dir)
        worker = JobWorker(repo, uploads, llm_provider, settings)
        worker.recover_interrupted_jobs()
        worker.start()
        app.state.repo, app.state.uploads, app.state.worker = repo, uploads, worker
        try:
            yield
        finally:
            await worker.stop()
            repo.close()
            logger.info("Backend stopping", extra={"event": "shutdown"})

    app = FastAPI(
        title="HTX Document Analyst API",
        version=__version__,
        description=(
            "Analyse one or more PDF documents with a fully local AI pipeline. "
            "All document content is treated as untrusted data."
        ),
        lifespan=lifespan,
        # Docs live under /api so the frontend's nginx /api proxy exposes them too.
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=None,
    )

    # Every request in this app instance sees the settings it was built with.
    app.dependency_overrides[get_settings] = lambda: settings
    # One provider per app; routes get it through app.api.deps.get_provider.
    app.state.provider = llm_provider

    max_request = settings.max_files * settings.max_file_mb * 1024 * 1024 + UPLOAD_OVERHEAD_BYTES

    @app.middleware("http")
    async def limit_upload_size(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Refuse an oversized upload from its Content-Length, before the body is parsed."""
        length = request.headers.get("content-length", "")
        if request.method == "POST" and length.isdigit() and int(length) > max_request:
            return error_response(
                413,
                ErrorCode.FILE_TOO_LARGE,
                f"The upload is larger than the {max_request // (1024 * 1024)} MB allowed "
                "per request.",
            )
        return await call_next(request)

    register_error_handlers(app)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(jobs.router, prefix=API_PREFIX)
    app.include_router(config.router, prefix=API_PREFIX)
    return app


app = create_app()
