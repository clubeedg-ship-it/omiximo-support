"""Thread collector service.

In Mirakl Connect mode (``MIRAKL_CONNECT_CLIENT_ID`` set), a single
``fetch_threads`` call returns threads across all linked marketplaces. The
collector extracts the channel/marketplace identity from each thread's
``entities`` payload, auto-creates ``MarketplaceAccount`` records as needed,
and upserts into ``support_threads``.

In legacy mode (no Connect credentials), the original behaviour is preserved:
every active ``MarketplaceAccount`` is polled individually using its per-shop
API key.

Usage::

    collector = ThreadCollector()
    async with AsyncSessionLocal() as db:
        await collector.collect_all(db)
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import ReplyState, SupportThread, ThreadStatus
from app.models.thread_message import MessageAuthorType, MessageDirection, ThreadMessage
from app.services.audit import write_audit_log
from app.services.message_filter import MessageFilter
from app.services.mirakl_client import MiraklClient, MiraklConnectClient
from app.services.thread_reopen import reopen_if_terminal

logger = logging.getLogger(__name__)


class ThreadCollector:
    """Collects new Mirakl threads and upserts them into the database."""

    def __init__(self, message_filter: MessageFilter | None = None) -> None:
        self._message_filter = message_filter or MessageFilter()

    async def collect_all(self, db: AsyncSession, *, updated_since: str | None = None) -> int:
        """Run collection for all active marketplace accounts.

        In Connect mode, a single API call fetches threads across all channels.
        In legacy mode, each ``MarketplaceAccount`` is polled in turn.

        Args:
            db:            Database session. The caller is responsible for committing
                           any outstanding changes between calls.
            updated_since: ISO-8601 timestamp; only threads updated after this time
                           are fetched (Connect mode only).

        Returns:
            Total number of new threads upserted.
        """
        if settings.MIRAKL_CONNECT_CLIENT_ID:
            return await self._collect_connect(db, updated_since=updated_since)
        return await self._collect_legacy(db)

    # ---------------------------------------------------------------------- #
    # Mirakl Connect path                                                      #
    # ---------------------------------------------------------------------- #

    async def _collect_connect(
        self,
        db: AsyncSession,
        *,
        updated_since: str | None = None,
    ) -> int:
        """Fetch threads via the Mirakl Connect API and upsert them."""
        connect = await MiraklConnectClient.get_instance()

        try:
            raw_threads = await connect.fetch_threads(updated_since=updated_since)
        except Exception as exc:
            logger.exception("Connect thread collection failed: %s", exc)
            await write_audit_log(
                db,
                action="collection_failed",
                actor="system",
                thread_id=None,
                detail={"error": str(exc), "mode": "connect"},
            )
            await db.commit()
            return 0

        total_new = 0
        for raw in raw_threads:
            account = await self._resolve_account(db, raw)
            if account is None:
                logger.warning(
                    "Skipping Connect thread %s — could not resolve marketplace account",
                    raw.get("id"),
                )
                continue
            is_new = await self._upsert_thread(db, account, raw, mode="connect")
            if is_new:
                total_new += 1

        logger.info(
            "Connect collection complete: %d raw thread(s), %d new",
            len(raw_threads),
            total_new,
        )
        return total_new

    async def _resolve_account(
        self,
        db: AsyncSession,
        raw: dict[str, Any],
    ) -> MarketplaceAccount | None:
        """Find or create a ``MarketplaceAccount`` from a Connect thread payload.

        The Connect API embeds channel information in the ``entities`` list.
        We look for an entity with ``type="channel"`` and extract the channel
        name (used as the marketplace identifier) and optional shop_id.

        If no matching account exists in the database, a placeholder account is
        created with sensible defaults so the thread can still be stored and
        reviewed by a human.

        Args:
            db:  Open database session.
            raw: Raw thread dict from the Connect API.

        Returns:
            A ``MarketplaceAccount`` instance, or ``None`` if no channel info
            can be extracted from the thread.
        """
        entities: list[dict[str, Any]] = raw.get("entities", [])
        channel_entity = next(
            (e for e in entities if e.get("type") == "channel"),
            None,
        )

        if channel_entity is None:
            # Fallback: some Connect responses embed channel info at the top level
            channel_name: str = raw.get("channel_name") or raw.get("channel", "")
            shop_id: str = raw.get("shop_id") or raw.get("seller_id") or settings.MIRAKL_CONNECT_SELLER_ID
        else:
            channel_name = (
                channel_entity.get("label")
                or channel_entity.get("name")
                or channel_entity.get("id", "")
            )
            shop_id = (
                channel_entity.get("shop_id")
                or channel_entity.get("seller_id")
                or settings.MIRAKL_CONNECT_SELLER_ID
            )

        if not channel_name:
            return None

        # Look for an existing account with this marketplace name
        stmt = select(MarketplaceAccount).where(
            MarketplaceAccount.marketplace == channel_name,
            MarketplaceAccount.is_active.is_(True),
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing

        # Create a placeholder account for this new channel
        logger.info(
            "Auto-creating MarketplaceAccount for new channel %r", channel_name
        )
        account = MarketplaceAccount(
            id=uuid.uuid4(),
            marketplace=channel_name,
            shop_id=shop_id or "unknown",
            api_key_encrypted=None,  # not needed in Connect mode
            base_url=settings.MIRAKL_CONNECT_API_URL,
            sla_hours=24,
            template_set="default",
            is_active=True,
        )
        db.add(account)
        await db.flush()
        return account

    # ---------------------------------------------------------------------- #
    # Legacy per-account path                                                  #
    # ---------------------------------------------------------------------- #

    async def _collect_legacy(self, db: AsyncSession) -> int:
        """Original collection strategy: poll each active account separately."""
        accounts = await self._fetch_active_accounts(db)
        total_new = 0

        for account in accounts:
            try:
                new_count = await self._collect_for_account(db, account)
                total_new += new_count
                logger.info(
                    "Collected %d new thread(s) for account %s (%s)",
                    new_count,
                    account.id,
                    account.marketplace,
                )
            except Exception as exc:
                logger.exception(
                    "Collection failed for account %s (%s): %s",
                    account.id,
                    account.marketplace,
                    exc,
                )
                await write_audit_log(
                    db,
                    action="collection_failed",
                    actor="system",
                    thread_id=None,
                    detail={
                        "account_id": str(account.id),
                        "marketplace": account.marketplace,
                        "error": str(exc),
                    },
                )
                await db.commit()

        return total_new

    async def _collect_for_account(
        self,
        db: AsyncSession,
        account: MarketplaceAccount,
    ) -> int:
        """Collect and upsert threads for a single legacy account."""
        async with MiraklClient(account) as client:
            raw_threads: list[dict[str, Any]] = await client.fetch_threads()

        new_count = 0
        for raw in raw_threads:
            is_new = await self._upsert_thread(db, account, raw, mode="legacy")
            if is_new:
                new_count += 1

        return new_count

    # ---------------------------------------------------------------------- #
    # Shared upsert logic                                                      #
    # ---------------------------------------------------------------------- #

    async def _upsert_thread(
        self,
        db: AsyncSession,
        account: MarketplaceAccount,
        raw: dict[str, Any],
        *,
        mode: str = "connect",
    ) -> bool:
        """Insert a new ``SupportThread`` or skip if it already exists.

        Thread IDs are stable; we rely on the unique constraint
        ``(mirakl_thread_id, marketplace_account_id)`` and skip rows that
        already exist rather than overwriting human-edited fields.

        The field mapping differs slightly between Connect and legacy payloads:
        - Connect: ``id``, ``topic.order_id`` or ``metadata.order_id``
        - Legacy:  ``id``, ``order_id``

        Returns:
            ``True`` if a new row was inserted.
        """
        mirakl_thread_id: str = str(raw.get("id", ""))

        # Extract order ID — M11 format uses entities list
        if mode == "connect":
            mirakl_order_id = (
                raw.get("topic", {}).get("order_id")
                or raw.get("metadata", {}).get("order_id")
                or str(raw.get("order_id", ""))
            )
        else:
            # M11 format: entities[0].id contains the order ID
            entities = raw.get("entities", [])
            if entities:
                mirakl_order_id = str(entities[0].get("id", ""))
            else:
                mirakl_order_id = str(raw.get("order_id", ""))

        mirakl_order_id = str(mirakl_order_id)

        if not mirakl_thread_id or not mirakl_order_id:
            logger.warning(
                "Skipping thread with missing id or order_id (mode=%s): %s",
                mode,
                raw,
            )
            return False

        # Check for existing row
        stmt = select(SupportThread).where(
            SupportThread.mirakl_thread_id == mirakl_thread_id,
            SupportThread.marketplace_account_id == account.id,
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            # Thread already exists — sync any messages we haven't stored yet.
            await self._sync_thread_messages(db, existing, raw)
            return False

        # Extract the latest customer message body
        messages: list[dict[str, Any]] = raw.get("messages", [])
        customer_message = _extract_customer_message(messages)
        if not customer_message:
            customer_message = (
                raw.get("subject")
                or raw.get("topic", {}).get("subject", "")
                or ""
            )

        # ---------------------------------------------------------------- #
        # Message filter: reject non-customer messages before storage       #
        # ---------------------------------------------------------------- #
        should_process, rejection_reason = self._message_filter.should_process(
            raw, customer_message
        )
        if not should_process:
            # Noise threads (invoice/notification emails) are re-evaluated on
            # every poll. We deliberately do NOT write an audit row here —
            # doing so accumulated tens of millions of rows. A debug log is
            # enough for diagnostics.
            logger.debug(
                "Filtered thread %s: %s", mirakl_thread_id, rejection_reason
            )
            return False

        if not customer_message:
            logger.warning(
                "Empty customer_message for raw thread id=%s — no body, content, "
                "or subject could be extracted. Thread will be stored with empty message.",
                mirakl_thread_id,
            )

        # Determine if this is an operator/marketplace message
        # M11: check current_participants for OPERATOR type or if last message is from OPERATOR
        current_participants = raw.get("current_participants", [])
        has_operator = any(p.get("type") == "OPERATOR" for p in current_participants)
        has_customer = any(p.get("type") == "CUSTOMER" for p in current_participants)
        operator_required: bool = has_operator and not has_customer or raw.get("operator_message", False)

        # Use Mirakl's original thread creation date, not our import time
        mirakl_date = _parse_mirakl_date(raw)
        thread_created_at = mirakl_date or datetime.now(UTC)

        # SLA deadline is relative to the original thread date
        response_deadline = thread_created_at + timedelta(hours=account.sla_hours)

        # Build the full conversation history from the Mirakl payload.
        thread_messages = _build_thread_messages(
            messages, default_dt=thread_created_at
        )
        if not thread_messages:
            # No structured messages (e.g. body came from the subject fallback);
            # store the single customer message so the thread is never empty.
            thread_messages = [
                ThreadMessage(
                    id=uuid.uuid4(),
                    direction=MessageDirection.INBOUND.value,
                    author_type=MessageAuthorType.CUSTOMER.value,
                    body=customer_message,
                    sequence_number=1,
                    created_at=thread_created_at,
                )
            ]

        last_customer_dt = next(
            (
                m.created_at
                for m in reversed(thread_messages)
                if m.author_type == MessageAuthorType.CUSTOMER.value
            ),
            thread_created_at,
        )

        thread = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id=mirakl_thread_id,
            mirakl_order_id=mirakl_order_id,
            marketplace_account_id=account.id,
            customer_message=customer_message,
            operator_required=operator_required,
            status=ThreadStatus.PENDING_REVIEW,
            reply_state=_derive_reply_state(raw),
            response_deadline=response_deadline,
            message_count=len(thread_messages),
            last_customer_message_at=last_customer_dt,
            last_activity_at=_parse_last_activity(raw) or thread_created_at,
            created_at=thread_created_at,
        )
        db.add(thread)
        await db.flush()

        for msg in thread_messages:
            msg.thread_id = thread.id
            db.add(msg)
        await db.flush()

        await write_audit_log(
            db,
            action="thread_collected",
            actor="system",
            thread_id=thread.id,
            detail={
                "mirakl_thread_id": mirakl_thread_id,
                "mirakl_order_id": mirakl_order_id,
                "account_id": str(account.id),
                "marketplace": account.marketplace,
                "operator_required": operator_required,
                "mode": mode,
            },
        )
        await db.commit()
        await _notify_new_thread(thread, account, customer_message)
        return True

    async def _sync_thread_messages(
        self,
        db: AsyncSession,
        thread: SupportThread,
        raw: dict[str, Any],
    ) -> None:
        """Idempotently store any Mirakl messages not yet persisted.

        Inserts every message whose ``mirakl_message_id`` is not already stored
        (covers customer follow-ups, operator notes, and replies sent outside
        this app). When the newest stored message is an inbound customer
        message, the denormalized ``customer_message`` is refreshed and a
        terminal thread is re-opened so it re-enters the pipeline.
        """
        messages: list[dict[str, Any]] = raw.get("messages", [])
        if not messages:
            return

        new_state = _derive_reply_state(raw)
        state_changed = new_state != thread.reply_state

        new_activity = _parse_last_activity(raw)
        activity_changed = (
            new_activity is not None and new_activity != thread.last_activity_at
        )

        existing_ids = {
            mid
            for mid in (
                await db.execute(
                    select(ThreadMessage.mirakl_message_id).where(
                        ThreadMessage.thread_id == thread.id
                    )
                )
            ).scalars().all()
            if mid
        }

        fallback_dt = thread.last_customer_message_at or thread.created_at or datetime.now(UTC)
        new_messages = _build_thread_messages(
            messages,
            default_dt=fallback_dt,
            start_seq=thread.message_count,
            skip_ids=existing_ids,
        )

        # Nothing new to persist and neither state nor activity changed.
        if not new_messages and not state_changed and not activity_changed:
            return

        if state_changed:
            thread.reply_state = new_state
        if activity_changed:
            thread.last_activity_at = new_activity

        if new_messages:
            for msg in new_messages:
                msg.thread_id = thread.id
                db.add(msg)
            thread.message_count += len(new_messages)

            latest_customer = next(
                (
                    m
                    for m in reversed(new_messages)
                    if m.author_type == MessageAuthorType.CUSTOMER.value
                ),
                None,
            )
            if latest_customer is not None:
                thread.customer_message = latest_customer.body
                thread.last_customer_message_at = latest_customer.created_at
                await reopen_if_terminal(
                    db, thread, new_message_length=len(latest_customer.body)
                )

        thread.updated_at = datetime.now(UTC)
        await db.commit()
        logger.info(
            "Synced thread %s (mirakl_thread_id=%s): +%d message(s), reply_state=%s",
            thread.id,
            thread.mirakl_thread_id,
            len(new_messages),
            thread.reply_state,
        )

    @staticmethod
    async def _fetch_active_accounts(
        db: AsyncSession,
    ) -> list[MarketplaceAccount]:
        stmt = select(MarketplaceAccount).where(
            MarketplaceAccount.is_active.is_(True)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())


async def _notify_new_thread(
    thread: SupportThread,
    account: MarketplaceAccount,
    customer_message: str,
) -> None:
    """Post a new-thread line to the Telegram activity channel (best-effort)."""
    from app.services.telegram import TelegramService
    from app.services.text_clean import strip_html

    preview = strip_html(customer_message or "").strip().replace("\n", " ")[:200]
    await TelegramService().send_activity(
        f"🆕 <b>New thread</b> — order {thread.mirakl_order_id} "
        f"({account.marketplace})\n{preview}"
    )


def _get_body(msg: dict[str, Any]) -> str:
    """Return the first non-empty body/content value from a message dict."""
    return msg.get("body", "") or msg.get("content", "") or ""


def _msg_from_type(msg: dict[str, Any]) -> str:
    """Return the uppercase ``from.type`` of a message, or empty string."""
    frm = msg.get("from")
    if isinstance(frm, dict):
        return str(frm.get("type") or "").upper()
    return ""


def _msg_author_name(msg: dict[str, Any]) -> str | None:
    """Return the sender display name of a message, if present."""
    frm = msg.get("from")
    if isinstance(frm, dict):
        return frm.get("display_name") or None
    return None


def _is_customer_message(msg: dict[str, Any]) -> bool:
    """Whether a message was authored by the customer.

    Mirakl M11 uses ``from.type`` of CUSTOMER_USER / SHOP_USER / OPERATOR_USER.
    The legacy fields (``from_operator``, ``author_type``) are honoured as a
    fallback when ``from.type`` is absent.
    """
    ftype = _msg_from_type(msg)
    if ftype in ("CUSTOMER_USER", "CUSTOMER"):
        return True
    if ftype in ("SHOP_USER", "SHOP", "OPERATOR_USER", "OPERATOR"):
        return False
    return (
        not msg.get("from_operator", False)
        and msg.get("author_type", "buyer") in ("buyer", "customer", "")
    )


def _classify_message(msg: dict[str, Any]) -> tuple[str, str]:
    """Map a Mirakl message to ``(direction, author_type)`` enum values."""
    ftype = _msg_from_type(msg)
    if ftype in ("SHOP_USER", "SHOP"):
        return MessageDirection.OUTBOUND.value, MessageAuthorType.SHOP_USER.value
    if ftype in ("OPERATOR_USER", "OPERATOR"):
        return MessageDirection.INBOUND.value, MessageAuthorType.OPERATOR.value
    if ftype in ("CUSTOMER_USER", "CUSTOMER"):
        return MessageDirection.INBOUND.value, MessageAuthorType.CUSTOMER.value
    # Legacy payloads omit ``from.type`` entirely — fall back to the
    # customer/operator heuristic. An explicit but unrecognised type is SYSTEM.
    if not ftype and _is_customer_message(msg):
        return MessageDirection.INBOUND.value, MessageAuthorType.CUSTOMER.value
    return MessageDirection.INBOUND.value, MessageAuthorType.SYSTEM.value


def _parse_msg_date(msg: dict[str, Any]) -> datetime | None:
    """Parse a single message's own timestamp."""
    for key in ("date_created", "date", "created_date"):
        val = msg.get(key)
        if val:
            try:
                return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
    return None


