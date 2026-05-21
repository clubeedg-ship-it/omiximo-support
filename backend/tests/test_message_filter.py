"""Tests for the MessageFilter service.

Verifies that non-customer messages (Omiximo outbound emails, system
notifications, empty messages) are rejected, while real customer messages
pass through.
"""

from __future__ import annotations

import pytest

from app.services.message_filter import MessageFilter


@pytest.fixture
def message_filter() -> MessageFilter:
    return MessageFilter()


# --------------------------------------------------------------------------- #
# Rejection tests                                                              #
# --------------------------------------------------------------------------- #


class TestRejectsOmiximoInvoiceGerman:
    """German invoice email is rejected."""

    def test_rejects_full_german_invoice(self, message_filter: MessageFilter) -> None:
        raw_thread: dict = {"messages": []}
        message = (
            "Sehr geehrter Kunde,\n\n"
            "Wir freuen uns sehr, dass Sie bei Omiximo eingekauft haben. "
            "Ihre Rechnung finden Sie im Anhang.\n\n"
            "Mit freundlichen Grüßen,\nOmiximo B.V."
        )
        should_process, reason = message_filter.should_process(raw_thread, message)
        assert should_process is False
        assert reason is not None
        assert "outbound_pattern" in reason

    def test_rejects_partial_german_invoice(self, message_filter: MessageFilter) -> None:
        """Even if only one pattern appears, the message is rejected."""
        raw_thread: dict = {"messages": []}
        message = "Ihre Rechnung finden Sie im Anhang. Vielen Dank!"
        should_process, reason = message_filter.should_process(raw_thread, message)
        assert should_process is False
        assert "outbound_pattern" in reason

    def test_case_insensitive_german(self, message_filter: MessageFilter) -> None:
        """Pattern matching is case-insensitive."""
        raw_thread: dict = {"messages": []}
        message = "WIR FREUEN UNS SEHR, DASS SIE BEI OMIXIMO EINGEKAUFT HABEN"
        should_process, reason = message_filter.should_process(raw_thread, message)
        assert should_process is False


class TestRejectsOmiximoInvoiceEnglish:
    """English invoice email is rejected."""

    def test_rejects_english_invoice(self, message_filter: MessageFilter) -> None:
        raw_thread: dict = {"messages": []}
        message = (
            "Dear Customer,\n\n"
            "We are very pleased that you have shopped with Omiximo. "
            "You can find your invoice attached.\n\n"
            "Kind regards,\nOmiximo B.V."
        )
        should_process, reason = message_filter.should_process(raw_thread, message)
        assert should_process is False
        assert "outbound_pattern" in reason

    def test_rejects_english_attachment_notice(self, message_filter: MessageFilter) -> None:
        raw_thread: dict = {"messages": []}
        message = "You can find your invoice attached to this email."
        should_process, reason = message_filter.should_process(raw_thread, message)
        assert should_process is False


class TestRejectsZohoDeskNotifications:
    """HTML with Zoho script tags or Zoho Desk URLs are rejected."""

    def test_rejects_zoho_script_tag(self, message_filter: MessageFilter) -> None:
        raw_thread: dict = {"messages": []}
        message = (
            '<html><head><script type="application/ld+json">'
            '{"@context":"http://schema.org"}</script></head>'
            "<body>Some notification</body></html>"
        )
        should_process, reason = message_filter.should_process(raw_thread, message)
        assert should_process is False
        assert "system_email" in reason

    def test_rejects_zoho_desk_url(self, message_filter: MessageFilter) -> None:
        raw_thread: dict = {"messages": []}
        message = (
            "You have a new ticket at "
            "https://desk.zoho.eu/portal/omiximo/tickets/12345"
        )
        should_process, reason = message_filter.should_process(raw_thread, message)
        assert should_process is False
        assert "system_email" in reason

    def test_rejects_zoho_case_insensitive(self, message_filter: MessageFilter) -> None:
        raw_thread: dict = {"messages": []}
        message = "Visit DESK.ZOHO.EU/PORTAL/OMIXIMO for details"
        should_process, reason = message_filter.should_process(raw_thread, message)
        assert should_process is False


