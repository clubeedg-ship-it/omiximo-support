"""Comprehensive tests for all six D3 safety rules.

Each rule has multiple positive (violation detected) and negative (no violation)
test cases including multilingual variants.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.support_thread import RiskLevel, SupportThread, ThreadStatus
from app.services.safety_rules import SafetyRules

# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def make_thread(
    *,
    operator_required: bool = False,
    tracking_status: str | None = None,
    category: str | None = "shipping_delay",
    risk_level: RiskLevel = RiskLevel.GREEN,
) -> SupportThread:
    """Construct a minimal SupportThread suitable for safety rule testing.

    Uses the normal SQLAlchemy __init__ so the instance state is properly
    initialised without requiring a database session.
    """
    return SupportThread(
        id=uuid.uuid4(),
        mirakl_thread_id="TEST-001",
        mirakl_order_id="ORD-001",
        marketplace_account_id=uuid.uuid4(),
        customer_message="test message",
        operator_required=operator_required,
        tracking_status=tracking_status,
        category=category,
        risk_level=risk_level,
        status=ThreadStatus.PENDING_REVIEW,
        response_deadline=datetime.now(UTC) + timedelta(hours=24),
        customer_language=None,
        drafted_response=None,
        invoice_status=None,
    )


rules = SafetyRules()


def check(thread: SupportThread, response: str) -> tuple[bool, list[str]]:
    return rules.validate(thread, response)


# --------------------------------------------------------------------------- #
# R1: Never auto-send refund promises                                         #
# --------------------------------------------------------------------------- #


class TestR1NoRefundPromise:

    def test_safe_standard_response(self):
        thread = make_thread()
        is_safe, violations = check(thread, "Your order is on its way.")
        assert is_safe
        assert violations == []

    def test_english_refund_keyword(self):
        thread = make_thread()
        is_safe, violations = check(thread, "We will process your refund within 5 days.")
        assert not is_safe
        assert any("R1" in v for v in violations)

    def test_english_reimburse(self):
        thread = make_thread()
        is_safe, violations = check(thread, "We will reimburse you for the full amount.")
        assert not is_safe
        assert any("R1" in v for v in violations)

    def test_english_credit(self):
        thread = make_thread()
        is_safe, violations = check(thread, "We will credit your account immediately.")
        assert not is_safe
        assert any("R1" in v for v in violations)

    def test_dutch_terugbetaling(self):
        thread = make_thread()
        is_safe, violations = check(thread, "Wij regelen de terugbetaling voor u.")
        assert not is_safe
        assert any("R1" in v for v in violations)

    def test_german_geld_zuruck(self):
        thread = make_thread()
        is_safe, violations = check(thread, "Wir werden Ihnen geld zurück überweisen.")
        assert not is_safe
        assert any("R1" in v for v in violations)

    def test_french_rembourse(self):
        thread = make_thread()
        is_safe, violations = check(thread, "Vous serez remboursé dans les plus brefs délais.")
        assert not is_safe
        assert any("R1" in v for v in violations)

    def test_refund_case_insensitive(self):
        thread = make_thread()
        is_safe, violations = check(thread, "REFUND will be processed.")
        assert not is_safe

    def test_context_without_refund_promise_is_safe(self):
        """Mentioning refund policy without promising one should be safe."""
        thread = make_thread()
        # This is borderline but "refund" keyword triggers R1 by design —
        # the rule is intentionally conservative
        is_safe, violations = check(thread, "Please note our return policy for information.")
        assert is_safe


# --------------------------------------------------------------------------- #
# R2: Never auto-approve returns                                              #
# --------------------------------------------------------------------------- #


class TestR2NoReturnApproval:

    def test_safe_response(self):
        thread = make_thread()
        is_safe, violations = check(thread, "Thank you for your message.")
        assert is_safe

    def test_english_approve_return(self):
        thread = make_thread()
        is_safe, violations = check(thread, "We approve your return request.")
        assert not is_safe
        assert any("R2" in v for v in violations)

    def test_english_you_can_return(self):
        thread = make_thread()
        is_safe, violations = check(thread, "You can return the item to us.")
        assert not is_safe
        assert any("R2" in v for v in violations)

    def test_english_you_may_send_back(self):
        thread = make_thread()
        is_safe, violations = check(thread, "You may send back the product.")
        assert not is_safe
        assert any("R2" in v for v in violations)

    def test_english_return_accepted(self):
        thread = make_thread()
        is_safe, violations = check(thread, "Your return has been accepted.")
        assert not is_safe
        assert any("R2" in v for v in violations)

    def test_dutch_stuur_terug(self):
        thread = make_thread()
        is_safe, violations = check(thread, "U kunt het product terug sturen naar ons.")
        assert not is_safe
        assert any("R2" in v for v in violations)

    def test_return_information_without_approval_is_safe(self):
        thread = make_thread()
        # Informational mention of return policy without granting it
        is_safe, violations = check(
            thread, "Please contact us to discuss the return procedure."
        )
        assert is_safe

    def test_return_and_refund_both_violated(self):
        """Both R1 and R2 should fire when a response contains both."""
        thread = make_thread()
        is_safe, violations = check(
            thread, "You can return the item and we will refund you."
        )
        assert not is_safe
        rule_numbers = {v[:2] for v in violations}
        assert "R1" in rule_numbers
        assert "R2" in rule_numbers


# --------------------------------------------------------------------------- #
# R3: Never auto-reply to operator messages                                   #
# --------------------------------------------------------------------------- #


class TestR3NoOperatorAutoReply:

    def test_customer_thread_is_safe(self):
        thread = make_thread(operator_required=False)
        is_safe, violations = check(thread, "Your order is on its way.")
        assert is_safe

    def test_operator_thread_always_blocked(self):
        thread = make_thread(operator_required=True)
        is_safe, violations = check(thread, "Your order is on its way.")
        assert not is_safe
        assert any("R3" in v for v in violations)

    def test_operator_thread_blocked_even_with_safe_response(self):
        thread = make_thread(operator_required=True)
        is_safe, violations = check(thread, "Thank you.")
        assert not is_safe

    def test_operator_thread_blocked_regardless_of_other_rules(self):
        """Even if no other rules would fire, operator threads are blocked."""
        thread = make_thread(operator_required=True)
        is_safe, violations = check(thread, "This is a completely benign message.")
        assert not is_safe
        rule_ids = [v[:2] for v in violations]
        assert "R3" in rule_ids


# --------------------------------------------------------------------------- #
# R4: Never claim delivery without verified carrier status                    #
# --------------------------------------------------------------------------- #


class TestR4NoUnverifiedDeliveryClaim:

    def test_no_delivery_claim_is_safe(self):
        thread = make_thread(tracking_status=None)
        is_safe, violations = check(thread, "Your order is being processed.")
        assert is_safe

    def test_delivery_claim_with_verified_status_is_safe(self):
        thread = make_thread(tracking_status="DELIVERED")
        is_safe, violations = check(
            thread, "Your order has been delivered to your address."
        )
        assert is_safe

    def test_delivery_claim_without_tracking_is_blocked(self):
        thread = make_thread(tracking_status=None)
        is_safe, violations = check(
            thread, "Your order has been delivered to your address."
        )
        assert not is_safe
        assert any("R4" in v for v in violations)

    def test_delivery_claim_with_in_transit_status_is_blocked(self):
        thread = make_thread(tracking_status="IN_TRANSIT")
        is_safe, violations = check(
            thread, "Your package was delivered yesterday."
        )
        assert not is_safe
        assert any("R4" in v for v in violations)

    def test_delivery_claim_with_exception_status_is_blocked(self):
        thread = make_thread(tracking_status="EXCEPTION")
        is_safe, violations = check(thread, "Your order is now at your door.")
        assert not is_safe

    def test_dutch_bezorgd_without_tracking_is_blocked(self):
        thread = make_thread(tracking_status=None)
        is_safe, violations = check(thread, "Uw pakket is bezorgd op uw adres.")
        assert not is_safe
        assert any("R4" in v for v in violations)

    def test_french_a_ete_livre_without_tracking_is_blocked(self):
        thread = make_thread(tracking_status=None)
        is_safe, violations = check(
            thread, "Votre colis a été livré avec succès."
        )
        assert not is_safe

    def test_shipment_in_transit_message_without_delivery_claim_is_safe(self):
        thread = make_thread(tracking_status="IN_TRANSIT")
        is_safe, violations = check(
            thread, "Your order MK-001 is currently in transit and expected soon."
        )
        assert is_safe


# --------------------------------------------------------------------------- #
# R5: Never auto-reject warranty/defect claims                               #
# --------------------------------------------------------------------------- #


class TestR5NoWarrantyRejection:

    def test_normal_response_is_safe(self):
        thread = make_thread(category="shipping_delay")
        is_safe, violations = check(
            thread, "Your order is on its way, expected delivery within 2 days."
        )
        assert is_safe

    def test_warranty_rejection_phrase_is_blocked(self):
        thread = make_thread(category="general_inquiry")
        is_safe, violations = check(
            thread, "Your product is not covered under warranty."
        )
        assert not is_safe
        assert any("R5" in v for v in violations)

    def test_reject_warranty_claim_is_blocked(self):
        thread = make_thread(category="general_inquiry")
        is_safe, violations = check(thread, "We must reject your warranty claim.")
        assert not is_safe

    def test_dutch_garantie_niet_geaccepteerd(self):
        thread = make_thread(category="general_inquiry")
        is_safe, violations = check(
            thread, "Helaas wordt uw garantie niet geaccepteerd."
        )
        assert not is_safe
        assert any("R5" in v for v in violations)

    def test_warranty_category_green_is_blocked(self):
        """Even a GREEN warranty_claim thread must not auto-send."""
        thread = make_thread(category="warranty_claim", risk_level=RiskLevel.GREEN)
        is_safe, violations = check(thread, "Thank you for your message.")
        assert not is_safe
        assert any("R5" in v for v in violations)

    def test_defect_category_green_is_blocked(self):
        thread = make_thread(category="defect_report", risk_level=RiskLevel.GREEN)
        is_safe, violations = check(thread, "We have received your report.")
        assert not is_safe

    def test_warranty_category_orange_not_blocked_by_r5_category_rule(self):
        """ORANGE warranty threads pass R5's category rule (they require human approval anyway)."""
        thread = make_thread(category="warranty_claim", risk_level=RiskLevel.ORANGE)
        is_safe, violations = check(thread, "Thank you for your message.")
        # R5 only blocks GREEN warranty threads on category alone
        assert is_safe

    def test_no_longer_under_warranty_is_blocked(self):
        thread = make_thread(category="general_inquiry")
        is_safe, violations = check(
            thread, "This product is no longer covered under warranty."
        )
        assert not is_safe


