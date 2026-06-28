"""Mirakl connector — order/tracking/invoice context, all from one order fetch.

The Mirakl order response (``GET /api/orders?order_ids=``) is the single source
for everything the agent shows: order facts, shipping/tracking, and invoice
presence. The three pure ``*_facts`` functions slice that response; the three
connector classes fetch the order and apply the matching slice.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.marketplace_account import MarketplaceAccount
from app.services.connectors.base import ConnectorBase
from app.services.mirakl_client import MiraklClient

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Pure extractors (real Mirakl order shape → fact dicts)                       #
# --------------------------------------------------------------------------- #


def order_facts(order: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Mirakl order into the slots the card + agent use."""
    if not order:
        return {}
    customer = order.get("customer") or {}
    channel = order.get("channel") or {}
    return {
        "order_id": str(order.get("order_id", "")),
        "status": order.get("order_state", "") or "",
        "order_date": order.get("created_date", "") or "",
        "item": _item_summary(order.get("order_lines") or []),
        "amount": _amount(order),
        "customer_name": customer.get("firstname", "") or "",
        "shop_name": channel.get("label", "") or "",
        "carrier": _carrier(order),
        "tracking_number": order.get("shipping_tracking", "") or "",
        "tracking_url": order.get("shipping_tracking_url", "") or "",
        "delivery_date": order.get("delivery_date") or order.get("shipping_deadline") or "",
        "has_invoice": bool(order.get("has_invoice")),
    }


def tracking_facts(order: dict[str, Any]) -> dict[str, Any]:
    """Shipping/tracking slice. No live carrier events — Mirakl order only."""
    if not order:
        return {}
    return {
        "tracking_number": order.get("shipping_tracking", "") or "",
        "carrier": _carrier(order),
        "status": order.get("order_state", "") or "",
        "estimated_delivery_date": (
            order.get("delivery_date") or order.get("shipping_deadline") or ""
        ),
        "tracking_url": order.get("shipping_tracking_url", "") or "",
    }


def invoice_facts(order: dict[str, Any]) -> dict[str, Any]:
    """Invoice slice. Mirakl exposes presence + amount; full PDF is a later step."""
    if not order:
        return {}
    return {
        "order_id": str(order.get("order_id", "")),
        "has_invoice": bool(order.get("has_invoice")),
        "amount": _amount(order),
        "status": order.get("order_state", "") or "",
    }


def _carrier(order: dict[str, Any]) -> str:
    return (
        order.get("shipping_company")
        or order.get("shipping_carrier_standard_code")
        or order.get("shipping_carrier_code")
        or ""
    )


def _amount(order: dict[str, Any]) -> str:
    total = order.get("total_price")
    if total is None:
        return ""
    return f"{float(total):.2f} {order.get('currency_iso_code', '')}".strip()


def _item_summary(lines: list[dict[str, Any]]) -> str:
    if not lines:
        return ""
    first = lines[0]
    title = first.get("product_title", "") or ""
    qty = first.get("quantity")
    label = f"{qty}× {title}" if (isinstance(qty, int) and qty > 1) else title
    extra = len(lines) - 1
    return f"{label} (+{extra} meer)" if extra > 0 else label


# --------------------------------------------------------------------------- #
# Connectors                                                                   #
# --------------------------------------------------------------------------- #


async def fetch_raw_order(account: MarketplaceAccount, order_id: str) -> dict[str, Any]:
    """Fetch a raw Mirakl order; ``{}`` on any error (never raises)."""
    try:
        async with MiraklClient(account) as client:
            return await client.fetch_order(order_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Mirakl fetch_order failed for %s: %s", order_id, exc)
        return {}


class MiraklConnector(ConnectorBase):
    """Order facts from the Mirakl Orders API."""

    def __init__(self, account: MarketplaceAccount) -> None:
        self._account = account

    async def fetch_context(self, order_id: str) -> dict[str, Any]:
        return order_facts(await fetch_raw_order(self._account, order_id))