class TestRejectsEmptyMessages:
    """Empty or whitespace-only messages are rejected."""

    def test_rejects_empty_string(self, message_filter: MessageFilter) -> None:
        raw_thread: dict = {"messages": []}
        should_process, reason = message_filter.should_process(raw_thread, "")
        assert should_process is False
        assert "empty_message" in reason

    def test_rejects_whitespace_only(self, message_filter: MessageFilter) -> None:
        raw_thread: dict = {"messages": []}
        should_process, reason = message_filter.should_process(raw_thread, "   \n\t  \n  ")
        assert should_process is False
        assert "empty_message" in reason

    def test_rejects_none_equivalent(self, message_filter: MessageFilter) -> None:
        """Empty string (which is what the collector produces for missing body)."""
        raw_thread: dict = {"messages": []}
        should_process, reason = message_filter.should_process(raw_thread, "")
        assert should_process is False


class TestRejectsSenderTypeShop:
    """Messages from the shop/seller are rejected via sender type check."""

    def test_rejects_m11_shop_user(self, message_filter: MessageFilter) -> None:
        """M11 format: from.type = SHOP_USER."""
        raw_thread = {
            "messages": [
                {"from": {"type": "SHOP_USER"}, "body": "We shipped your order."}
            ]
        }
        should_process, reason = message_filter.should_process(
            raw_thread, "We shipped your order."
        )
        assert should_process is False
        assert "sender_is_shop" in reason

    def test_rejects_legacy_author_type_shop(self, message_filter: MessageFilter) -> None:
        """Legacy format: author_type = shop."""
        raw_thread = {
            "messages": [
                {"author_type": "shop", "body": "Your package is on the way."}
            ]
        }
        should_process, reason = message_filter.should_process(
            raw_thread, "Your package is on the way."
        )
        assert should_process is False
        assert "sender_is_shop" in reason

    def test_rejects_legacy_author_type_seller(self, message_filter: MessageFilter) -> None:
        raw_thread = {
            "messages": [
                {"author_type": "seller", "body": "Thank you for your purchase."}
            ]
        }
        should_process, reason = message_filter.should_process(
            raw_thread, "Thank you for your purchase."
        )
        assert should_process is False


# --------------------------------------------------------------------------- #
# Acceptance tests                                                             #
# --------------------------------------------------------------------------- #


class TestAcceptsRealCustomerMessage:
    """Actual customer questions pass through the filter."""

    def test_accepts_delivery_question(self, message_filter: MessageFilter) -> None:
        raw_thread = {
            "messages": [
                {"from": {"type": "CUSTOMER"}, "body": "Where is my package?"}
            ]
        }
        should_process, reason = message_filter.should_process(
            raw_thread, "Where is my package?"
        )
        assert should_process is True
        assert reason is None

    def test_accepts_german_customer_question(self, message_filter: MessageFilter) -> None:
        raw_thread = {
            "messages": [
                {
                    "from": {"type": "CUSTOMER"},
                    "body": "Wo bleibt meine Bestellung? Ich habe vor 5 Tagen bestellt.",
                }
            ]
        }
        should_process, reason = message_filter.should_process(
            raw_thread, "Wo bleibt meine Bestellung? Ich habe vor 5 Tagen bestellt."
        )
        assert should_process is True
        assert reason is None

    def test_accepts_french_customer_message(self, message_filter: MessageFilter) -> None:
        raw_thread: dict = {"messages": []}
        should_process, reason = message_filter.should_process(
            raw_thread,
            "Bonjour, je n'ai toujours pas reçu mon colis. Pouvez-vous me donner un suivi?",
        )
        assert should_process is True
        assert reason is None


class TestAcceptsComplaintMessage:
    """Customer complaints pass through."""

    def test_accepts_defect_complaint(self, message_filter: MessageFilter) -> None:
        raw_thread = {
            "messages": [
                {
                    "from": {"type": "CUSTOMER"},
                    "body": "The product arrived broken. I want a refund immediately!",
                }
            ]
        }
        should_process, reason = message_filter.should_process(
            raw_thread, "The product arrived broken. I want a refund immediately!"
        )
        assert should_process is True
        assert reason is None

    def test_accepts_wrong_item_complaint(self, message_filter: MessageFilter) -> None:
        raw_thread: dict = {"messages": []}
        should_process, reason = message_filter.should_process(
            raw_thread,
            "Ik heb het verkeerde product ontvangen. Dit is niet wat ik besteld heb.",
        )
        assert should_process is True
        assert reason is None


