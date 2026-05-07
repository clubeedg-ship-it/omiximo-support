"""Safety rules — hard-coded invariants (architecture decision D3).

These rules are NOT configurable. They are code-level guards that run before
any automated send. The six rules from D3 are implemented here as individual
private methods and composed into SafetyRules.validate().

Rule inventory (D3):
  R1 – Never auto-send refund promises
  R2 – Never auto-approve returns
  R3 – Never auto-reply to marketplace/operator messages (operator_required=True)
  R4 – Never claim delivery without verified carrier status
  R5 – Never auto-reject warranty/defect claims
  R6 – Never route customers outside marketplace message channel

Any violation causes validate() to return is_safe=False with the list of
violated rule descriptions. The draft pipeline treats this as a hard stop.
"""

from __future__ import annotations

import re

from app.models.support_thread import RiskLevel, SupportThread


# Compiled patterns used across multiple rules. Keeping them module-level avoids
# re-compiling on every call.

# R1: refund promise patterns
_REFUND_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brefund\b", re.IGNORECASE),
    re.compile(r"\btransfer(red|ring)?\b.*\bamount\b", re.IGNORECASE),
    re.compile(r"\bwill (credit|reimburse|pay back|pay you back)\b", re.IGNORECASE),
    re.compile(r"\bterugbetal\w*\b", re.IGNORECASE),          # nl: terugbetaling, terugbetalen
    re.compile(r"\b(remboursement|erstattung)\b", re.IGNORECASE),  # fr/de
    re.compile(r"\bgeld zurück\b", re.IGNORECASE),
    re.compile(r"\bvous (serez|sera) remboursé\b", re.IGNORECASE),
]

# R2: return approval patterns
_RETURN_APPROVAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(approve|accept|authoris[e|]|authoriz[e|]).*\breturn\b", re.IGNORECASE),
    re.compile(r"\breturn.*\b(approved|accepted|authorised|authorized)\b", re.IGNORECASE),
    re.compile(r"\byou (can|may|are allowed to) (return|send back)\b", re.IGNORECASE),
    re.compile(r"\b(stuur|sturen|stuurt).*terug\b", re.IGNORECASE),   # nl: stuur/sturen terug
    re.compile(r"\bterug\b.{0,30}\b(stuur|sturen|stuurt)\b", re.IGNORECASE),  # nl: terug sturen
    re.compile(r"\brenvoi (accepté|autorisé)\b", re.IGNORECASE),  # fr
    re.compile(r"\brücksendung.*genehmig\b", re.IGNORECASE),  # de
]

# R4: delivery claim patterns (claiming delivery without carrier verification)
_DELIVERY_CLAIM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(has been|was|is) delivered\b", re.IGNORECASE),
    re.compile(r"\byour (order|parcel|package|shipment) (arrived|delivered)\b", re.IGNORECASE),
    re.compile(r"\bis now at your (door|address|home)\b", re.IGNORECASE),
    re.compile(r"\bbezorgd\b", re.IGNORECASE),          # nl: delivered
    re.compile(r"\ba été livré\b", re.IGNORECASE),      # fr
    re.compile(r"\bwurde geliefert\b", re.IGNORECASE),  # de
]

# R5: warranty/defect rejection patterns
_WARRANTY_REJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(not|no longer)\b.{0,20}\b(covered|eligible|under)\b.{0,20}\bwarranty\b", re.IGNORECASE),
    re.compile(r"\b(reject|deny|declin).{0,20}\b(warranty|claim|defect)\b", re.IGNORECASE),
    re.compile(r"\bgarantie (wordt|wordt niet|niet) (geaccepteerd|gehonoreerd)\b", re.IGNORECASE),  # nl
    re.compile(r"\bgarantie (refusée|rejetée|refus)\b", re.IGNORECASE),  # fr
    re.compile(r"\bgarantie.*abgelehnt\b", re.IGNORECASE),  # de
]

# R6: external routing patterns
_EXTERNAL_ROUTING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bcontact (us|me|our team|our support) (at|via|on|through)\b.{0,30}@", re.IGNORECASE),
    re.compile(r"\bemail (us|me|our team) (at|directly)\b", re.IGNORECASE),
    re.compile(r"\bcall (us|our team|our customer service|customer service)\b", re.IGNORECASE),
    re.compile(r"\bwhatsapp\b", re.IGNORECASE),
    re.compile(r"\btelegram\b", re.IGNORECASE),
    re.compile(r"\bout(side)? (of|the) (marketplace|platform|mirakl|this channel)\b", re.IGNORECASE),
    re.compile(r"\bbuiten (het platform|dit kanaal|mirakl)\b", re.IGNORECASE),  # nl
    re.compile(r"\nen dehors (de la plateforme|du canal)\b", re.IGNORECASE),  # fr
]


