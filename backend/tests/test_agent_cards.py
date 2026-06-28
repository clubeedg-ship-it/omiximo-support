"""Pure approval-card builder.

A self-contained Telegram card folds the thread classification, the order/
tracking/invoice facts the agent gathered, and the proposed reply (or escalation
reason) into one HTML message. Null-safe (missing facts drop their line) and
HTML-escaped (customer/agent text never breaks the parse).
"""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.support_thread import CustomerLanguage, RiskLevel
from app.services.agent.cards import build_action_card, toolbar


def _turn(author_type, body, day, hour, minute, name=None):
    return SimpleNamespace(
        author_type=author_type,
        author_name=name,
        body=body,
        created_at=datetime(2026, 6, day, hour, minute, tzinfo=timezone.utc),
    )


def _thread(**kw):
    base = dict(
        risk_level=RiskLevel.ORANGE,
        category="complaint",
        customer_language=CustomerLanguage.nl,
        mirakl_order_id="FAKE-1001",
        customer_message="Hallo, ik heb mijn bestelling nog niet ontvangen.",
    )
    base.update(kw)
    return SimpleNamespace(**base)


_FULL_FACTS = {
    "get_order": {
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
    "get_tracking": {
        "tracking_number": "3SABCD1234567",
        "carrier": "PostNL",
        "status": "IN_TRANSIT",
        "last_event": "Pakket gesorteerd in distributiecentrum Amsterdam",
        "estimated_delivery_date": "2026-06-29",
    },
    "search_knowledge": {"entries": [{"title": "a"}, {"title": "b"}]},
}


def test_reply_card_has_classification_facts_and_reply():
    card = build_action_card(
        action_type="send_reply",
        thread=_thread(),
        facts=_FULL_FACTS,
        body="Hallo Sanne, je pakket is onderweg met PostNL.",
    )
    # classification
    assert "🟠" in card
    assert "ORANGE" in card
    assert "complaint" in card
    # order + customer + shop
    assert "FAKE-1001" in card
    assert "Sanne" in card
    assert "MediaMarktSaturn" in card
    # gathered facts
    assert "SHIPPED" in card
    assert "Philips koffiemachine EP2220" in card
    assert "€299,00" in card  # amount localized
    assert "PostNL" in card
    assert "IN_TRANSIT" in card
    assert "29 jun" in card  # ETA localized
    assert "2 treffer" in card  # knowledge hits
    # proposed reply
    assert "Voorgestelde reactie" in card
    assert "Hallo Sanne, je pakket is onderweg met PostNL." in card


def test_reply_card_omits_missing_facts_and_tolerates_none_classification():
    card = build_action_card(
        action_type="send_reply",
        thread=_thread(
            risk_level=None,
            category=None,
            customer_language=None,
            mirakl_order_id="X-1",
            customer_message=None,
        ),
        facts={},
        body="Klaar.",
    )
    assert "Klaar." in card
    assert "X-1" in card
    # no facts gathered → those lines are absent, and no crash on None classification
    assert "Status:" not in card
    assert "Tracking:" not in card
    assert "Klant:" not in card
    assert "Kennisbank" not in card


def test_escalation_card_shows_reason_not_reply():
    card = build_action_card(
        action_type="escalate",
        thread=_thread(),
        facts=_FULL_FACTS,
        body="Defect product vereist een retour-besluit dat ik niet zelf kan nemen.",
    )
    assert "Escalatie" in card
    assert "retour-besluit" in card
    assert "Voorgestelde reactie" not in card


def test_unparseable_amount_and_date_pass_through():
    card = build_action_card(
        action_type="send_reply",
        thread=_thread(),
        facts={"get_order": {"amount": "op aanvraag", "order_date": "binnenkort", "status": "OPEN"}},
        body="ok",
    )
    assert "op aanvraag" in card
    assert "binnenkort" in card


def test_dynamic_text_is_html_escaped():
    card = build_action_card(
        action_type="send_reply",
        thread=_thread(customer_message="<b>boos</b> & ongeduldig"),
        facts={},
        body="1 < 2 & 3 > 0",
    )
    # Quote: markup stripped (like UI previews), remaining text escaped.
    assert "boos" in card
    assert "<b>boos</b>" not in card
    # Body: escaped only — a tag-stripper would have eaten "< 2 & 3 >".
    assert "1 &lt; 2 &amp; 3 &gt; 0" in card
    assert "&amp;" in card


def test_delivered_tracking_reads_as_delivered_not_eta():
    card = build_action_card(
        action_type="send_reply",
        thread=_thread(),
        facts={
            "get_tracking": {
                "carrier": "DHL",
                "tracking_number": "3SXYZ9876543",
                "status": "DELIVERED",
                "estimated_delivery_date": "2026-06-18",
            }
        },
        body="ok",
    )
    assert "bezorgd 18 jun" in card
    assert "ETA" not in card


def test_in_transit_tracking_uses_eta_label():
    card = build_action_card(
        action_type="send_reply",
        thread=_thread(),
        facts={
            "get_tracking": {
                "carrier": "PostNL",
                "tracking_number": "3SABCD1234567",
                "status": "IN_TRANSIT",
                "estimated_delivery_date": "2026-06-29",
            }
        },
        body="ok",
    )
    assert "ETA 29 jun" in card


def test_multi_message_thread_renders_threaded_conversation():
    msgs = [
        _turn("CUSTOMER", "Hallo, waar is mijn pakket? Ik wacht al 10 dagen.", 22, 14, 3),
        _turn("OPERATOR", "Excuses! We zoeken het direct uit.", 22, 15, 10),
        _turn("CUSTOMER", "Nog steeds niets ontvangen, dit duurt te lang.", 23, 9, 0),
    ]
    card = build_action_card(
        action_type="send_reply", thread=_thread(), facts={}, body="ok", messages=msgs
    )
    assert "Gesprek" in card
    assert "3 berichten" in card
    assert "Klant" in card and "Wij" in card
    assert "Nog steeds niets ontvangen, dit duurt te lang." in card
    assert "nieuwste" in card
    assert "22 jun 14:03" in card  # timestamp formatting


def test_single_message_thread_renders_one_quote_not_threaded():
    msgs = [_turn("CUSTOMER", "Hallo, waar is mijn pakket?", 22, 14, 3)]
    card = build_action_card(
        action_type="send_reply", thread=_thread(), facts={}, body="ok", messages=msgs
    )
    assert "Hallo, waar is mijn pakket?" in card
    assert "Gesprek" not in card  # no threaded header for a single turn


def test_no_messages_falls_back_to_customer_message():
    card = build_action_card(
        action_type="send_reply",
        thread=_thread(customer_message="Eenmalig bericht."),
        facts={},
        body="ok",
    )  # messages omitted entirely
    assert "Eenmalig bericht." in card
    assert "Gesprek" not in card


def test_long_conversation_collapses_older_turns():
    msgs = [
        _turn("CUSTOMER" if i % 2 == 0 else "OPERATOR", f"Bericht nummer {i}.", 20, 10, i)
        for i in range(7)
    ]
    card = build_action_card(
        action_type="send_reply", thread=_thread(), facts={}, body="ok", messages=msgs
    )
    assert "7 berichten" in card
    assert "expandable" in card  # older turns collapsed into an expandable quote
    assert "eerdere berichten" in card
    assert "Bericht nummer 6." in card  # newest turn still shown in full
    assert "nieuwste" in card


def _datas(markup):
    return [b["callback_data"] for row in markup["inline_keyboard"] for b in row]


def _texts(markup):
    return [b["text"] for row in markup["inline_keyboard"] for b in row]


def test_toolbar_proposed_reply_has_approve_deny_edit_translate():
    datas = _datas(toolbar("send_reply", "AID", "proposed"))
    assert "approve:AID" in datas
    assert "deny:AID" in datas
    assert "edit:AID" in datas
    assert "tr:AID" in datas


def test_toolbar_proposed_escalate_has_escalate_dismiss():
    markup = toolbar("escalate", "AID", "proposed")
    assert any("Escalate" in t for t in _texts(markup))
    datas = _datas(markup)
    assert "approve:AID" in datas and "deny:AID" in datas
    assert "edit:AID" not in datas  # escalations are not edited/translated


def test_toolbar_editing_has_cancel_only():
    assert _datas(toolbar("send_reply", "AID", "editing")) == ["cancel:AID"]


def test_toolbar_picking_lang_lists_languages_and_back():
    datas = _datas(toolbar("send_reply", "AID", "picking_lang"))
    assert "trset:AID:nl" in datas
    assert "trset:AID:en" in datas
    assert "back:AID" in datas


def test_toolbar_translated_has_back_and_approve():
    datas = _datas(toolbar("send_reply", "AID", "translated"))
    assert "approve:AID" in datas
    assert "back:AID" in datas
