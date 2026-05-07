"""Pytest fixtures for the Omiximo Support backend test suite.

Uses an in-process SQLite database (via aiosqlite) so tests run without an
external PostgreSQL instance. The engine is created fresh for each test
session; each individual test gets its own rolled-back transaction so the
database state is always clean.

Key fixtures:
  engine        – Shared async engine (SQLite, session-scoped)
  db            – Per-test async session with automatic rollback
  client        – HTTPX AsyncClient wired to the FastAPI app with the test db
  sample_account    – A MarketplaceAccount inserted in the test db
  sample_thread     – A SupportThread linked to sample_account
  sample_template   – A ResponseTemplate linked to sample_account
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.marketplace_account import MarketplaceAccount
from app.models.response_template import ResponseTemplate
from app.models.support_thread import (
    CustomerLanguage,
    RiskLevel,
    SupportThread,
    ThreadStatus,
)
from app.services.encryption import encrypt

# --------------------------------------------------------------------------- #
# SQLite test engine                                                           #
# --------------------------------------------------------------------------- #

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def engine():
    """Create a fresh SQLite in-memory engine for each test.

    Using function scope (default) ensures full isolation: each test gets
    its own database with clean schema, so no test can pollute another's
    data through the shared session-scoped engine.
    """
    test_engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield test_engine

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a per-test async session backed by the per-test engine."""
    TestSession = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTPX AsyncClient wired to the FastAPI app, using the test db session."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c

    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Sample data fixtures                                                         #
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def sample_account(db: AsyncSession) -> MarketplaceAccount:
    """Insert and return a sample active MarketplaceAccount."""
    account = MarketplaceAccount(
        id=uuid.uuid4(),
        marketplace="MediaMarkt",
        shop_id="shop-001",
        api_key_encrypted=encrypt("test-api-key-12345"),
        base_url="https://markt.mediamarkt.nl",
        sla_hours=24,
        template_set="default",
        is_active=True,
    )
    db.add(account)
    await db.flush()
    return account


@pytest_asyncio.fixture
async def sample_thread(
    db: AsyncSession,
    sample_account: MarketplaceAccount,
) -> SupportThread:
    """Insert and return a PENDING_REVIEW SupportThread."""
    thread = SupportThread(
        id=uuid.uuid4(),
        mirakl_thread_id="MK-THREAD-001",
        mirakl_order_id="MK-ORDER-001",
        marketplace_account_id=sample_account.id,
        customer_message="Where is my order? It has been 10 days.",
        operator_required=False,
        status=ThreadStatus.PENDING_REVIEW,
        response_deadline=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(thread)
    await db.flush()
    return thread


@pytest_asyncio.fixture
async def classified_green_thread(
    db: AsyncSession,
    sample_account: MarketplaceAccount,
) -> SupportThread:
    """A GREEN PENDING_REVIEW thread with a drafted response."""
    thread = SupportThread(
        id=uuid.uuid4(),
        mirakl_thread_id="MK-THREAD-GREEN",
        mirakl_order_id="MK-ORDER-GREEN",
        marketplace_account_id=sample_account.id,
        customer_message="Where is my order?",
        customer_language=CustomerLanguage.en,
        category="shipping_delay",
        risk_level=RiskLevel.GREEN,
        operator_required=False,
        status=ThreadStatus.PENDING_REVIEW,
        drafted_response="Dear customer, your order MK-ORDER-GREEN is on its way.",
        response_deadline=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(thread)
    await db.flush()
    return thread


@pytest_asyncio.fixture
async def operator_thread(
    db: AsyncSession,
    sample_account: MarketplaceAccount,
) -> SupportThread:
    """A thread where operator_required=True."""
    thread = SupportThread(
        id=uuid.uuid4(),
        mirakl_thread_id="MK-THREAD-OP",
        mirakl_order_id="MK-ORDER-OP",
        marketplace_account_id=sample_account.id,
        customer_message="Operator message about compliance.",
        operator_required=True,
        status=ThreadStatus.PENDING_REVIEW,
        response_deadline=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(thread)
    await db.flush()
    return thread


@pytest_asyncio.fixture
async def sample_template(
    db: AsyncSession,
    sample_account: MarketplaceAccount,
) -> ResponseTemplate:
    """Insert and return a global shipping_delay template in English."""
    template = ResponseTemplate(
        id=uuid.uuid4(),
        marketplace_account_id=None,  # global
        category="shipping_delay",
        language="en",
        template_body=(
            "Dear {{ customer_name or 'customer' }},\n\n"
            "Thank you for reaching out. Your order {{ order_id }} is currently "
            "in transit. Tracking number: {{ tracking_number or 'not yet available' }}.\n\n"
            "Kind regards,\n{{ shop_name }}"
        ),
        is_active=True,
    )
    db.add(template)
    await db.flush()
    return template


@pytest_asyncio.fixture
async def nl_template(
    db: AsyncSession,
    sample_account: MarketplaceAccount,
) -> ResponseTemplate:
    """A Dutch shipping_delay template scoped to sample_account."""
    template = ResponseTemplate(
        id=uuid.uuid4(),
        marketplace_account_id=sample_account.id,
        category="shipping_delay",
        language="nl",
        template_body=(
            "Beste {{ customer_name or 'klant' }},\n\n"
            "Bedankt voor uw bericht. Uw bestelling {{ order_id }} is onderweg. "
            "Trackingnummer: {{ tracking_number or 'nog niet beschikbaar' }}.\n\n"
            "Met vriendelijke groet,\n{{ shop_name }}"
        ),
        is_active=True,
    )
    db.add(template)
    await db.flush()
    return template
