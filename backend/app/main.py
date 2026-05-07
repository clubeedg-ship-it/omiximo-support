"""FastAPI application entry point.

Responsibilities:
- Instantiate the FastAPI application with lifespan management
- Configure CORS
- Mount all API routers under the configured prefix
- Register global exception handlers
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config import settings
from app.core.exceptions import (
    ClassificationError,
    EncryptionError,
    MiraklAPIError,
    SafetyViolationError,
    TemplateNotFoundError,
    TemplateRenderError,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler.

    On startup:
      - Validate that the database is reachable
      - Start the background polling task

    On shutdown:
      - Cancel the polling task gracefully
    """
    logger.info("Omiximo Support API starting up")

    # Start background polling task
    polling_task = asyncio.create_task(_polling_loop(), name="mirakl_poller")

    yield

    # Shutdown
    logger.info("Omiximo Support API shutting down — cancelling background tasks")
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        logger.info("Background polling task cancelled cleanly")


async def _polling_loop() -> None:
    """Background task: collect and process new Mirakl threads periodically.

    Runs every MIRAKL_POLL_INTERVAL_SECONDS. Errors in a single run are logged
    and do not stop the loop.
    """
    # Import here to avoid circular imports at module load time
    from app.database import AsyncSessionLocal
    from app.services.collector import ThreadCollector
    from app.services.draft_pipeline import DraftPipeline

    collector = ThreadCollector()
    pipeline = DraftPipeline()

    while True:
        try:
            await asyncio.sleep(settings.MIRAKL_POLL_INTERVAL_SECONDS)
            logger.info("Polling: starting collection run")
            async with AsyncSessionLocal() as db:
                collected = await collector.collect_all(db)
                logger.info("Polling: collected %d new thread(s)", collected)

            async with AsyncSessionLocal() as db:
                processed = await pipeline.process_new_threads(db)
                logger.info("Polling: processed %d thread(s)", processed)

        except asyncio.CancelledError:
            logger.info("Polling loop received cancellation signal")
            raise
        except Exception as exc:
            logger.exception("Polling loop encountered an unhandled error: %s", exc)
            # Continue polling after unexpected errors


def create_app() -> FastAPI:
    """Factory function for the FastAPI application instance."""
    app = FastAPI(
        title="Omiximo Support Automation API",
        description=(
            "Semi-automated Mirakl customer support backend. "
            "Classifies messages, drafts template responses, enforces safety rules, "
            "and routes Green cases to auto-send."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------ #
    # CORS                                                                 #
    # ------------------------------------------------------------------ #
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------ #
    # Routers                                                              #
    # ------------------------------------------------------------------ #
    # Health check at root level (no prefix)
    from app.api.health import router as health_router
    app.include_router(health_router)

    # All versioned API routes under /api/v1
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # ------------------------------------------------------------------ #
    # Exception handlers                                                   #
    # ------------------------------------------------------------------ #
    @app.exception_handler(MiraklAPIError)
    async def mirakl_error_handler(
        request: Request, exc: MiraklAPIError
    ) -> JSONResponse:
        logger.error("MiraklAPIError: %s | detail: %s", exc.message, exc.detail)
        return JSONResponse(
            status_code=502,
            content={
                "error": "mirakl_api_error",
                "message": exc.message,
                "detail": exc.detail,
            },
        )

    @app.exception_handler(ClassificationError)
    async def classification_error_handler(
        request: Request, exc: ClassificationError
    ) -> JSONResponse:
        logger.error("ClassificationError: %s", exc.message)
        return JSONResponse(
            status_code=502,
            content={
                "error": "classification_error",
                "message": exc.message,
            },
        )

    @app.exception_handler(TemplateNotFoundError)
    async def template_not_found_handler(
        request: Request, exc: TemplateNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": "template_not_found",
                "message": exc.message,
                "category": exc.category,
                "language": exc.language,
            },
        )

    @app.exception_handler(TemplateRenderError)
    async def template_render_error_handler(
        request: Request, exc: TemplateRenderError
    ) -> JSONResponse:
        logger.error("TemplateRenderError: %s", exc.message)
        return JSONResponse(
            status_code=500,
            content={"error": "template_render_error", "message": exc.message},
        )

    @app.exception_handler(SafetyViolationError)
    async def safety_violation_handler(
        request: Request, exc: SafetyViolationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": "safety_violation",
                "message": exc.message,
                "violations": exc.violations,
            },
        )

    @app.exception_handler(EncryptionError)
    async def encryption_error_handler(
        request: Request, exc: EncryptionError
    ) -> JSONResponse:
        logger.critical("EncryptionError: %s", exc.message)
        return JSONResponse(
            status_code=500,
            content={"error": "encryption_error", "message": "Encryption subsystem error"},
        )

    return app


app = create_app()
