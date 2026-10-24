"""handle_incoming(): one customer message, end to end.

Used by both /dev/simulate and the Telegram webhook; only the injected `Outbox` differs
(collect replies vs send through the Bot API). This keeps the simulator honest.
"""

import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlmodel import Session, col, select

from app.agent.executor import ToolContext, execute_tool
from app.agent.loop import Outcome, run_agent
from app.models import (
    ACTIVE_STATUSES,
    Business,
    Conversation,
    Customer,
    Direction,
    Message,
    MessageType,
    Order,
    OrderStatus,
    Sender,
)
from app.models.base import utcnow
from app.services import events, handoff, orders, templates
from app.services.menu import available_items
from app.services.outbox import CollectingOutbox, Outbox  # noqa: F401  (re-export)

log = logging.getLogger(__name__)

HISTORY_LIMIT = 20


def mask_id(chat_id: str) -> str:
    """Customer chat ids are personal data: never log them in full."""
    return (
        chat_id[:3] + "*" * max(len(chat_id) - 5, 0) + chat_id[-2:] if len(chat_id) > 5 else "***"
    )


@dataclass
class IncomingMessage:
    business_id: uuid.UUID
    chat_id: str  # Telegram chat id of the customer
    type: MessageType = MessageType.text
    text: str | None = None
    display_name: str | None = None
    username: str | None = None  # Telegram @username, without @
    phone: str | None = None  # known phone (the simulator); Telegram shares it via handle_contact
    message_id: str | None = None
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
            Customer.tg_chat_id == incoming.chat_id,
        )
    ).first()
    if customer is None:
        customer = Customer(business_id=incoming.business_id, tg_chat_id=incoming.chat_id)
    # Telegram names and usernames can change; keep the latest
    for attr, value in (
        ("display_name", incoming.display_name),
        ("tg_username", incoming.username),
        ("phone", incoming.phone),
    ):
        if value and getattr(customer, attr) != value:
            setattr(customer, attr, value)
    session.add(customer)
    session.flush()
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
    tg_message_id: str | None = None,
) -> Message:
    msg = Message(
        business_id=conversation.business_id,
        conversation_id=conversation.id,
        direction=direction,
        sender=sender,
        type=type_,
        body=body,
        payload=payload,
        tg_message_id=tg_message_id,
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


def _tool_context(
    session: Session,
    business: Business,
    conversation: Conversation,
    customer: Customer,
    outbox: Outbox,
) -> ToolContext:
    """Tools send through the outbox and every message they send is stored."""

    def send_text(body: str) -> None:
        outbox.send_text(customer.tg_chat_id, body)
        _save(session, conversation, Direction.out, Sender.system, body)

    def send_image(url: str, caption: str | None) -> None:
        outbox.send_image(customer.tg_chat_id, url, caption)
        _save(
            session,
            conversation,
            Direction.out,
            Sender.system,
            caption,
            type_=MessageType.image,
            payload={"url": url},
        )

    def ask_phone(text: str) -> None:
        outbox.ask_phone(customer.tg_chat_id, text)
        _save(session, conversation, Direction.out, Sender.system, text)

    return ToolContext(
        session,
        business,
        conversation,
        send_text=send_text,
        send_image=send_image,
        ask_phone=ask_phone,
    )


def _can_start_over(session: Session, conversation: Conversation) -> bool:
    """Not while the owner has the chat, or while a payment is pending or being checked."""
    if conversation.needs_owner or (
        conversation.ai_paused_until and conversation.ai_paused_until > utcnow()
    ):
        return False
    order = orders.get_active_order(session, conversation.id)
    return order is None or order.status == OrderStatus.chatting


def send_welcome(
    session: Session,
    business: Business,
    incoming: IncomingMessage,
    first_name: str | None,
    outbox: Outbox,
) -> str:
    """The customer opened the shop with /start: greet them before they write anything."""
    customer = _get_customer(session, incoming)
    conversation, is_new = _get_conversation(session, customer)
    if conversation.ai_paused_until and not conversation.needs_owner:
        # the customer pressed Start: they want the bot again, even if the owner replied earlier
        handoff.resume_ai(conversation)
        session.add(conversation)
    if not is_new and _can_start_over(session, conversation):
        # a fresh chat for the AI: small models copy their old replies from the history
        conversation = Conversation(business_id=business.id, customer_id=customer.id)
        session.add(conversation)
        session.flush()
    text = templates.welcome(business, first_name, available_items(session, business.id))
    outbox.send_text(customer.tg_chat_id, text)
    _save(session, conversation, Direction.out, Sender.system, text)
    session.commit()
    return "welcome"


def handle_contact(
    session: Session, incoming: IncomingMessage, phone: str, outbox: Outbox
) -> PipelineResult:
    """The customer tapped "Share phone number": save it and finish the checkout by code."""
    business = session.get(Business, incoming.business_id)
    incoming.phone = "".join(ch for ch in phone if ch.isdigit())
    customer = _get_customer(session, incoming)
    conversation, _ = _get_conversation(session, customer)
    _save(
        session,
        conversation,
        Direction.in_,
        Sender.customer,
        "[customer shared their phone number]",
        tg_message_id=incoming.message_id,
    )
    before = orders.get_active_order(session, conversation.id)
    before_state = (before.id, before.updated_at, before.status) if before else None
    outbox.send_text(customer.tg_chat_id, templates.PHONE_THANKS, remove_keyboard=True)
    _save(session, conversation, Direction.out, Sender.system, templates.PHONE_THANKS)

    outcome = "phone_saved"
    ctx = _tool_context(session, business, conversation, customer, outbox)
    order = ctx.order
    owner_has_chat = conversation.needs_owner or (
        conversation.ai_paused_until and conversation.ai_paused_until > utcnow()
    )
    if (
        not owner_has_chat
        and order is not None
        and order.status == OrderStatus.chatting
        and not orders.missing_fields(session, order)
    ):
        result = execute_tool(ctx, "request_payment", {})
        outcome = "payment_sent" if result.get("payment_sent") else outcome
    session.commit()
    order = orders.get_active_order(session, conversation.id)
    published = _publish(business.id, conversation.id, before_state, order, ctx.flags)
    return PipelineResult(conversation.id, order, None, outcome, published)


def handle_incoming(session: Session, incoming: IncomingMessage, outbox: Outbox) -> PipelineResult:
    business = session.get(Business, incoming.business_id)
    if business is None:
        log.info("message for unknown business ignored")
        return PipelineResult(None, None, None, "unknown_business")

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
        tg_message_id=incoming.message_id,
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
        outbox.send_text(customer.tg_chat_id, templates.TEXT_ONLY)
        _save(session, conversation, Direction.out, Sender.system, templates.TEXT_ONLY)
        return finish(templates.TEXT_ONLY, "unsupported_type", [])

    ctx = _tool_context(session, business, conversation, customer, outbox)
    result = run_agent(ctx, _history(session, conversation), first_message=is_new)

    if result.reply:
        outbox.send_text(customer.tg_chat_id, result.reply)
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
    log.info("agent %s for %s", result.outcome.value, mask_id(customer.tg_chat_id))
    return finish(result.reply, result.outcome.value, ctx.flags)