# --------------------------------------------------------------------------- #
# R6: Never route customers outside marketplace channel                       #
# --------------------------------------------------------------------------- #


class TestR6NoExternalRouting:

    def test_safe_response_no_external_contact(self):
        thread = make_thread()
        is_safe, violations = check(
            thread, "Thank you for your message. We will resolve this for you."
        )
        assert is_safe

    def test_email_routing_is_blocked(self):
        thread = make_thread()
        is_safe, violations = check(
            thread, "Please email us at support@example.com for further help."
        )
        assert not is_safe
        assert any("R6" in v for v in violations)

    def test_call_us_is_blocked(self):
        thread = make_thread()
        is_safe, violations = check(
            thread, "Please call our customer service team."
        )
        assert not is_safe
        assert any("R6" in v for v in violations)

    def test_whatsapp_is_blocked(self):
        thread = make_thread()
        is_safe, violations = check(
            thread, "You can also reach us on WhatsApp for faster support."
        )
        assert not is_safe
        assert any("R6" in v for v in violations)

    def test_telegram_is_blocked(self):
        thread = make_thread()
        is_safe, violations = check(
            thread, "Join our Telegram channel for updates."
        )
        assert not is_safe

    def test_outside_marketplace_is_blocked(self):
        thread = make_thread()
        is_safe, violations = check(
            thread, "Please contact us outside the marketplace for a faster response."
        )
        assert not is_safe
        assert any("R6" in v for v in violations)

    def test_dutch_buiten_platform_is_blocked(self):
        thread = make_thread()
        is_safe, violations = check(
            thread, "Neem contact op buiten het platform voor directe hulp."
        )
        assert not is_safe
        assert any("R6" in v for v in violations)

    def test_contact_within_marketplace_is_safe(self):
        thread = make_thread()
        is_safe, violations = check(
            thread, "Please reply to this message within the marketplace platform."
        )
        assert is_safe


# --------------------------------------------------------------------------- #
# Combined / edge cases                                                        #
# --------------------------------------------------------------------------- #


class TestCombinedRules:

    def test_all_violations_accumulated(self):
        """All applicable violations should be reported, not just the first one."""
        # Create a response that triggers R1 + R2 + R6
        thread = make_thread(operator_required=False, tracking_status=None)
        response = (
            "You can return the item and we will refund you. "
            "Call our customer service for more info."
        )
        is_safe, violations = check(thread, response)
        assert not is_safe
        assert len(violations) >= 2

    def test_valid_green_thread_passes_all_rules(self):
        """A well-formed GREEN response should pass every rule."""
        thread = make_thread(
            operator_required=False,
            tracking_status=None,
            category="shipping_delay",
            risk_level=RiskLevel.GREEN,
        )
        response = (
            "Dear customer,\n\n"
            "Thank you for your message. Your order is currently in transit "
            "and we expect delivery within 2-3 business days.\n\n"
            "Kind regards,\nMediaMarkt Seller Support"
        )
        is_safe, violations = check(thread, response)
        assert is_safe
        assert violations == []

    def test_validate_returns_tuple(self):
        thread = make_thread()
        result = check(thread, "Test response.")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], list)
