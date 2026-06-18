"""Thread re-opening logic for multi-message conversations.

When a customer sends a follow-up message on a thread that has already been
processed (sent, approved, escalated, or failed), this module handles the
state transition back to PENDING_REVIEW so the thread re-enters the
automation pipeline.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_thread import SupportThread, ThreadStatus
from app.models.thread_message import MessageAuthorType, MessageDirection, ThreadMessage
from app.services.audit import write_audit_log

# Terminal states: the thread was previously resolved in some manner
_TERMINAL_STATES = frozenset({
    ThreadStatus.SENT_AUTO,
    ThreadStatus.APPROVED,
    ThreadStatus.ESCALATED,
    ThreadStatus.FAILED,
})


async def append_customer_message(
    db: AsyncSession,
    thread: SupportThread,
    new_message: str,
) -> ThreadMessage:
    """Append a new inbound customer message to a thread.

    If the thread is in a terminal state, it is re-opened. If the thread is
    already active (PENDING_REVIEW), the message is simply appended without
    any status change.

    Args:
        db:          The current async database session.
        thread:      The existing SupportThread to append to.
        new_message: The body of the new customer message.

    Returns:
        The newly created ThreadMessage.
    """
    now = datetime.now(UTC)

    # Append the new message
    next_seq = thread.message_count + 1
    message = ThreadMessage(
        id=uuid.uuid4(),
        thread_id=thread.id,
        direction=MessageDirection.INBOUND.value,
        author_type=MessageAuthorType.CUSTOMER.value,
        body=new_message,
        sequence_number=next_seq,
    )
    db.add(message)

    # Update denormalized fields
    thread.customer_message = new_message
    thread.message_count = next_seq
    thread.last_customer_message_at = now
    thread.updated_at = now

    await reopen_if_terminal(db, thread, new_message_length=len(new_message))

    await db.flush()
    return message


async def reopen_if_terminal(
    db: AsyncSession,
    thread: SupportThread,
    *,
    new_message_length: int,
) -> bool:
    """Re-open a terminal thread so it re-enters the automation pipeline.

    Clears the prior classification/draft/insight so the thread is reprocessed
    cleanly, and writes a ``thread_reopened`` audit entry. No-op for threads
    that are already active.

    Returns:
        ``True`` if the thread was re-opened, ``False`` otherwise.
    """
    if thread.status not in _TERMINAL_STATES:
        return False

    previous_status = thread.status
    thread.status = ThreadStatus.PENDING_REVIEW
    thread.risk_level = None
    thread.category = None
    thread.drafted_response = None
    thread.message_summary = None
    thread.translated_message = None
    thread.draft_summary = None
    thread.draft_translated = None

    await write_audit_log(
        db,
        action="thread_reopened",
        actor="system",
        thread_id=thread.id,
        detail={
            "previous_status": previous_status.value,
            "new_message_length": new_message_length,
        },
    )
    return True
