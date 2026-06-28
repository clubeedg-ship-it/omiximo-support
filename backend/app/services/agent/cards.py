"""Approval-card rendering for agent actions.

Pure presentation — no I/O, no DB — so it is unit-testable in isolation. Turns a
thread's classification, the order/tracking/knowledge facts the agent gathered,
and the proposed reply (or escalation reason) into ONE self-contained Telegram
HTML card. The reviewer sees the full picture in the single message they
Approve/Deny, instead of scrolling back through separate narration lines.

The live per-tool narration (``runner._narrate``) is unchanged and complements
this card as a real-time ticker.

Safety:
* The customer quote is run through ``strip_html`` (like the UI previews) then
  HTML-escaped, so email markup never leaks into the card.
* The agent's reply body is escaped only — never ``strip_html``'d — because a
  legitimate reply may contain ``<`` / ``>`` that a tag-stripper would eat.
"""

from __future__ import annotations

import html
import re
from typing import Any

from app.services.text_clean import strip_html

_RISK_EMOJI = {"GREEN": "🟢", "ORANGE": "🟠", "RED": "🔴"}
_LANG_LABEL = {"nl": "NL", "en": "EN", "fr": "FR", "de": "DE"}
_MONTHS_NL = (
    "", "jan", "feb", "mrt", "apr", "mei", "jun",
    "jul", "aug", "sep", "okt", "nov", "dec",
)

_CUSTOMER_QUOTE_MAX = 160
_LAST_EVENT_MAX = 90
_TURN_BODY_MAX = 400
# Past this many turns, collapse all but the newest few into an expandable quote.
_CONVO_COLLAPSE_OVER = 5
_CONVO_KEEP_EXPANDED = 2

# Per-action inline-button labels. ``callback_data`` stays approve:/deny:
# regardless, so the webhook is unaffected — only the visible text changes.
_BUTTONS = {
    "send_reply": ("✅ Approve", "❌ Deny"),
    "escalate": ("⤴️ Escalate", "❌ Dismiss"),
}
_DEFAULT_BUTTONS = ("✅ Approve", "❌ Deny")


def button_labels(action_type: str) -> tuple[str, str]:
    """Return ``(approve_label, deny_label)`` for an action type."""
    return _BUTTONS.get(action_type, _DEFAULT_BUTTONS)


def build_action_card(
    *,
    action_type: str,
    thread: Any,
    facts: dict[str, Any],
    body: str,
    messages: list[Any] | None = None,
) -> str:
    """Render the full Telegram HTML card for a proposed agent action.

    ``messages`` is the thread's conversation turns (oldest first). With more
    than one turn the card renders the full threaded history; with one or none
    it falls back to a single customer quote.
    """
    order = _as_dict(facts.get("get_order"))
    tracking = _as_dict(facts.get("get_tracking"))
    knowledge = _as_dict(facts.get("search_knowledge"))

    lines: list[str | None] = [
        _classification_line(thread),
        _order_line(thread, order),
    ]

    convo = _conversation_section(thread, messages)
    if convo:
        lines += ["", *convo]

    fact_lines = _fact_lines(order, tracking, knowledge)
    if fact_lines:
        lines += ["", *fact_lines]

    lines += ["", *_body_block(action_type, body)]

    return "\n".join(line for line in lines if line is not None)


# --------------------------------------------------------------------------- #
# Sections                                                                     #
# --------------------------------------------------------------------------- #


def _classification_line(thread: Any) -> str | None:
    risk = _enum_value(getattr(thread, "risk_level", None))
    category = getattr(thread, "category", None)
    lang = _enum_value(getattr(thread, "customer_language", None))

    parts: list[str] = []
    if risk:
        parts.append(f"{_RISK_EMOJI.get(risk, '⚪')} <b>{_esc(risk)}</b>")
    if category:
        parts.append(_esc(category))
    if lang:
        parts.append(_LANG_LABEL.get(lang, _esc(lang.upper())))
    return " · ".join(parts) if parts else None


def _order_line(thread: Any, order: dict[str, Any]) -> str:
    order_id = getattr(thread, "mirakl_order_id", None) or order.get("order_id")
    head = f"📦 <b>Order {_esc(order_id)}</b>" if order_id else "📦 <b>Order</b>"
    tail = " · ".join(_esc(x) for x in (order.get("customer_name"), order.get("shop_name")) if x)
    return f"{head} — {tail}" if tail else head


def _conversation_section(thread: Any, messages: list[Any] | None) -> list[str] | None:
    turns = list(messages or [])
    if len(turns) > 1:
        return _threaded_conversation(turns)
    # Single turn (or none) → one customer quote, like a fresh thread.
    body = _turn_body(turns[0]) if turns else (getattr(thread, "customer_message", None) or "")
    clean = strip_html(body)
    if not clean:
        return None
    return [f"💬 <b>Klant:</b> <i>{_esc(_truncate(clean, _CUSTOMER_QUOTE_MAX))}</i>"]


