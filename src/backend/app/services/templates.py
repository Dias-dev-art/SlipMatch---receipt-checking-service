"""Fixed customer messages. Never LLM output."""

from decimal import Decimal

from app.models import Business, Order


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
