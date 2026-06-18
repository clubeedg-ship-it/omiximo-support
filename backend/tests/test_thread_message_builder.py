"""Unit tests for the conversation-history builders in collector.py.

These cover the mapping from raw Mirakl message payloads to ThreadMessage rows:
direction/author classification, chronological ordering and sequencing,
sender attribution, empty-body skipping, and idempotent (skip_ids) sync.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models.support_thread import ReplyState
from app.models.thread_message import MessageAuthorType, MessageDirection
from app.services.collector import (
    _build_thread_messages,
    _classify_message,
    _derive_reply_state,
    _extract_customer_message,
    _parse_last_activity,
)


def _msg(mid, ftype, name, body, date):
    return {
        "id": mid,
        "from": {"type": ftype, "display_name": name},
        "body": body,
        "date_created": date,
    }


# Realistic Mirakl M11 payload: out-of-order, mixed authors.
SAMPLE = [
    _msg("m2", "CUSTOMER_USER", "Maka Alelishvili", "My PC is broken", "2023-07-12T10:00:00.000Z"),
    _msg("m1", "OPERATOR_USER", "Operator", "Customer reports a fault", "2023-07-12T09:00:00.000Z"),
    _msg("m3", "SHOP_USER", "info@omiximo.nl", "We will help you", "2023-07-13T08:00:00.000Z"),
    _msg("m4", "CUSTOMER_USER", "Maka Alelishvili", "Thanks!", "2023-07-14T08:00:00.000Z"),
]


class TestClassifyMessage:
    def test_shop_user_is_outbound(self):
        d, a = _classify_message({"from": {"type": "SHOP_USER"}})
        assert d == MessageDirection.OUTBOUND.value
        assert a == MessageAuthorType.SHOP_USER.value

    def test_customer_user_is_inbound_customer(self):
        d, a = _classify_message({"from": {"type": "CUSTOMER_USER"}})
        assert d == MessageDirection.INBOUND.value
        assert a == MessageAuthorType.CUSTOMER.value

    def test_operator_user_is_inbound_operator(self):
        d, a = _classify_message({"from": {"type": "OPERATOR_USER"}})
        assert d == MessageDirection.INBOUND.value
        assert a == MessageAuthorType.OPERATOR.value

    def test_unknown_type_falls_back_to_system(self):
        d, a = _classify_message({"from": {"type": "ROBOT"}})
        assert d == MessageDirection.INBOUND.value
        assert a == MessageAuthorType.SYSTEM.value


class TestExtractCustomerMessage:
    def test_returns_latest_customer_body_by_date(self):
        assert _extract_customer_message(SAMPLE) == "Thanks!"

    def test_ignores_shop_and_operator(self):
        msgs = [
            _msg("a", "SHOP_USER", "Us", "shop only", "2023-01-01T00:00:00Z"),
            _msg("b", "OPERATOR_USER", "Op", "operator only", "2023-01-02T00:00:00Z"),
        ]
        # No customer messages → falls back to the latest message body.
        assert _extract_customer_message(msgs) == "operator only"

    def test_empty_list(self):
        assert _extract_customer_message([]) == ""


class TestBuildThreadMessages:
    def test_orders_chronologically_and_sequences(self):
        built = _build_thread_messages(SAMPLE, default_dt=datetime.now(UTC))
        assert [m.sequence_number for m in built] == [1, 2, 3, 4]
        assert [m.mirakl_message_id for m in built] == ["m1", "m2", "m3", "m4"]

    def test_maps_direction_author_and_name(self):
        built = _build_thread_messages(SAMPLE, default_dt=datetime.now(UTC))
        first = built[0]  # the operator message (earliest)
        assert first.direction == MessageDirection.INBOUND.value
        assert first.author_type == MessageAuthorType.OPERATOR.value
        assert first.author_name == "Operator"
        shop = next(m for m in built if m.mirakl_message_id == "m3")
        assert shop.direction == MessageDirection.OUTBOUND.value
        assert shop.author_type == MessageAuthorType.SHOP_USER.value
        assert shop.author_name == "info@omiximo.nl"

    def test_preserves_original_timestamps(self):
        built = _build_thread_messages(SAMPLE, default_dt=datetime.now(UTC))
        assert built[0].created_at == datetime(2023, 7, 12, 9, 0, tzinfo=UTC)

    def test_skips_empty_bodies(self):
        msgs = SAMPLE + [_msg("m5", "SHOP_USER", "Us", "", "2023-07-15T00:00:00Z")]
        built = _build_thread_messages(msgs, default_dt=datetime.now(UTC))
        assert all(m.body for m in built)
        assert "m5" not in [m.mirakl_message_id for m in built]

    def test_skip_ids_continues_sequence(self):
        built = _build_thread_messages(
            SAMPLE,
            default_dt=datetime.now(UTC),
            start_seq=2,
            skip_ids={"m1", "m2"},
        )
        assert [m.mirakl_message_id for m in built] == ["m3", "m4"]
        assert [m.sequence_number for m in built] == [3, 4]

    def test_falls_back_to_default_dt_when_undated(self):
        fallback = datetime(2020, 1, 1, tzinfo=UTC)
        msgs = [{"id": "x", "from": {"type": "CUSTOMER_USER"}, "body": "hi"}]
        built = _build_thread_messages(msgs, default_dt=fallback)
        assert built[0].created_at == fallback


class TestDeriveReplyState:
    def test_needs_reply_when_shop_reply_needed_since_set(self):
        raw = {"metadata": {"shop_reply_needed_since": "2026-06-01T00:00:00Z",
                            "last_sender": {"type": "CUSTOMER_USER"}}}
        assert _derive_reply_state(raw) == ReplyState.NEEDS_REPLY.value

    def test_awaiting_customer_when_shop_sent_last(self):
        raw = {"metadata": {"shop_reply_needed_since": None,
                            "last_sender": {"type": "SHOP_USER"}}}
        assert _derive_reply_state(raw) == ReplyState.AWAITING_CUSTOMER.value

    def test_resolved_when_no_reply_needed_and_customer_last(self):
        raw = {"metadata": {"shop_reply_needed_since": None,
                            "last_sender": {"type": "CUSTOMER_USER"}}}
        assert _derive_reply_state(raw) == ReplyState.RESOLVED.value

    def test_legacy_no_metadata_customer_last_needs_reply(self):
        raw = {"messages": [{"from": {"type": "CUSTOMER_USER"}, "body": "hi",
                            "date_created": "2026-06-01T00:00:00Z"}]}
        assert _derive_reply_state(raw) == ReplyState.NEEDS_REPLY.value

    def test_legacy_no_metadata_shop_last_awaiting(self):
        raw = {"messages": [
            {"from": {"type": "CUSTOMER_USER"}, "body": "hi", "date_created": "2026-06-01T00:00:00Z"},
            {"from": {"type": "SHOP_USER"}, "body": "reply", "date_created": "2026-06-02T00:00:00Z"},
        ]}
        assert _derive_reply_state(raw) == ReplyState.AWAITING_CUSTOMER.value


class TestParseLastActivity:
    def test_prefers_metadata_last_message_date(self):
        raw = {"metadata": {"last_message_date": "2026-06-10T16:32:49.872Z"},
               "messages": [{"date_created": "2023-01-01T00:00:00Z"}]}
        assert _parse_last_activity(raw) == datetime(2026, 6, 10, 16, 32, 49, 872000, tzinfo=UTC)

    def test_falls_back_to_last_message_date(self):
        raw = {"messages": [
            {"date_created": "2026-05-01T00:00:00Z"},
            {"date_created": "2026-05-09T00:00:00Z"},
        ]}
        assert _parse_last_activity(raw) == datetime(2026, 5, 9, tzinfo=UTC)

    def test_falls_back_to_thread_date(self):
        raw = {"date_created": "2026-04-01T00:00:00Z", "messages": []}
        assert _parse_last_activity(raw) == datetime(2026, 4, 1, tzinfo=UTC)
