"""Pluggable connector package (architecture decision D5)."""

from app.services.connectors.base import ConnectorBase
from app.services.connectors.invoice import InvoiceConnector
from app.services.connectors.mirakl import MiraklConnector
from app.services.connectors.tracking import TrackingConnector

__all__ = [
    "ConnectorBase",
    "InvoiceConnector",
    "MiraklConnector",
    "TrackingConnector",
]
