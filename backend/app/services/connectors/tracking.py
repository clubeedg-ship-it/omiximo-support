"""Carrier tracking connector — Phase 2 stub.

This connector will integrate with PostNL, MyParcel, and FedEx tracking APIs.
In Phase 1 it returns an empty context dict so the pipeline continues without
tracking data. The interface is defined here so the pipeline can already
reference it and tests can stub it.

Phase 2 implementation notes:
- Resolve carrier from order_context.get("shipping", {}).get("carrier_code")
- Call the appropriate carrier API with the tracking number
- Normalise status to one of: PENDING, IN_TRANSIT, OUT_FOR_DELIVERY,
  DELIVERED, EXCEPTION, UNKNOWN
- Populate the SupportThread.tracking_status field after fetch
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.connectors.base import ConnectorBase

logger = logging.getLogger(__name__)


class TrackingConnector(ConnectorBase):
    """Phase 2 stub: carrier tracking context provider.

    When implemented, this connector will call PostNL / MyParcel / FedEx
    APIs to retrieve real-time shipment status.
    """

    async def fetch_context(self, order_id: str) -> dict[str, Any]:
        """Return empty context — tracking integration is Phase 2.

        This stub ensures the pipeline does not break when TrackingConnector
        is registered; it simply contributes no additional context.
        """
        logger.debug(
            "TrackingConnector.fetch_context called for order %s — Phase 2 stub, returning {}",
            order_id,
        )
        return {}
