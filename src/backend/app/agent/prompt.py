"""System prompt. Short and explicit; only available menu items. runpod/ copies this format."""

import json
from decimal import Decimal

from app.models import Business, MenuItem, Order
from app.services.orders import CartLine


def _money(value: Decimal) -> float:
    return float(value)


# only used when nothing is available; the normal prompt is unchanged (tool calling is fragile)
EMPTY_MENU = "[] (nothing is available today: say so politely and never name or suggest any food)"


def menu_json(items: list[MenuItem]) -> str:
    return json.dumps(
        [
            {
                "id": i.slug,
                "name": i.name,
                "price": _money(i.price),
                "description": i.description,
                "tags": i.tags,
                **({"category": i.category} if i.category else {}),
            }
            for i in items
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def order_json(order: Order | None, lines: list[CartLine], missing: list[str]) -> str:
    if order is None:
        data = {"status": "no order yet", "cart": [], "missing_fields": missing}
        return json.dumps(data, separators=(",", ":"))
    data = {
        "status": order.status.value,
        "code": order.code,
        "order_type": order.order_type.value if order.order_type else None,
        "address": order.address_text,
        "cart": [
            {
                "id": ln.slug,
                "name": ln.item.name_snapshot,
                "qty": ln.item.qty,
                "unit_price": _money(ln.item.unit_price_snapshot),
                **({"note": ln.item.note} if ln.item.note else {}),
            }
            for ln in lines
        ],
        "subtotal": _money(order.subtotal),
        "delivery_fee": _money(order.delivery_fee),
        "total": _money(order.total),
        "missing_fields": missing,
    }
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def build_system_prompt(
    business: Business,
    menu: list[MenuItem],
    order: Order | None,
    lines: list[CartLine],
    missing: list[str],
    *,
    first_message: bool,
) -> str:
    options = []
    if business.pickup_enabled:
        options.append("pickup")
    if business.delivery_enabled:
        options.append(f"delivery (fee RM{business.delivery_fee:.2f})")
    greeting = ""
    if first_message and business.greeting:
        greeting = (
            f"\nThis is the customer's first message. Start your reply with: {business.greeting}"
        )
    return f"""{_preamble(business)}
You only help customers order from this menu.

MENU (the only items you may offer; use these ids in tools):
{menu_json(menu) if menu else EMPTY_MENU}

ORDER TYPES: {", ".join(options) or "none"}

CURRENT ORDER:
{order_json(order, lines, missing)}

NOW: {next_step(order, missing)}

RULES:
- Change the order ONLY by calling tools. Never write the cart, JSON or a tool name in your reply.
- Use only ids from MENU. If an item is not on the menu, say so and suggest something from MENU.
- Never state a price or total that is not in MENU or in a tool result.
- Customers write Malay, English, Manglish and typos. "tapau", "bungkus", "take away" mean pickup: call set_order_type with pickup. "hantar", "deliver" mean delivery. "nak" means want.
- Ask for what is still missing (missing_fields). For delivery you need the address.
- When the customer has finished choosing, call request_payment. It sends the amount and reference itself; then add only a short friendly line, do not repeat the amount.
- When the customer says they paid ("dah bayar", "sudah transfer", "paid", "done"), call mark_paid_by_customer. Never say the payment is received or confirmed; the owner checks the bank.
- Complaints, refunds or angry customers: call handoff_to_owner.
- Spam or abuse: call ignore_or_flag. Greetings and small talk: reply briefly, then ask what they would like to order.
- Reply in the customer's language. Short, friendly, plain text, no markdown.{greeting}"""


def _preamble(business: Business) -> str:
    return f'You are the Telegram ordering assistant of "{business.name}", a food business in Malaysia.'


def next_step(order: Order | None, missing: list[str]) -> str:
    """One line telling a small model what is expected in the current state."""
    status = order.status.value if order else None
    if status == "awaiting_payment":
        return (
            "Payment details were already sent. If the customer says they paid, call "
            "mark_paid_by_customer. If they want to change the order, call the cart tools."
        )
    if status == "payment_check":
        return (
            "The owner is checking the payment. Do not change the order. Tell the customer "
            "politely to wait; never say the payment is confirmed."
        )
    if not missing:
        return "The order is complete. When the customer is done choosing, call request_payment."
    return "Still missing: " + ", ".join(missing) + "."
