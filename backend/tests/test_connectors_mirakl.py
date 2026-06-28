"""Mirakl order extractors: map the real Connect/OR11 order shape to fact dicts.

Everything the agent shows (order facts, tracking, invoice) is derived from one
Mirakl order response — there is no separate carrier/invoice API.
"""

from app.services.connectors.mirakl import invoice_facts, order_facts, tracking_facts

# Sanitized fixture mirroring the real /api/orders?order_ids= response shape.
SAMPLE_ORDER = {
    "order_id": "01015_183824195-A",
    "order_state": "SHIPPED",
    "created_date": "2026-06-22T10:00:00Z",
    "currency_iso_code": "EUR",
    "total_price": 299.0,
    "customer": {"firstname": "Sanne", "lastname": "J"},
    "channel": {"code": "mm", "label": "MediaMarkt"},
    "shipping_company": "PostNL",
    "shipping_carrier_standard_code": None,
    "shipping_tracking": "3SABCD1234567",
    "shipping_tracking_url": "https://postnl.nl/track/3SABCD1234567",
    "delivery_date": None,
    "shipping_deadline": "2026-06-29T00:00:00Z",
    "has_invoice": True,
    "order_lines": [
        {"product_title": "Philips koffiemachine EP2220", "quantity": 1, "total_price": 299.0},
    ],
}


def test_order_facts_maps_real_schema():
    f = order_facts(SAMPLE_ORDER)
    assert f["order_id"] == "01015_183824195-A"
    assert f["status"] == "SHIPPED"
    assert f["order_date"] == "2026-06-22T10:00:00Z"
    assert f["item"] == "Philips koffiemachine EP2220"
    assert f["amount"] == "299.00 EUR"
    assert f["customer_name"] == "Sanne"
    assert f["shop_name"] == "MediaMarkt"
    assert f["carrier"] == "PostNL"
    assert f["tracking_number"] == "3SABCD1234567"
    assert f["tracking_url"] == "https://postnl.nl/track/3SABCD1234567"
    assert f["delivery_date"] == "2026-06-29T00:00:00Z"  # falls back to shipping_deadline
    assert f["has_invoice"] is True


def test_order_facts_quantity_and_multiple_lines():
    order = dict(SAMPLE_ORDER, order_lines=[
        {"product_title": "Koptelefoon", "quantity": 2},
        {"product_title": "Kabel", "quantity": 1},
    ])
    f = order_facts(order)
    assert f["item"] == "2× Koptelefoon (+1 meer)"


def test_tracking_facts_from_order():
    f = tracking_facts(SAMPLE_ORDER)
    assert f["tracking_number"] == "3SABCD1234567"
    assert f["carrier"] == "PostNL"
    assert f["status"] == "SHIPPED"
    assert f["estimated_delivery_date"] == "2026-06-29T00:00:00Z"
    assert f["tracking_url"] == "https://postnl.nl/track/3SABCD1234567"


def test_invoice_facts_from_order():
    f = invoice_facts(SAMPLE_ORDER)
    assert f["order_id"] == "01015_183824195-A"
    assert f["has_invoice"] is True
    assert f["amount"] == "299.00 EUR"
    assert f["status"] == "SHIPPED"


def test_empty_order_yields_empty_dicts():
    assert order_facts({}) == {}
    assert tracking_facts({}) == {}
    assert invoice_facts({}) == {}
