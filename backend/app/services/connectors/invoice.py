"""Invoice connector — Phase 2 stub.

This connector will integrate with EasyBill (and potentially other invoicing
systems) to fetch invoice status and download links for order-related threads.

Phase 2 implementation notes:
- Authenticate with the EasyBill API using a per-account API key
- Look up invoice by order reference (Mirakl order ID)
- Return invoice_url, invoice_number, invoice_date, invoice_status
- Cache responses to avoid repeated API calls within a single pipeline run
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.connectors.base import ConnectorBase

logger = logging.getLogger(__name__)


class InvoiceConnector(ConnectorBase):
    """Phase 2 stub: invoice data context provider.

    When implemented, this connector will call EasyBill (or compatible
    invoicing API) to retrieve invoice details for order-related messages.
    """

    async def fetch_context(self, order_id: str) -> dict[str, Any]:
        """Return empty context — invoice integration is Phase 2.

        This stub ensures the pipeline does not break when InvoiceConnector
        is registered; it simply contributes no additional context.
        """
        logger.debug(
            "InvoiceConnector.fetch_context called for order %s — Phase 2 stub, returning {}",
            order_id,
        )
        return {}
