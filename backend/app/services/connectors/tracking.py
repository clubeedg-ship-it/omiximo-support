"""Tracking connector — shipping status derived from the Mirakl order.

All data flows through Mirakl (no separate carrier API): carrier, tracking
number, tracking URL, order state, and estimated delivery come straight off the
order response. Returns ``{}`` on any error so the pipeline never breaks.
"""

from __future__ import annotations

from typing import Any

from app.models.marketplace_account import MarketplaceAccount
from app.services.connectors.base import ConnectorBase
from app.services.connectors.mirakl import fetch_raw_order, tracking_facts


class TrackingConnector(ConnectorBase):
    """Shipping/tracking context provider, sourced from the Mirakl order."""

    def __init__(self, account: MarketplaceAccount) -> None:
        self._account = account

    async def fetch_context(self, order_id: str) -> dict[str, Any]:
        return tracking_facts(await fetch_raw_order(self._account, order_id))
