"""Main API router — aggregates all sub-routers under the v1 prefix."""

from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.marketplace_accounts import router as accounts_router
from app.api.templates import router as templates_router
from app.api.threads import router as threads_router

api_router = APIRouter()

# Health check lives at /health (no version prefix)
api_router.include_router(health_router)

# All versioned resources sit under /api/v1/
api_router.include_router(threads_router)
api_router.include_router(accounts_router)
api_router.include_router(templates_router)
