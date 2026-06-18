"""Message filter service.

Filters out non-customer messages before they enter the draft pipeline.
This prevents Omiximo's own outbound messages (invoice confirmations, previous
replies), system-generated emails (Zoho Desk notifications), and empty messages
from being stored as inbound customer support threads.

The filter is forward-looking: it does not modify existing data, but prevents
new noise from being ingested.

Usage::

    from app.services.message_filter import MessageFilter

    message_filter = MessageFilter()
    should_process, reason = message_filter.should_process(raw_thread, customer_message)
    if not should_process:
        # log and skip
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Known outbound message patterns (case-insensitive substring matching)        #
# --------------------------------------------------------------------------- #

_OUTBOUND_PATTERNS: list[str] = [
    # German invoice email
    "wir freuen uns sehr, dass sie bei omiximo eingekauft haben",
    # English invoice email
    "we are very pleased that you have shopped with omiximo",
    # German invoice attachment notice
    "ihre rechnung finden sie im anhang",
    # English invoice attachment notice
    "you can find your invoice attached",
]

# --------------------------------------------------------------------------- #
# System email indicators (case-insensitive substring matching)                #
# --------------------------------------------------------------------------- #

_SYSTEM_EMAIL_PATTERNS: list[str] = [
    '<script type="application/ld+json">',
    "desk.zoho.eu/portal/omiximo",
]


class MessageFilter:
    """Filters out non-customer messages before they enter the pipeline.

    Rejects:
    - Messages where the sender is the shop (outbound messages)
    - System-generated emails (Zoho Desk notifications, invoice auto-emails)
    - Messages with no meaningful customer content

    This class is stateless and has no external dependencies.
    """

    def should_process(
        self,
        raw_thread: dict[str, Any],
        customer_message: str,
    ) -> tuple[bool, str | None]:
        """Determine whether a thread should be ingested into the pipeline.

        Applies filter rules in order of specificity:
          1. Sender type check (shop/seller messages)
          2. Known Omiximo outbound patterns
          3. System email detection (Zoho Desk, structured data scripts)
          4. Empty/whitespace content

        Args:
            raw_thread:      Raw thread dict from the Mirakl API (Connect or legacy).
            customer_message: The extracted message body text that would be stored
                             as ``SupportThread.customer_message``.

        Returns:
            A tuple of ``(should_process, rejection_reason)``. When the message
            should be processed, returns ``(True, None)``. When rejected, returns
            ``(False, reason_string)`` explaining why the message was filtered.
        """
        # Rule 1: Reject shop-only threads (pure outbound noise — e.g. invoice
        # emails, notifications). A genuine conversation has at least one
        # customer or operator message; we keep those even if WE replied last,
        # so handled/resolved threads remain visible in the inbox.
        reason = self._check_has_conversation(raw_thread)
        if reason is not None:
            return False, reason

        # Rule 2: Known outbound patterns
        reason = self._check_outbound_patterns(customer_message)
        if reason is not None:
            return False, reason

        # Rule 3: System email detection
        reason = self._check_system_email(customer_message)
        if reason is not None:
            return False, reason

        # Rule 4: Empty/whitespace
        reason = self._check_empty(customer_message)
        if reason is not None:
            return False, reason

        return True, None

    def _check_has_conversation(self, raw_thread: dict[str, Any]) -> str | None:
        """Reject threads that contain only shop/seller messages.

        A thread is a genuine support conversation if at least one message comes
        from the customer or the marketplace operator. Threads with only shop
        messages (invoice confirmations, auto-notifications) are noise.

        Mirakl M11: messages[].from.type ∈ {CUSTOMER_USER, SHOP_USER, OPERATOR_USER}.
        Legacy: messages[].from_operator (bool), author_type (str).
        """
        messages: list[dict[str, Any]] = raw_thread.get("messages", [])
        if not messages:
            return None  # nothing to judge here; later rules handle empties

        def _is_inbound(msg: dict[str, Any]) -> bool:
            ftype = str((msg.get("from") or {}).get("type", "")).upper()
            if ftype in ("CUSTOMER_USER", "CUSTOMER", "OPERATOR_USER", "OPERATOR"):
                return True
            if ftype in ("SHOP_USER", "SHOP"):
                return False
            # Legacy hints
            if msg.get("from_operator", False):
                return True
            return msg.get("author_type", "") in ("buyer", "customer", "operator")

        if not any(_is_inbound(m) for m in messages):
            return "shop_only_thread: no customer or operator message (outbound noise)"

        return None

    def _check_outbound_patterns(self, customer_message: str) -> str | None:
        """Reject if the message matches known Omiximo outbound templates."""
        message_lower = customer_message.lower()
        for pattern in _OUTBOUND_PATTERNS:
            if pattern in message_lower:
                return f"outbound_pattern: matched '{pattern}'"
        return None

    def _check_system_email(self, customer_message: str) -> str | None:
        """Reject system-generated emails (Zoho Desk, structured data scripts)."""
        message_lower = customer_message.lower()
        for pattern in _SYSTEM_EMAIL_PATTERNS:
            if pattern.lower() in message_lower:
                return f"system_email: matched '{pattern}'"
        return None

    def _check_empty(self, customer_message: str) -> str | None:
        """Reject empty or whitespace-only messages."""
        if not customer_message or not customer_message.strip():
            return "empty_message: no content after stripping whitespace"
        return None
