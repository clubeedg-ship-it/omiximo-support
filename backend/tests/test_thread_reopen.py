"""Tests for thread re-opening logic (multi-message conversations).

Validates that follow-up customer messages correctly re-open threads from
terminal states and that the message/audit tracking behaves correctly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import (
    CustomerLanguage,
    RiskLevel,
    SupportThread,
    ThreadStatus,
)
from app.models.thread_message import MessageAuthorType, MessageDirection, ThreadMessage
from app.services.thread_reopen import append_customer_message


@pytest_asyncio.fixture
async def sent_auto_thread(
    db: AsyncSession,
    sample_account: MarketplaceAccount,
) -> SupportThread:
    """A SENT_AUTO thread simulating a previously auto-replied conversation."""
    thread = SupportThread(
        id=uuid.uuid4(),
        mirakl_thread_id="MK-REOPEN-SENT",
        mirakl_order_id="ORD-REOPEN-SENT",
        marketplace_account_id=sample_account.id,
        customer_message="Original message about shipping.",
        customer_language=CustomerLanguage.en,
        category="shipping_delay",
        risk_level=RiskLevel.GREEN,
        status=ThreadStatus.SENT_AUTO,
        operator_required=False,
        drafted_response="Your order is on its way.",
        message_summary="Customer asking about shipping.",
        translated_message="",
        draft_summary="Reply about shipping status.",
        draft_translated="",
        response_deadline=datetime.now(UTC) + timedelta(hours=24),
        message_count=2,
        last_customer_message_at=datetime.now(UTC) - timedelta(hours=12),
    )
    db.add(thread)
    await db.flush()

    # Add existing messages
    msg1 = ThreadMessage(
        id=uuid.uuid4(),
        thread_id=thread.id,
        direction=MessageDirection.INBOUND.value,
        author_type=MessageAuthorType.CUSTOMER.value,
        body="Original message about shipping.",
        sequence_number=1,
    )
    msg2 = ThreadMessage(
        id=uuid.uuid4(),
        thread_id=thread.id,
        direction=MessageDirection.OUTBOUND.value,
        author_type=MessageAuthorType.SHOP_USER.value,
        body="Your order is on its way.",
        sequence_number=2,
    )
    db.add_all([msg1, msg2])
    await db.flush()
    return thread


@pytest_asyncio.fixture
async def approved_thread(
    db: AsyncSession,
    sample_account: MarketplaceAccount,
) -> SupportThread:
    """An APPROVED thread simulating a human-approved reply."""
    thread = SupportThread(
        id=uuid.uuid4(),
        mirakl_thread_id="MK-REOPEN-APPROVED",
        mirakl_order_id="ORD-REOPEN-APPROVED",
        marketplace_account_id=sample_account.id,
        customer_message="I want to return this item.",
        customer_language=CustomerLanguage.en,
        category="return_request",
        risk_level=RiskLevel.ORANGE,
        status=ThreadStatus.APPROVED,
        operator_required=False,
        drafted_response="Please use the return portal.",
        response_deadline=datetime.now(UTC) + timedelta(hours=24),
        message_count=2,
        last_customer_message_at=datetime.now(UTC) - timedelta(hours=6),
    )
    db.add(thread)
    await db.flush()
    return thread


@pytest_asyncio.fixture
async def pending_thread(
    db: AsyncSession,
    sample_account: MarketplaceAccount,
) -> SupportThread:
    """A PENDING_REVIEW thread (still active, not terminal)."""
    thread = SupportThread(
        id=uuid.uuid4(),
        mirakl_thread_id="MK-REOPEN-PENDING",
        mirakl_order_id="ORD-REOPEN-PENDING",
        marketplace_account_id=sample_account.id,
        customer_message="Waiting for your reply.",
        status=ThreadStatus.PENDING_REVIEW,
        operator_required=False,
        response_deadline=datetime.now(UTC) + timedelta(hours=24),
        message_count=1,
        last_customer_message_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db.add(thread)
    await db.flush()
    return thread


class TestThreadReopen:

    async def test_reopen_from_sent_auto(self, db, sent_auto_thread):
        """SENT_AUTO thread with new message transitions to PENDING_REVIEW."""
        await append_customer_message(
            db, sent_auto_thread, "It still hasn't arrived!"
        )

        assert sent_auto_thread.status == ThreadStatus.PENDING_REVIEW

    async def test_reopen_from_approved(self, db, approved_thread):
        """APPROVED thread with new message transitions to PENDING_REVIEW."""
        await append_customer_message(
            db, approved_thread, "The return portal is not working."
        )

        assert approved_thread.status == ThreadStatus.PENDING_REVIEW

    async def test_reopen_clears_classification(self, db, sent_auto_thread):
        """Re-opening a thread should clear risk_level, category, and cached insights."""
        await append_customer_message(
            db, sent_auto_thread, "Still waiting!"
        )

        assert sent_auto_thread.risk_level is None
        assert sent_auto_thread.category is None
        assert sent_auto_thread.drafted_response is None
        assert sent_auto_thread.message_summary is None
        assert sent_auto_thread.translated_message is None
        assert sent_auto_thread.draft_summary is None
        assert sent_auto_thread.draft_translated is None

    async def test_reopen_on_pending_review_just_appends(self, db, pending_thread):
        """PENDING_REVIEW thread stays in the same status; message is just appended."""
        original_status = pending_thread.status

        await append_customer_message(
            db, pending_thread, "Any update?"
        )

        assert pending_thread.status == original_status
        assert pending_thread.status == ThreadStatus.PENDING_REVIEW
        assert pending_thread.customer_message == "Any update?"
        assert pending_thread.message_count == 2

    async def test_reopen_writes_audit_log(self, db, sent_auto_thread):
        """Re-opening a thread should create an audit log entry."""
        await append_customer_message(
            db, sent_auto_thread, "Follow-up message"
        )

        result = await db.execute(
            select(AuditLog).where(
                AuditLog.thread_id == sent_auto_thread.id,
                AuditLog.action == "thread_reopened",
            )
        )
        log = result.scalar_one_or_none()
        assert log is not None
        assert log.actor == "system"
        assert log.detail_json["previous_status"] == "SENT_AUTO"
        assert log.detail_json["new_message_length"] == len("Follow-up message")

    async def test_message_count_increments(self, db, sent_auto_thread):
        """Each appended message should increment the thread's message_count."""
        original_count = sent_auto_thread.message_count
        assert original_count == 2

        await append_customer_message(
            db, sent_auto_thread, "First follow-up"
        )
        assert sent_auto_thread.message_count == 3

        await append_customer_message(
            db, sent_auto_thread, "Second follow-up"
        )
        assert sent_auto_thread.message_count == 4

    async def test_appended_message_stored_as_thread_message(self, db, pending_thread):
        """The new message should be stored as a ThreadMessage with correct fields."""
        msg = await append_customer_message(
            db, pending_thread, "Where is my refund?"
        )

        assert msg.direction == MessageDirection.INBOUND.value
        assert msg.author_type == MessageAuthorType.CUSTOMER.value
        assert msg.body == "Where is my refund?"
        assert msg.sequence_number == 2
        assert msg.thread_id == pending_thread.id

    async def test_reopen_updates_denormalized_customer_message(
        self, db, sent_auto_thread
    ):
        """The denormalized customer_message field should be updated to the new message."""
        new_msg = "This is a follow-up question about my order."
        await append_customer_message(db, sent_auto_thread, new_msg)

        assert sent_auto_thread.customer_message == new_msg

    async def test_reopen_updates_last_customer_message_at(self, db, sent_auto_thread):
        """last_customer_message_at should be updated to now."""
        before = datetime.now(UTC)
        await append_customer_message(
            db, sent_auto_thread, "Another follow-up"
        )
        after = datetime.now(UTC)

        assert sent_auto_thread.last_customer_message_at is not None
        assert before <= sent_auto_thread.last_customer_message_at <= after

    async def test_no_audit_log_when_not_terminal(self, db, pending_thread):
        """No thread_reopened audit log should be written for non-terminal threads."""
        await append_customer_message(
            db, pending_thread, "Just checking in"
        )

        result = await db.execute(
            select(AuditLog).where(
                AuditLog.thread_id == pending_thread.id,
                AuditLog.action == "thread_reopened",
            )
        )
        log = result.scalar_one_or_none()
        assert log is None
