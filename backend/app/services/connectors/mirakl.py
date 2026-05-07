"""Mirakl connector — wraps MiraklClient.fetch_order for the pipeline context layer."""

from __future__ import annotations

import logging
from typing import Any

from app.models.marketplace_account import MarketplaceAccount
from app.services.connectors.base import ConnectorBase
from app.services.mirakl_client import MiraklClient

logger = logging.getLogger(__name__)


class MiraklConnector(ConnectorBase):
    """Fetches order context from the Mirakl Orders API.

    Args:
        account: The marketplace account whose credentials will be used for
                 authentication.
    """

    def __init__(self, account: MarketplaceAccount) -> None:
        self._account = account

    async def fetch_context(self, order_id: str) -> dict[str, Any]:
        """Fetch Mirakl order data and flatten it into a context dict.

        Returns an empty dict on any error so the pipeline can continue
        without order context (templates will use empty-string fallbacks).
        """
        try:
            async with MiraklClient(self._account) as client:
                order = await client.fetch_order(order_id)
        except Exception as exc:
            logger.warning(
                "MiraklConnector: failed to fetch order %s: %s",
                order_id,
                exc,
            )
            return {}

        return _flatten_order(order)


def _flatten_order(order: dict[str, Any]) -> dict[str, Any]:
    """Extract known context slots from the raw Mirakl order response."""
    shipping: dict[str, Any] = order.get("shipping", {})
    tracking: dict[str, Any] = order.get("tracking", {}) or {}
    customer: dict[str, Any] = order.get("customer", {})

    return {
        "order_id": str(order.get("id", "")),
        "tracking_number": (
            tracking.get("tracking_number")
            or shipping.get("tracking_number", "")
        ),
        "delivery_date": (
            shipping.get("estimated_delivery_date")
            or shipping.get("delivery_date", "")
        ),
        "customer_name": customer.get("firstname", ""),
        "shop_name": str(order.get("shop_name", "")),
    }
