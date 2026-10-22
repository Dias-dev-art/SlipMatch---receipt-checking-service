"""Order state machine and cart math. The ONLY place where `Order.status` changes.

chatting ──request_payment──▶ awaiting_payment ──customer says paid──▶ payment_check
awaiting_payment ──customer changes the cart──▶ chatting
awaiting_payment ──timeout──▶ cancelled (payment_timeout)
payment_check ──owner: Approve──▶ approved
payment_check ──owner: Not received──▶ awaiting_payment (timer restarts)
payment_check ──timeout, owner did nothing──▶ cancelled (owner_timeout)
cancelled ──owner: Restore (money arrived late)──▶ payment_check
chatting | awaiting_payment | payment_check ──owner: Cancel──▶ cancelled (owner_rejected)

Owner actions return False when the order is already in the target state, so repeated clicks
are no-ops; any other wrong state raises InvalidTransition (HTTP 409).
"""

import random
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.models import (
    ACTIVE_STATUSES,
    Business,
    Conversation,
    MenuItem,
    Order,
    OrderItem,
    OrderStatus,
    OrderType,
)
from app.models.base import utcnow

CENT = Decimal("0.01")
_CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I / O: easy to read out loud


class OrderError(Exception):
    """Domain error; maps to HTTP 409."""


class InvalidTransition(OrderError):
    def __init__(self, order: Order, action: str):
        super().__init__(f"Cannot {action} an order that is {order.status.value}")
        self.status = order.status


class MissingFields(OrderError):
    def __init__(self, fields: list[str]):
        super().__init__(f"Missing: {', '.join(fields)}")
        self.fields = fields


@dataclass
class CartLine:
    item: OrderItem
    slug: str


def get_active_order(session: Session, conversation_id: uuid.UUID) -> Order | None:
    return session.exec(
        select(Order)
        .where(Order.conversation_id == conversation_id, col(Order.status).in_(ACTIVE_STATUSES))
        .with_for_update()
    ).first()


def _new_code(session: Session, business_id: uuid.UUID) -> str:
    for _ in range(50):
        code = secrets.choice(_CODE_LETTERS) + f"{secrets.randbelow(1000):03d}"
        taken = session.exec(
            select(Order.id).where(Order.business_id == business_id, Order.code == code)
        ).first()
        if not taken:
            return code
    raise OrderError("Could not generate an order code")


def create_order(session: Session, conversation: Conversation) -> Order:
    order = Order(
        business_id=conversation.business_id,
        conversation_id=conversation.id,
        customer_id=conversation.customer_id,
        code=_new_code(session, conversation.business_id),
    )
    session.add(order)
    session.flush()
    return order


def cart_lines(session: Session, order: Order) -> list[CartLine]:
    rows = session.exec(
        select(OrderItem, MenuItem.slug)
        .join(MenuItem, col(MenuItem.id) == OrderItem.menu_item_id)
        .where(OrderItem.order_id == order.id)
        .order_by(col(OrderItem.name_snapshot), col(OrderItem.note).nulls_first())
    ).all()
    return [CartLine(item, slug) for item, slug in rows]


def recalc(session: Session, order: Order) -> None:
    """Subtotal and total in Decimal. Never from LLM numbers."""
    session.flush()
    subtotal = sum(
        (line.item.unit_price_snapshot * line.item.qty for line in cart_lines(session, order)),
        Decimal("0.00"),
    )
    order.subtotal = subtotal.quantize(CENT)
    order.total = (order.subtotal + order.delivery_fee).quantize(CENT)
    order.updated_at = utcnow()
    session.add(order)


def missing_fields(session: Session, order: Order | None) -> list[str]:
    if order is None:
        return ["items", "order_type"]
    missing = []
    if not cart_lines(session, order):
        missing.append("items")
    if order.order_type is None:
        missing.append("order_type")
    elif order.order_type == OrderType.delivery and not (
        order.address_text or order.location_lat is not None
    ):
        missing.append("address")
    return missing


def set_order_type(order: Order, business: Business, order_type: OrderType) -> None:
    order.order_type = order_type
    # delivery fee is copied from the business at the time it is chosen
    order.delivery_fee = business.delivery_fee if order_type == OrderType.delivery else Decimal(0)


def _unique_total(session: Session, business: Business, base: Decimal) -> Decimal:
    """Add 0.01–0.99 so the owner can find this transfer in the bank quickly."""
    pending = set(
        session.exec(
            select(Order.total).where(
                Order.business_id == business.id,
                col(Order.status).in_((OrderStatus.awaiting_payment, OrderStatus.payment_check)),
            )
        ).all()
    )
    cents = list(range(1, 100))
    random.shuffle(cents)
    for c in cents:
        candidate = base + Decimal(c) * CENT
        if candidate not in pending:
            return candidate
    return base + Decimal(cents[0]) * CENT


