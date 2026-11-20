"""FastAPI application factory and lifespan.

``create_app`` builds the app so tests can construct isolated instances with
their own settings. The module-level ``app`` is what Uvicorn serves
(``uvicorn app.main:app``).

Later milestones attach the job worker (``asyncio.Queue``) and SQLite storage
to the lifespan below.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import health
from app.api.errors import register_error_handlers
from app.config import Settings, get_settings
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)

API_PREFIX = "/api"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Optional settings override (used by tests). Defaults to
            settings read from the environment.

    Returns:
        A configured ``FastAPI`` instance.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Log an explicit allow-list of config values, never the whole object.
        logger.info(
            "Backend starting: provider=%s model=%s",
            settings.llm_provider,
            settings.ollama_model,
            extra={"event": "startup"},
        )
        yield
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

    register_error_handlers(app)
    app.include_router(health.router, prefix=API_PREFIX)
    return app


app = create_app()
