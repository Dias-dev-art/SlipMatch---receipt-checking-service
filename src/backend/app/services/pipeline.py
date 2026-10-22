"""handle_incoming(): one customer message, end to end.

Used by both /dev/simulate and the WhatsApp webhook; only the injected `Outbox` differs
(collect replies vs send through the Graph API). This keeps the simulator honest.
"""

import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlmodel import Session, col, select

from app.agent.executor import ToolContext
from app.agent.loop import Outcome, run_agent
from app.models import (
    ACTIVE_STATUSES,
    Business,
    ContactExclusion,
    Conversation,
    Customer,
    Direction,
    Message,
    MessageType,
    Order,
    Sender,
)
from app.models.base import utcnow
from app.services import events, handoff, orders, templates
from app.services.outbox import CollectingOutbox, Outbox  # noqa: F401  (re-export)

log = logging.getLogger(__name__)

HISTORY_LIMIT = 20


def mask_phone(phone: str) -> str:
    return phone[:4] + "*" * max(len(phone) - 7, 0) + phone[-3:] if len(phone) > 7 else "***"


@dataclass
class IncomingMessage:
    business_id: uuid.UUID
    customer_phone: str
    type: MessageType = MessageType.text
    text: str | None = None
    display_name: str | None = None
    wa_message_id: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    media_id: str | None = None
    # where the downloaded image is served (/media/...), when the download worked
    media_url: str | None = None


def _publish(
    business_id: uuid.UUID,
    conversation_id: uuid.UUID,
    before: tuple | None,
    order: Order | None,
    flags: list[str],
) -> list[str]:
    """Tell the dashboard what changed. Called after commit."""
    published: list[str] = []
    # only orders touched by this message: the active one, or the one that was active before
    relevant = order is not None and (
        order.status in ACTIVE_STATUSES or (before is not None and before[0] == order.id)
    )
    if relevant:
        if before is None or before[0] != order.id:
            published.append(events.ORDER_CREATED)
        elif (order.updated_at, order.status) != (before[1], before[2]):
            published.append(events.ORDER_UPDATED)
    for name in published:
        events.bus.publish(business_id, name, order_id=order.id)
    if events.PAYMENT_CHECK_REQUESTED in flags and order is not None:
        events.bus.publish(business_id, events.PAYMENT_CHECK_REQUESTED, order_id=order.id)
        published.append(events.PAYMENT_CHECK_REQUESTED)
    if events.CONVERSATION_NEEDS_OWNER in flags:
        events.bus.publish(
            business_id, events.CONVERSATION_NEEDS_OWNER, conversation_id=conversation_id
        )
        published.append(events.CONVERSATION_NEEDS_OWNER)
    return published


@dataclass
class PipelineResult:
    conversation_id: uuid.UUID | None
    order: Order | None
    reply: str | None
    outcome: str  # agent outcome, or why the AI stayed silent
    events: list[str] = field(default_factory=list)


def _get_customer(session: Session, incoming: IncomingMessage) -> Customer:
    customer = session.exec(
        select(Customer).where(
            Customer.business_id == incoming.business_id,
            Customer.wa_phone == incoming.customer_phone,
        )
    ).first()
    if customer is None:
        customer = Customer(
            business_id=incoming.business_id,
            wa_phone=incoming.customer_phone,
            display_name=incoming.display_name,
        )
        session.add(customer)
        session.flush()
    elif incoming.display_name and customer.display_name != incoming.display_name:
        customer.display_name = incoming.display_name
        session.add(customer)
    return customer


def _get_conversation(session: Session, customer: Customer) -> tuple[Conversation, bool]:
    """Latest conversation of the customer, row-locked so one message is processed at a time."""
    conversation = session.exec(
        select(Conversation)
        .where(Conversation.customer_id == customer.id)
        .order_by(col(Conversation.created_at).desc())
        .with_for_update()
    ).first()
    if conversation:
        return conversation, False
    conversation = Conversation(business_id=customer.business_id, customer_id=customer.id)
    session.add(conversation)
    session.flush()
    return conversation, True


def _save(
    session: Session,
    conversation: Conversation,
    direction: Direction,
    sender: Sender,
    body: str | None,
    *,
    type_: MessageType = MessageType.text,
    payload: dict[str, Any] | None = None,
    wa_message_id: str | None = None,
) -> Message:
    msg = Message(
        business_id=conversation.business_id,
        conversation_id=conversation.id,
        direction=direction,
        sender=sender,
        type=type_,
        body=body,
        payload=payload,
        wa_message_id=wa_message_id,
    )
    session.add(msg)
    session.flush()
    return msg


def _history(session: Session, conversation: Conversation) -> list[dict[str, str]]:
    rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation.id, col(Message.body).is_not(None))
        .order_by(col(Message.created_at).desc())
        .limit(HISTORY_LIMIT)
    ).all()
    out = []
    for m in reversed(rows):
        role = "user" if m.direction == Direction.in_ else "assistant"
        out.append({"role": role, "content": m.body or ""})
    return out


def _incoming_text(incoming: IncomingMessage) -> str | None:
    if incoming.type == MessageType.text:
        return (incoming.text or "").strip() or None
    if incoming.type == MessageType.location:
        return "[customer shared a location pin for delivery]"
    if incoming.type == MessageType.image:
        caption = f": {incoming.text}" if incoming.text else ""
        return f"[customer sent an image, maybe a payment screenshot{caption}]"
    return None


