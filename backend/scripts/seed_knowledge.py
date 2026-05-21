"""Seed the knowledge_entries table with initial policy, FAQ, and product data.

Run via: cd backend && uv run python -m scripts.seed_knowledge

Idempotent: checks for existing entries by title before inserting.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.knowledge_entry import KnowledgeEntry

SEED_ENTRIES = [
    {
        "entry_type": "policy",
        "title": "Return Window Policy",
        "content": (
            "Omiximo B.V. offers a 30-day return window from the date of delivery. "
            "The product must be in its original packaging, unused, and with all "
            "accessories included. Products with broken seals (e.g., headphones, "
            "hygiene-sensitive electronics) are excluded from return unless defective. "
            "The customer must initiate the return through the marketplace messaging "
            "system. We do not accept returns shipped without prior authorization."
        ),
        "category_tags": ["return_inquiry", "complaint"],
        "marketplace_tags": [],
        "language": None,
    },
    {
        "entry_type": "policy",
        "title": "Warranty Policy",
        "content": (
            "All products sold by Omiximo B.V. carry a 24-month manufacturer warranty "
            "from the date of delivery. To process a warranty claim, the customer must "
            "provide: (1) the order number, (2) a clear photo of the defect, and "
            "(3) a brief description of the issue. Do not ask the customer to return "
            "the product before the claim is assessed. Warranty does not cover physical "
            "damage caused by misuse, water damage, or unauthorized modifications."
        ),
        "category_tags": ["defect_report", "complaint"],
        "marketplace_tags": [],
        "language": None,
    },
    {
        "entry_type": "policy",
        "title": "Shipping & Delivery",
        "content": (
            "Orders are dispatched within 1 business day of payment confirmation. "
            "Standard delivery times: Netherlands/Belgium 1-3 business days, "
            "France/Germany 3-5 business days. Tracking information is provided via "
            "the marketplace order page. If the tracking shows no update for 24+ hours "
            "after dispatch, advise the customer that carrier scanning delays are normal "
            "and the package is still in transit. Omiximo ships via PostNL (NL/BE) and "
            "DPD (FR/DE)."
        ),
        "category_tags": ["tracking_update", "delivery_confirmation"],
        "marketplace_tags": [],
        "language": None,
    },
    {
        "entry_type": "marketplace_rule",
        "title": "MediaMarkt SLA Rules",
        "content": (
            "MediaMarktSaturn marketplace requirements: (1) All customer messages must "
            "receive a first response within 24 hours. (2) Never direct customers to "
            "external channels (email, phone, website) — all communication must stay "
            "within the marketplace messaging system. (3) Orders above EUR 150 that "
            "require a refund or return must be escalated to a human operator for "
            "manual approval. (4) Product descriptions and responses must be in the "
            "customer's language (Dutch, German, or French depending on country)."
        ),
        "category_tags": [],
        "marketplace_tags": ["MediaMarktSaturn"],
        "language": None,
    },
    {
        "entry_type": "marketplace_rule",
        "title": "Boulanger SLA Rules",
        "content": (
            "Boulanger marketplace requirements: (1) All customer messages must "
            "receive a first response within 48 hours. (2) Return labels must be "
            "generated through the seller portal — never ask the customer to arrange "
            "their own return shipping. (3) All communication must be in French. "
            "(4) Boulanger requires sellers to resolve disputes within 5 business "
            "days or the marketplace may intervene. (5) Never offer partial refunds "
            "without marketplace approval."
        ),
        "category_tags": [],
        "marketplace_tags": ["Boulanger"],
        "language": None,
    },
    {
        "entry_type": "faq",
        "title": "FAQ: Where is my order",
        "content": (
            "When a customer asks about order status or tracking: (1) Confirm that "
            "the order has been dispatched (check order status). (2) Provide the "
            "tracking number and carrier name. (3) Explain that carrier scanning "
            "updates can be delayed up to 24 hours after handoff. (4) If tracking "
            "shows 'delivered' but customer claims non-receipt, escalate to human "
            "review — do not promise re-shipment or refund. (5) If tracking shows "
            "no movement for 5+ business days, escalate for carrier investigation."
        ),
        "category_tags": ["tracking_update", "delivery_confirmation"],
        "marketplace_tags": [],
        "language": None,
    },
    {
        "entry_type": "faq",
        "title": "FAQ: Wrong/damaged item received",
        "content": (
            "When a customer reports receiving a wrong or damaged item: "
            "(1) Acknowledge the issue and apologize for the inconvenience. "
            "(2) Ask the customer to provide a clear photo of the item received "
            "and any visible damage. (3) Do NOT immediately request a return — "
            "wait for photo evidence first. (4) Once photos are received, escalate "
            "to human review for resolution (replacement, refund, or return). "
            "(5) Never blame the carrier or the customer in the response."
        ),
        "category_tags": ["complaint", "defect_report"],
        "marketplace_tags": [],
        "language": None,
    },
    {
        "entry_type": "product_info",
        "title": "Product Info: Small Electronics",
        "content": (
            "Omiximo B.V. primarily sells small consumer electronics: wireless "
            "earbuds, Bluetooth speakers, phone accessories, smart home devices, "
            "and charging equipment. Common issues reported by customers: "
            "(1) Bluetooth pairing failures — advise factory reset (hold power 10s). "
            "(2) Battery not charging — check cable and adapter wattage. "
            "(3) Sound quality complaints — check ear tip fit (earbuds) or firmware "
            "update availability. (4) Device not turning on — attempt charging for "
            "30 minutes before concluding defect. Always suggest basic troubleshooting "
            "before initiating a warranty claim."
        ),
        "category_tags": ["defect_report", "complaint", "general_inquiry"],
        "marketplace_tags": [],
        "language": None,
    },
]


async def seed_knowledge_entries() -> None:
    """Insert seed knowledge entries if they do not already exist."""
    async with AsyncSessionLocal() as session:
        inserted = 0
        skipped = 0

        for entry_data in SEED_ENTRIES:
            # Check if an entry with this title already exists
            stmt = select(KnowledgeEntry).where(
                KnowledgeEntry.title == entry_data["title"]
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing is not None:
                skipped += 1
                continue

            entry = KnowledgeEntry(
                id=uuid.uuid4(),
                **entry_data,
            )
            session.add(entry)
            inserted += 1

        await session.commit()
        print(f"Knowledge seed complete: {inserted} inserted, {skipped} skipped (already exist).")


if __name__ == "__main__":
    asyncio.run(seed_knowledge_entries())
