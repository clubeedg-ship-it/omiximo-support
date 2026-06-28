"""Invoice connector — invoice presence + amount derived from the Mirakl order.

All data flows through Mirakl: the order response exposes ``has_invoice`` and the
total amount. Returns ``{}`` on any error so the pipeline never breaks. Fetching
the full invoice PDF (Mirakl documents endpoint) is a later step.
"""

from __future__ import annotations

from typing import Any

from app.models.marketplace_account import MarketplaceAccount
from app.services.connectors.base import ConnectorBase
from app.services.connectors.mirakl import fetch_raw_order, invoice_facts


class InvoiceConnector(ConnectorBase):
    """Invoice context provider, sourced from the Mirakl order."""

    def __init__(self, account: MarketplaceAccount) -> None:
        self._account = account

    async def fetch_context(self, order_id: str) -> dict[str, Any]:
        return invoice_facts(await fetch_raw_order(self._account, order_id))