def _threaded_conversation(turns: list[Any]) -> list[str]:
    n = len(turns)
    out: list[str] = [f"💬 <b>Gesprek</b> · {n} berichten"]
    if n > _CONVO_COLLAPSE_OVER:
        older, recent = turns[: n - _CONVO_KEEP_EXPANDED], turns[n - _CONVO_KEEP_EXPANDED :]
        collapsed = [f"⤵️ {len(older)} eerdere berichten"]
        for t in older:
            collapsed.append(f"{_turn_who(t)} · {_esc(_truncate(strip_html(_turn_body(t)), 120))}")
        out.append("<blockquote expandable>" + "\n".join(collapsed) + "</blockquote>")
        base, recent_turns = n - _CONVO_KEEP_EXPANDED, recent
    else:
        base, recent_turns = 0, turns
    for i, t in enumerate(recent_turns):
        out += _turn_block(t, newest=(base + i) == (n - 1))
    return out


def _turn_block(turn: Any, *, newest: bool) -> list[str]:
    body = _esc(_truncate(strip_html(_turn_body(turn)), _TURN_BODY_MAX))
    return [_turn_header(turn, newest=newest), f"<blockquote>{body}</blockquote>"]


def _turn_header(turn: Any, *, newest: bool) -> str:
    ts = _fmt_datetime(getattr(turn, "created_at", None))
    when = f" · {ts}" if ts else ""
    tag = " · <i>nieuwste</i>" if newest else ""
    return f"{_turn_who(turn)}{when}{tag}"


def _turn_who(turn: Any) -> str:
    author = str(getattr(turn, "author_type", "") or "").upper()
    return "👤 <b>Klant</b>" if author == "CUSTOMER" else "🧑‍💼 <b>Wij</b>"


def _turn_body(turn: Any) -> str:
    if isinstance(turn, dict):
        return turn.get("body") or ""
    return getattr(turn, "body", "") or ""


def _fmt_datetime(dt: Any) -> str | None:
    try:
        return f"{dt.day} {_MONTHS_NL[dt.month]} {dt.hour:02d}:{dt.minute:02d}"
    except (AttributeError, IndexError, TypeError):
        return None


def _fact_lines(
    order: dict[str, Any], tracking: dict[str, Any], knowledge: dict[str, Any]
) -> list[str]:
    out: list[str] = []

    status = order.get("status")
    if status:
        order_date = order.get("order_date")
        suffix = f" (besteld {_fmt_date(order_date)})" if order_date else ""
        out.append(f"• <b>Status:</b> {_esc(status)}{suffix}")

    item, amount = order.get("item"), order.get("amount")
    if item:
        line = f"• <b>Artikel:</b> {_esc(item)}"
        if amount:
            line += f" — {_fmt_amount(amount)}"
        out.append(line)
    elif amount:
        out.append(f"• <b>Bedrag:</b> {_fmt_amount(amount)}")

    carrier = tracking.get("carrier") or order.get("carrier")
    tnum = tracking.get("tracking_number") or order.get("tracking_number")
    tstatus = tracking.get("status")
    eta = tracking.get("estimated_delivery_date") or order.get("delivery_date")
    last_event = tracking.get("last_event")
    if carrier or tnum or tstatus:
        head = " ".join(_esc(x) for x in (carrier, tnum) if x)
        out.append(f"• <b>Tracking:</b> {head}".rstrip())
        sub = []
        if tstatus:
            sub.append(_esc(tstatus))
        if eta:
            # The date is an estimate only while the parcel is in transit; once
            # delivered it is the actual delivery date, so label it accordingly.
            delivered = (tstatus or "").upper() == "DELIVERED"
            sub.append(f"{'bezorgd' if delivered else 'ETA'} {_fmt_date(eta)}")
        if sub:
            out.append("  " + " · ".join(sub))
        if last_event:
            out.append(f"  ⤷ <i>{_esc(_truncate(strip_html(last_event), _LAST_EVENT_MAX))}</i>")

    entries = knowledge.get("entries")
    if entries:
        n = len(entries)
        out.append(f"• <b>Kennisbank:</b> {n} treffer{'' if n == 1 else 's'}")

    return out


def _body_block(action_type: str, body: str) -> list[str]:
    safe = _esc(body or "")
    if action_type == "escalate":
        return ["⤴️ <b>Escalatie</b>", f"<blockquote>{safe}</blockquote>"]
    return ["✍️ <b>Voorgestelde reactie</b>", f"<blockquote>{safe}</blockquote>"]


# --------------------------------------------------------------------------- #
# Formatting helpers                                                           #
# --------------------------------------------------------------------------- #


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=False) if value is not None else ""


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _fmt_amount(raw: Any) -> str:
    """``'299.00 EUR'`` → ``'€299,00'``; unparseable input passes through escaped."""
    s = str(raw).strip()
    m = re.search(r"\d+(?:[.,]\d{1,2})?", s)
    if not m:
        return _esc(s)
    try:
        val = float(m.group(0).replace(",", "."))
    except ValueError:
        return _esc(s)
    formatted = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"€{formatted}"


def _fmt_date(raw: Any) -> str:
    """``'2026-06-22'`` → ``'22 jun'``; unparseable input passes through escaped."""
    s = str(raw).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if not m:
        return _esc(s)
    month = int(m.group(2))
    if 1 <= month <= 12:
        return f"{int(m.group(3))} {_MONTHS_NL[month]}"
    return _esc(s)