def request_payment(session: Session, order: Order, business: Business) -> None:
    """chatting → awaiting_payment: freeze the amount and start the timer."""
    if order.status != OrderStatus.chatting:
        raise InvalidTransition(order, "request payment for")
    missing = missing_fields(session, order)
    if missing:
        raise MissingFields(missing)
    recalc(session, order)
    if business.unique_amount_cents:
        order.total = _unique_total(session, business, order.total)
    order.status = OrderStatus.awaiting_payment
    order.expires_at = utcnow() + timedelta(minutes=business.payment_timeout_minutes)
    session.add(order)


def reopen_for_changes(session: Session, order: Order) -> None:
    """awaiting_payment → chatting: the customer wants to change the cart."""
    if order.status != OrderStatus.awaiting_payment:
        raise InvalidTransition(order, "change")
    order.status = OrderStatus.chatting
    order.expires_at = None
    recalc(session, order)


def mark_paid_by_customer(session: Session, order: Order, business: Business) -> None:
    """awaiting_payment → payment_check. Does NOT confirm payment; the owner does."""
    if order.status != OrderStatus.awaiting_payment:
        raise InvalidTransition(order, "mark as paid")
    order.status = OrderStatus.payment_check
    order.expires_at = utcnow() + timedelta(minutes=business.payment_timeout_minutes)
    order.updated_at = utcnow()
    session.add(order)


class CancelReason:
    payment_timeout = "payment_timeout"
    owner_timeout = "owner_timeout"
    owner_rejected = "owner_rejected"
    customer = "customer"


# Restore is for "the money arrived late": only orders whose payment was requested.
RESTORABLE = {CancelReason.payment_timeout, CancelReason.owner_timeout, CancelReason.owner_rejected}


def lock_order(session: Session, business_id: uuid.UUID, order_id: uuid.UUID) -> Order | None:
    return session.exec(
        select(Order)
        .where(Order.id == order_id, Order.business_id == business_id)
        .with_for_update()
    ).first()


def _touch(order: Order) -> None:
    order.updated_at = utcnow()


def approve(session: Session, order: Order, owner_id: uuid.UUID) -> bool:
    if order.status == OrderStatus.approved:
        return False
    if order.status != OrderStatus.payment_check:
        raise InvalidTransition(order, "approve")
    order.status = OrderStatus.approved
    order.approved_by = owner_id
    order.approved_at = utcnow()
    order.expires_at = None
    _touch(order)
    session.add(order)
    return True


def not_received(session: Session, order: Order, business: Business) -> bool:
    if order.status == OrderStatus.awaiting_payment:
        return False
    if order.status != OrderStatus.payment_check:
        raise InvalidTransition(order, "mark as not received")
    order.status = OrderStatus.awaiting_payment
    order.expires_at = utcnow() + timedelta(minutes=business.payment_timeout_minutes)
    _touch(order)
    session.add(order)
    return True


def restore(session: Session, order: Order, business: Business) -> bool:
    if order.status == OrderStatus.payment_check:
        return False
    if order.status != OrderStatus.cancelled or order.cancelled_reason not in RESTORABLE:
        raise InvalidTransition(order, "restore")
    active = session.exec(
        select(Order.id).where(
            Order.conversation_id == order.conversation_id,
            col(Order.status).in_(ACTIVE_STATUSES),
        )
    ).first()
    if active:
        raise OrderError("The customer already has another open order")
    order.status = OrderStatus.payment_check
    order.cancelled_reason = None
    order.expires_at = utcnow() + timedelta(minutes=business.payment_timeout_minutes)
    _touch(order)
    session.add(order)
    try:
        session.flush()
    except IntegrityError:  # partial unique index: one active order per conversation
        raise OrderError("The customer already has another open order") from None
    return True


def cancel(session: Session, order: Order, reason: str) -> bool:
    if order.status == OrderStatus.cancelled:
        return False
    if order.status not in ACTIVE_STATUSES:
        raise InvalidTransition(order, "cancel")
    order.status = OrderStatus.cancelled
    order.cancelled_reason = reason
    order.expires_at = None
    _touch(order)
    session.add(order)
    return True


def due_orders(session: Session, limit: int = 100) -> list[Order]:
    """Orders whose timer ran out. SKIP LOCKED: two workers never take the same order."""
    return list(
        session.exec(
            select(Order)
            .where(
                col(Order.status).in_((OrderStatus.awaiting_payment, OrderStatus.payment_check)),
                col(Order.expires_at) < utcnow(),
            )
            .order_by(col(Order.expires_at))
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
    )


def expire(session: Session, order: Order) -> str:
    reason = (
        CancelReason.payment_timeout
        if order.status == OrderStatus.awaiting_payment
        else CancelReason.owner_timeout
    )
    cancel(session, order, reason)
    return reason