class SafetyRules:
    """Stateless validator that applies all D3 hard safety rules.

    This class is intentionally kept stateless so it can be instantiated once
    and reused across the lifetime of the application.
    """

    def validate(
        self,
        thread: SupportThread,
        drafted_response: str,
    ) -> tuple[bool, list[str]]:
        """Apply all six D3 safety rules to *thread* and *drafted_response*.

        Args:
            thread:           The SupportThread being evaluated.
            drafted_response: The text that would be sent to the customer.

        Returns:
            A tuple ``(is_safe, violations)`` where *is_safe* is True only when
            zero violations were detected. *violations* is a list of human-
            readable rule descriptions; empty when is_safe is True.
        """
        violations: list[str] = []

        violations.extend(self._rule_r1_no_refund_promise(drafted_response))
        violations.extend(self._rule_r2_no_return_approval(drafted_response))
        violations.extend(self._rule_r3_no_operator_auto_reply(thread))
        violations.extend(self._rule_r4_no_unverified_delivery_claim(thread, drafted_response))
        violations.extend(self._rule_r5_no_warranty_rejection(thread, drafted_response))
        violations.extend(self._rule_r6_no_external_routing(drafted_response))

        return (len(violations) == 0, violations)

    # ------------------------------------------------------------------ #
    # Individual rule implementations                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _rule_r1_no_refund_promise(response: str) -> list[str]:
        """R1: Never auto-send refund promises.

        Any drafted response that promises a monetary refund must be blocked.
        Refund decisions require human sign-off regardless of risk level.
        """
        for pattern in _REFUND_PATTERNS:
            if pattern.search(response):
                return [
                    "R1: Drafted response contains a refund promise. "
                    "Refund commitments require human review before sending."
                ]
        return []

    @staticmethod
    def _rule_r2_no_return_approval(response: str) -> list[str]:
        """R2: Never auto-approve returns.

        The system must not grant a return without human review — return
        decisions affect inventory and logistics.
        """
        for pattern in _RETURN_APPROVAL_PATTERNS:
            if pattern.search(response):
                return [
                    "R2: Drafted response approves or authorises a return. "
                    "Return authorisations require human review before sending."
                ]
        return []

    @staticmethod
    def _rule_r3_no_operator_auto_reply(thread: SupportThread) -> list[str]:
        """R3: Never auto-reply to marketplace/operator messages.

        When operator_required is True the message came from the marketplace
        operator, not the customer. These are never auto-replied — ever.
        """
        if thread.operator_required:
            return [
                "R3: Thread is flagged as operator_required=True. "
                "Auto-reply to marketplace/operator messages is permanently blocked."
            ]
        return []

    @staticmethod
    def _rule_r4_no_unverified_delivery_claim(
        thread: SupportThread,
        response: str,
    ) -> list[str]:
        """R4: Never claim delivery without a verified carrier status.

        If the response claims an item was delivered but tracking_status is
        not a verified delivered state, the response must be blocked.
        """
        # Check whether the response makes a delivery claim at all
        makes_delivery_claim = any(p.search(response) for p in _DELIVERY_CLAIM_PATTERNS)
        if not makes_delivery_claim:
            return []

        # A delivery claim is allowed only when tracking_status is positively confirmed
        verified_statuses = {"DELIVERED", "delivered", "DELIVERED_TO_NEIGHBOUR"}
        if thread.tracking_status not in verified_statuses:
            return [
                "R4: Drafted response claims delivery, but carrier tracking_status "
                f"is {thread.tracking_status!r} (not a verified delivered state). "
                "Delivery claims require confirmed carrier verification."
            ]
        return []

    @staticmethod
    def _rule_r5_no_warranty_rejection(
        thread: SupportThread,
        response: str,
    ) -> list[str]:
        """R5: Never auto-reject warranty/defect claims.

        The system must not dismiss or deny warranty or defect complaints
        automatically — these require human evaluation.
        """
        for pattern in _WARRANTY_REJECTION_PATTERNS:
            if pattern.search(response):
                return [
                    "R5: Drafted response rejects a warranty or defect claim. "
                    "Warranty/defect rejections require human review before sending."
                ]

        # Also block auto-send for any thread categorised as warranty/defect
        warranty_categories = {"warranty_claim", "defect_report", "product_defect", "warranty"}
        if (
            thread.category
            and thread.category.lower() in warranty_categories
            and thread.risk_level == RiskLevel.GREEN
        ):
            # Even a GREEN-classified warranty thread must not be auto-sent
            return [
                "R5: Thread is categorised as a warranty/defect claim. "
                "Auto-send is blocked regardless of risk_level for warranty categories."
            ]
        return []

    @staticmethod
    def _rule_r6_no_external_routing(response: str) -> list[str]:
        """R6: Never route customers outside the marketplace message channel.

        Directing customers to email addresses, phone numbers, or external
        platforms violates marketplace terms and bypasses the audit trail.
        """
        for pattern in _EXTERNAL_ROUTING_PATTERNS:
            if pattern.search(response):
                return [
                    "R6: Drafted response routes the customer to a channel outside "
                    "the marketplace messaging system (email, phone, WhatsApp, etc.). "
                    "All customer communication must remain within the marketplace channel."
                ]
        return []