class TestReturnsRejectionReason:
    """Verify the rejection reason string is descriptive and useful."""

    def test_outbound_reason_includes_pattern(self, message_filter: MessageFilter) -> None:
        raw_thread: dict = {"messages": []}
        message = "Wir freuen uns sehr, dass Sie bei Omiximo eingekauft haben."
        _, reason = message_filter.should_process(raw_thread, message)
        assert reason is not None
        assert "outbound_pattern" in reason
        assert "omiximo" in reason.lower()

    def test_system_email_reason_includes_indicator(self, message_filter: MessageFilter) -> None:
        raw_thread: dict = {"messages": []}
        message = '<div><script type="application/ld+json">{}</script></div>'
        _, reason = message_filter.should_process(raw_thread, message)
        assert reason is not None
        assert "system_email" in reason

    def test_sender_reason_includes_type(self, message_filter: MessageFilter) -> None:
        raw_thread = {
            "messages": [{"from": {"type": "SHOP_USER"}, "body": "Hello"}]
        }
        _, reason = message_filter.should_process(raw_thread, "Hello")
        assert reason is not None
        assert "sender_is_shop" in reason
        assert "SHOP_USER" in reason

    def test_empty_reason_is_descriptive(self, message_filter: MessageFilter) -> None:
        raw_thread: dict = {"messages": []}
        _, reason = message_filter.should_process(raw_thread, "")
        assert reason is not None
        assert "empty_message" in reason


# --------------------------------------------------------------------------- #
# Edge cases                                                                   #
# --------------------------------------------------------------------------- #


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_no_messages_in_thread_with_valid_body(self, message_filter: MessageFilter) -> None:
        """Thread with empty messages list but valid customer_message passes."""
        raw_thread: dict = {"messages": []}
        should_process, reason = message_filter.should_process(
            raw_thread, "I have a question about my order."
        )
        assert should_process is True
        assert reason is None

    def test_multiple_messages_only_checks_last(self, message_filter: MessageFilter) -> None:
        """Only the last message's sender type matters."""
        raw_thread = {
            "messages": [
                {"from": {"type": "SHOP_USER"}, "body": "We replied earlier."},
                {"from": {"type": "CUSTOMER"}, "body": "Thanks, but I still have a question."},
            ]
        }
        should_process, reason = message_filter.should_process(
            raw_thread, "Thanks, but I still have a question."
        )
        assert should_process is True
        assert reason is None

    def test_shop_user_last_rejects(self, message_filter: MessageFilter) -> None:
        """If the last message is from shop, reject even if earlier messages are from customer."""
        raw_thread = {
            "messages": [
                {"from": {"type": "CUSTOMER"}, "body": "Where is my order?"},
                {"from": {"type": "SHOP_USER"}, "body": "It was shipped yesterday."},
            ]
        }
        should_process, reason = message_filter.should_process(
            raw_thread, "It was shipped yesterday."
        )
        assert should_process is False

    def test_message_with_only_html_tags_but_no_system_pattern(
        self, message_filter: MessageFilter
    ) -> None:
        """HTML that does not match system patterns passes through."""
        raw_thread: dict = {"messages": []}
        message = "<p>Hallo, ich brauche Hilfe mit meiner Bestellung.</p>"
        should_process, reason = message_filter.should_process(raw_thread, message)
        assert should_process is True
        assert reason is None

    def test_priority_order_sender_before_pattern(self, message_filter: MessageFilter) -> None:
        """Sender type check fires before outbound pattern check."""
        raw_thread = {
            "messages": [
                {
                    "from": {"type": "SHOP_USER"},
                    "body": "Wir freuen uns sehr, dass Sie bei Omiximo eingekauft haben.",
                }
            ]
        }
        _, reason = message_filter.should_process(
            raw_thread,
            "Wir freuen uns sehr, dass Sie bei Omiximo eingekauft haben.",
        )
        # Should be rejected by sender check first (rule 1), not pattern (rule 2)
        assert reason is not None
        assert "sender_is_shop" in reason
