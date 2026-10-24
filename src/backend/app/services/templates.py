"""Fixed customer messages. Never LLM output."""

from decimal import Decimal

from app.models import Business, MenuItem, Order


def rm(amount: Decimal) -> str:
    return f"RM{amount:.2f}"


def payment_request(order: Order, business: Business) -> str:
    lines = [f"Pay {rm(order.total)}, reference {order.code}"]
    if business.payment_instructions:
        lines.append(business.payment_instructions)
    lines.append(
        f"Please pay within {business.payment_timeout_minutes} minutes and tell us when done."
    )
    return "\n".join(lines)


FALLBACK = "Sorry, something went wrong on our side. The owner will reply to you here soon."
HANDOFF = "Thank you! I have passed your message to the owner. They will reply to you here soon."
TEXT_ONLY = "Sorry, I can only read text messages. Please type your order."
OPEN_SHOP_LINK = (
    "Hi! To order, please open your shop's Telegram link or scan the QR code at the shop."
)


ASK_AGAIN = "Sorry, I didn't catch that. Which items would you like, and how many?"
ASK_PHONE = (
    "Almost done! Please tap the button below to share your phone number, "
    "so the shop can reach you about this order."
)
PHONE_THANKS = "Thanks! 📱"
OWNER_REPLY_PREFIX = "👩‍🍳 {shop}:"

_NEXT_QUESTION = {
    "items": "What would you like to order?",
    "order_type": "Pickup or delivery?",
    "address": "What's the delivery address?",
}


def cart_summary(order: Order, lines: list) -> str:
    """The real cart, written by code: the AI's own words about the cart are not trusted."""
    rows = ["Your order:"]
    for ln in lines:
        line_total = ln.item.unit_price_snapshot * ln.item.qty
        rows.append(f"• {ln.item.qty}× {ln.item.name_snapshot} – {rm(line_total)}")
    if order.delivery_fee:
        rows.append(f"• Delivery – {rm(order.delivery_fee)}")
    rows.append(f"Total: {rm(order.total)}")
    return "\n".join(rows)


def next_question(missing: list[str]) -> str:
    for field in ("items", "order_type", "address"):
        if field in missing:
            return _NEXT_QUESTION[field]
    return "Anything else, or shall I send the payment details?"


def phone_request(order: Order, lines: list) -> str:
    return cart_summary(order, lines) + "\n\n" + ASK_PHONE


def owner_reply(business: Business, text: str) -> str:
    return OWNER_REPLY_PREFIX.format(shop=business.name) + "\n" + text


def welcome(business: Business, first_name: str | None, menu: list[MenuItem]) -> str:
    """Reply to /start: says which shop this is (one bot serves many) and shows the menu."""
    hi = f"Hi {first_name}!" if first_name else "Hi!"
    lines = [f"{hi} You're ordering from {business.name} 😊"]
    if not menu:
        return "\n\n".join([lines[0], NOTHING_AVAILABLE])
    lines += ["", menu_list(menu), "", order_types_line(business)]
    # the owner's own greeting (Settings) replaces the closing question
    lines += ["", business.greeting or "What would you like today?"]
    return "\n".join(lines)


NOTHING_AVAILABLE = "Sorry, nothing is available to order right now. Please check again later."


def menu_list(menu: list[MenuItem]) -> str:
    return "\n".join(["Menu:", *(f"• {item.name} – {rm(item.price)}" for item in menu)])


def menu_reply(menu: list[MenuItem]) -> str:
    """The real menu, written by code: seen live, the model invented items for a 1-item menu."""
    if not menu:
        return NOTHING_AVAILABLE
    return menu_list(menu) + "\n\nWhat would you like?"


def order_types_line(business: Business) -> str:
    if business.pickup_enabled and business.delivery_enabled:
        return f"Pickup or delivery (+{rm(business.delivery_fee)})."
    if business.delivery_enabled:
        return f"Delivery only (+{rm(business.delivery_fee)})."
    return "Pickup only."


def order_type_unavailable(business: Business, wanted: str) -> str:
    other = "pickup" if wanted == "delivery" else "delivery"
    return f"Sorry, {business.name} doesn't do {wanted} right now, only {other}."


def _pickup_or_delivery(order: Order) -> str:
    if order.order_type is not None and order.order_type.value == "delivery":
        return "We will deliver it to you soon."
    return "We will tell you when it is ready for pickup."


def confirmed(order: Order) -> str:
    # fixed template sent only after the owner checked the bank and pressed Approve
    return f"Payment received, thank you! Order {order.code} is confirmed. " + _pickup_or_delivery(
        order
    )


def not_received(order: Order, business: Business) -> str:
    return (
        f"We don't see your payment for order {order.code} yet. Please check and pay "
        f"{rm(order.total)} with reference {order.code}, then tell us when done. "
        f"We will keep the order for {business.payment_timeout_minutes} more minutes."
    )


def cancelled_payment_timeout(order: Order) -> str:
    return (
        f"Order {order.code} was cancelled because we did not receive the payment in time. "
        "You can order again any time."
    )


def cancelled_owner_timeout(order: Order) -> str:
    return (
        f"Sorry, we could not confirm your payment for order {order.code} in time, so the order "
        "was cancelled. If you already paid, reply here and we will check it."
    )


def cancelled_by_owner(order: Order) -> str:
    return f"Sorry, order {order.code} was cancelled by the shop. Reply here if you have questions."
