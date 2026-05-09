"""Main API router — aggregates all sub-routers under the v1 prefix."""

from fastapi import APIRouter, Depends

from app.api.alerts import router as alerts_router
from app.api.classification import router as classification_router
from app.api.marketplace_accounts import router as accounts_router
from app.api.reports import router as reports_router
from app.api.templates import router as templates_router
from app.api.threads import router as threads_router
from app.api.webhooks import router as webhooks_router
from app.auth import require_admin_user

api_router = APIRouter()
protected_api_router = APIRouter(dependencies=[Depends(require_admin_user)])

api_router.include_router(webhooks_router)
protected_api_router.include_router(threads_router)
protected_api_router.include_router(accounts_router)
protected_api_router.include_router(templates_router)
protected_api_router.include_router(alerts_router)
protected_api_router.include_router(reports_router)
protected_api_router.include_router(classification_router)
api_router.include_router(protected_api_router)