def is_excluded(session: Session, business_id: uuid.UUID, phone: str) -> bool:
    return (
        session.exec(
            select(ContactExclusion.id).where(
                ContactExclusion.business_id == business_id, ContactExclusion.wa_phone == phone
            )
        ).first()
        is not None
    )


def handle_owner_echo(
    session: Session,
    business_id: uuid.UUID,
    customer_phone: str,
    text: str | None,
    wa_message_id: str | None = None,
) -> str:
    """The owner wrote to a customer from the WhatsApp Business app (coexistence echo).

    The owner is handling this chat now: store the message and pause the AI for 24h.
    """
    if is_excluded(session, business_id, customer_phone):
        return "excluded"
    customer = _get_customer(
        session, IncomingMessage(business_id=business_id, customer_phone=customer_phone)
    )
    conversation, _ = _get_conversation(session, customer)
    handoff.owner_took_over(conversation)
    session.add(conversation)
    _save(
        session,
        conversation,
        Direction.out,
        Sender.owner,
        text,
        wa_message_id=wa_message_id,
    )
    session.commit()
    return "ai_paused"


def handle_incoming(session: Session, incoming: IncomingMessage, outbox: Outbox) -> PipelineResult:
    business = session.get(Business, incoming.business_id)
    if business is None:
        log.info("message for unknown business ignored")
        return PipelineResult(None, None, None, "unknown_business")

    # friends, family, suppliers: nothing is stored and the AI never sees it
    if is_excluded(session, business.id, incoming.customer_phone):
        log.info("message from excluded contact %s ignored", mask_phone(incoming.customer_phone))
        return PipelineResult(None, None, None, "excluded")

    customer = _get_customer(session, incoming)
    conversation, is_new = _get_conversation(session, customer)
    now = utcnow()
    conversation.last_customer_message_at = now
    session.add(conversation)

    payload: dict[str, Any] | None = None
    if incoming.type == MessageType.location:
        payload = {"lat": str(incoming.latitude), "lng": str(incoming.longitude)}
    elif incoming.media_id:
        payload = {"media_id": incoming.media_id}
        if incoming.media_url:
            payload["url"] = incoming.media_url
    text = _incoming_text(incoming)
    _save(
        session,
        conversation,
        Direction.in_,
        Sender.customer,
        text,
        type_=incoming.type,
        payload=payload,
        wa_message_id=incoming.wa_message_id,
    )

    before = orders.get_active_order(session, conversation.id)
    before_state = (before.id, before.updated_at, before.status) if before else None

    def finish(reply: str | None, outcome: str, flags: list[str]) -> PipelineResult:
        session.commit()
        order = (
            orders.get_active_order(session, conversation.id)
            or session.exec(
                select(Order)
                .where(Order.conversation_id == conversation.id)
                .order_by(col(Order.created_at).desc())
            ).first()
        )
        session.commit()
        published = _publish(business.id, conversation.id, before_state, order, flags)
        return PipelineResult(conversation.id, order, reply, outcome, published)

    # gatekeeping: any hit means the AI does not reply
    if conversation.ai_paused_until and conversation.ai_paused_until > now:
        return finish(None, "ai_paused", [])
    if conversation.needs_owner:
        return finish(None, "needs_owner", [])

    # non-text messages are stored by code, not by the LLM
    if incoming.type == MessageType.location and incoming.latitude is not None:
        order = orders.get_active_order(session, conversation.id) or orders.create_order(
            session, conversation
        )
        order.location_lat, order.location_lng = incoming.latitude, incoming.longitude
        session.add(order)
    elif incoming.type == MessageType.image:
        order = orders.get_active_order(session, conversation.id)
        proof = incoming.media_url or incoming.media_id
        if order and proof:
            order.payment_proof_media_url = proof  # hint only, never proof
            session.add(order)
    elif text is None:
        outbox.send_text(customer.wa_phone, templates.TEXT_ONLY)
        _save(session, conversation, Direction.out, Sender.system, templates.TEXT_ONLY)
        return finish(templates.TEXT_ONLY, "unsupported_type", [])

    def send_text(body: str) -> None:
        outbox.send_text(customer.wa_phone, body)
        _save(session, conversation, Direction.out, Sender.system, body)

    def send_image(url: str, caption: str | None) -> None:
        outbox.send_image(customer.wa_phone, url, caption)
        _save(
            session,
            conversation,
            Direction.out,
            Sender.system,
            caption,
            type_=MessageType.image,
            payload={"url": url},
        )

    ctx = ToolContext(session, business, conversation, send_text=send_text, send_image=send_image)
    result = run_agent(ctx, _history(session, conversation), first_message=is_new)

    if result.reply:
        outbox.send_text(customer.wa_phone, result.reply)
    sender = Sender.ai if result.outcome == Outcome.reply else Sender.system
    # every agent turn is logged for debugging (tool calls + results)
    _save(
        session,
        conversation,
        Direction.out,
        sender,
        result.reply,
        payload={"outcome": result.outcome.value, "trace": result.trace},
    )
    log.info("agent %s for %s", result.outcome.value, mask_phone(customer.wa_phone))
    return finish(result.reply, result.outcome.value, ctx.flags)