def _sorted_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return messages ordered chronologically (undated entries keep order)."""
    epoch = datetime.min.replace(tzinfo=UTC)
    return sorted(
        messages,
        key=lambda m: (_parse_msg_date(m) is None, _parse_msg_date(m) or epoch),
    )


def _extract_customer_message(messages: list[dict[str, Any]]) -> str:
    """Extract the most recent *incoming* message body (the open ask).

    Prefers the latest customer message; falls back to the latest non-shop
    (e.g. operator-forwarded) message; finally the last message. This keeps
    ``customer_message`` meaningful even on threads where WE replied last.
    """
    ordered = _sorted_messages(messages)
    customer_msgs = [m for m in ordered if _is_customer_message(m)]
    if customer_msgs:
        return _get_body(customer_msgs[-1])
    inbound = [m for m in ordered if _msg_from_type(m) not in ("SHOP_USER", "SHOP")]
    if inbound:
        return _get_body(inbound[-1])
    if ordered:
        return _get_body(ordered[-1])
    return ""


def _derive_reply_state(raw: dict[str, Any]) -> str:
    """Derive the conversation state from a Mirakl thread payload.

    Uses ``metadata.shop_reply_needed_since`` (authoritative "customer is
    waiting") and ``metadata.last_sender``; falls back to the last message's
    sender when metadata is absent (legacy payloads).
    """
    meta = raw.get("metadata") or {}
    if meta.get("shop_reply_needed_since"):
        return ReplyState.NEEDS_REPLY.value

    last_sender = str((meta.get("last_sender") or {}).get("type") or "").upper()
    if not last_sender:
        ordered = _sorted_messages(raw.get("messages", []))
        last_sender = _msg_from_type(ordered[-1]) if ordered else ""

    if last_sender in ("SHOP_USER", "SHOP"):
        return ReplyState.AWAITING_CUSTOMER.value
    if meta:
        # Mirakl had metadata and did not flag a reply as needed → settled.
        return ReplyState.RESOLVED.value
    # No metadata and a non-shop sender spoke last: assume the customer awaits us.
    return ReplyState.NEEDS_REPLY.value


def _parse_last_activity(raw: dict[str, Any]) -> datetime | None:
    """Timestamp of the most recent message in the conversation.

    Prefers Mirakl's ``metadata.last_message_date``; falls back to the latest
    message's own date, then the thread date.
    """
    meta = raw.get("metadata") or {}
    val = meta.get("last_message_date")
    if val:
        try:
            return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass
    ordered = _sorted_messages(raw.get("messages", []))
    if ordered:
        last = _parse_msg_date(ordered[-1])
        if last:
            return last
    return _parse_mirakl_date(raw)


def _build_thread_messages(
    messages: list[dict[str, Any]],
    *,
    default_dt: datetime,
    start_seq: int = 0,
    skip_ids: set[str] | None = None,
) -> list[ThreadMessage]:
    """Build ``ThreadMessage`` rows for every persistable Mirakl message.

    Messages are ordered chronologically and numbered from ``start_seq + 1``.
    Empty-bodied messages are skipped; messages whose ``mirakl_message_id`` is
    in ``skip_ids`` are skipped (idempotent sync). ``thread_id`` is left unset
    so the caller can assign it after the thread is flushed.
    """
    skip_ids = skip_ids or set()
    out: list[ThreadMessage] = []
    seq = start_seq
    for msg in _sorted_messages(messages):
        mid = str(msg.get("id") or "") or None
        if mid is not None and mid in skip_ids:
            continue
        body = _get_body(msg)
        if not body:
            continue
        direction, author_type = _classify_message(msg)
        seq += 1
        out.append(
            ThreadMessage(
                id=uuid.uuid4(),
                direction=direction,
                author_type=author_type,
                author_name=_msg_author_name(msg),
                mirakl_message_id=mid,
                body=body,
                sequence_number=seq,
                created_at=_parse_msg_date(msg) or default_dt,
            )
        )
    return out


def _parse_mirakl_date(raw: dict[str, Any]) -> datetime | None:
    """Extract the original thread creation date from a Mirakl thread payload.

    Mirakl uses ``date_created`` (M11) or ``created_date`` (Connect).
    Falls back to the earliest message date if the thread-level date is absent.
    """
    for key in ("date_created", "created_date", "date"):
        val = raw.get(key)
        if val:
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

    messages = raw.get("messages", [])
    if messages:
        earliest = messages[0].get("date_created") or messages[0].get("date")
        if earliest:
            try:
                return datetime.fromisoformat(earliest.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

    return None
