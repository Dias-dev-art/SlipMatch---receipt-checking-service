"""Messages to a customer that are not replies (owner actions, timers). Always fixed templates."""

from typing import Any

from sqlmodel import Session

from app.models import Customer, Direction, Message, Order, Sender
from app.services.outbox import Outbox, get_outbox


def notify_customer(
    session: Session,
    order: Order,
    text: str,
    *,
    outbox: Outbox | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    customer = session.get(Customer, order.customer_id)
    session.add(
        Message(
            business_id=order.business_id,
            conversation_id=order.conversation_id,
            direction=Direction.out,
            sender=Sender.system,
            body=text,
            payload=payload,
        )
    )
    (outbox or get_outbox()).send_text(customer.wa_phone, text)
