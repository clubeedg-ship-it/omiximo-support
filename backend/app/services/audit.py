"""Audit log service.

Architecture decision D4: every automated decision, draft generation, approval,
send, and failure gets a row in audit_log. This module provides the single
function used throughout the service layer to write those rows.

Usage:
    from app.services.audit import write_audit_log

    await write_audit_log(
        db=db,
        action="thread_collected",
        actor="system",
        thread_id=thread.id,
        detail={"mirakl_thread_id": thread.mirakl_thread_id},
    )
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def write_audit_log(
    db: AsyncSession,
    action: str,
    actor: str,
    *,
    thread_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """Persist an audit log entry and flush it to the session.

    The caller is responsible for committing the surrounding transaction.
    In practice, the FastAPI ``get_db`` dependency commits at the end of
    each request, and the background pipeline commits explicitly.

    Args:
        db:        The current async database session.
        action:    Short identifier for what happened, e.g. "classified".
        actor:     "system" for automated steps; a user ID/email for human actions.
        thread_id: FK to the associated SupportThread; None for account-level events.
        detail:    Optional structured context serialised as JSON.

    Returns:
        The persisted AuditLog instance (id is populated after flush).
    """
    log_entry = AuditLog(
        id=uuid.uuid4(),
        thread_id=thread_id,
        action=action,
        actor=actor,
        detail_json=detail,
    )
    db.add(log_entry)
    await db.flush()
    return log_entry
