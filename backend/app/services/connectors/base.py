"""Abstract connector base (architecture decision D5).

Connectors provide order/shipment/invoice context to the draft pipeline.
Adding a new data source means implementing ConnectorBase and registering the
connector in the pipeline — no changes to the core pipeline logic required.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ConnectorBase(ABC):
    """Abstract base class for all external data connectors.

    Implementors must provide :meth:`fetch_context` which returns a dict of
    contextual data keyed by well-known slot names (e.g. ``tracking_number``,
    ``delivery_date``, ``invoice_url``).

    The dict is merged into the Jinja2 template context before rendering.
    Connectors should never raise on missing data — they should return an empty
    or partial dict and let the template engine use fallbacks.
    """

    @abstractmethod
    async def fetch_context(self, order_id: str) -> dict[str, Any]:
        """Fetch contextual data for the given order.

        Args:
            order_id: The Mirakl order identifier.

        Returns:
            A dict of context slot values. Empty dict is acceptable when no
            data is available. Keys should use the standard slot names:
            ``order_id``, ``tracking_number``, ``delivery_date``,
            ``customer_name``, ``invoice_url``, etc.

        This method must not raise exceptions for missing/unavailable data —
        it should log a warning and return what it can.
        """
        ...

    @property
    def name(self) -> str:
        """Human-readable connector name for logging and audit purposes."""
        return self.__class__.__name__
