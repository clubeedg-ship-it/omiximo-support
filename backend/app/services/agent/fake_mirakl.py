"""Built-in fake Mirakl data for testing/polishing the agent + Telegram flow.

Active only when ``settings.AGENT_FAKE_MIRAKL`` is True. The shapes mirror what
the real connectors return (``connectors/mirakl.py:_flatten_order`` →
order_id / tracking_number / delivery_date / customer_name / shop_name),
extended with a few extra facts a fuller connector would provide (status,
order_date, item, amount) so the agent has something concrete to resolve.

Each scenario also carries an example ``customer_message`` so a test run can be
fired with just a scenario key.
"""

from __future__ import annotations

from typing import Any

# Keyed by a friendly scenario id. order_id doubles as the lookup key.
SCENARIOS: dict[str, dict[str, Any]] = {
    "where_is_order": {
        "customer_message": (
            "Hallo, ik heb mijn bestelling nog niet ontvangen en de track & trace "
            "doet niets. Kan ik weten waar mijn pakket is?"
        ),
        "order": {
            "order_id": "FAKE-1001",
            "status": "SHIPPED",
            "order_date": "2026-06-22",
            "tracking_number": "3SABCD1234567",
            "carrier": "PostNL",
            "delivery_date": "2026-06-29",
            "item": "Philips koffiemachine EP2220",
            "amount": "299.00 EUR",
            "customer_name": "Sanne",
            "shop_name": "MediaMarktSaturn",
        },
        "tracking": {
            "tracking_number": "3SABCD1234567",
            "carrier": "PostNL",
            "status": "IN_TRANSIT",
            "last_event": "Pakket gesorteerd in distributiecentrum Amsterdam",
            "estimated_delivery_date": "2026-06-29",
        },
    },
    "broken_item": {
        "customer_message": (
            "Mijn koffiemachine is kapot aangekomen, het lampje knippert rood en "
            "hij start niet op. Wat nu?"
        ),
        "order": {
            "order_id": "FAKE-1002",
            "status": "DELIVERED",
            "order_date": "2026-06-15",
            "tracking_number": "3SXYZ9876543",
            "carrier": "DHL",
            "delivery_date": "2026-06-18",
            "item": "Philips koffiemachine EP2220",
            "amount": "299.00 EUR",
            "customer_name": "Tom",
            "shop_name": "MediaMarktSaturn",
        },
        "tracking": {
            "tracking_number": "3SXYZ9876543",
            "carrier": "DHL",
            "status": "DELIVERED",
            "last_event": "Afgeleverd bij ontvanger",
            "estimated_delivery_date": "2026-06-18",
        },
    },
    "wrong_item": {
        "customer_message": (
            "Ik had een zwarte koptelefoon besteld maar ik heb een witte ontvangen. "
            "Kan dit omgeruild worden?"
        ),
        "order": {
            "order_id": "FAKE-1003",
            "status": "DELIVERED",
            "order_date": "2026-06-20",
            "tracking_number": "3SDEF4567890",
            "carrier": "PostNL",
            "delivery_date": "2026-06-23",
            "item": "Sony WH-1000XM5 (zwart)",
            "amount": "379.00 EUR",
            "customer_name": "Lisa",
            "shop_name": "MediaMarktSaturn",
        },
        "tracking": {
            "tracking_number": "3SDEF4567890",
            "carrier": "PostNL",
            "status": "DELIVERED",
            "last_event": "Afgeleverd bij buren",
            "estimated_delivery_date": "2026-06-23",
        },
    },
}

DEFAULT_SCENARIO = "where_is_order"


def _by_order_id(order_id: str) -> dict[str, Any] | None:
    for sc in SCENARIOS.values():
        if sc["order"]["order_id"] == order_id:
            return sc
    return None


def fake_order(order_id: str) -> dict[str, Any]:
    """Return the flattened order context for a fake order id (or a default)."""
    sc = _by_order_id(order_id) or SCENARIOS[DEFAULT_SCENARIO]
    return dict(sc["order"])


def fake_tracking(order_id: str) -> dict[str, Any]:
    sc = _by_order_id(order_id) or SCENARIOS[DEFAULT_SCENARIO]
    return dict(sc.get("tracking", {}))


def fake_invoice(order_id: str) -> dict[str, Any]:
    sc = _by_order_id(order_id) or SCENARIOS[DEFAULT_SCENARIO]
    o = sc["order"]
    return {
        "order_id": o["order_id"],
        "invoice_number": f"INV-{o['order_id']}",
        "amount": o.get("amount", ""),
        "status": "PAID",
    }
