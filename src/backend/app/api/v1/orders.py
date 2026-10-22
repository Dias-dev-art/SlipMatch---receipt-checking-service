import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.core.deps import CurrentBusiness, CurrentOwner, SessionDep
from app.models import Business, Order, OrderStatus
from app.schemas.order import OrderOut, order_out
from app.services import events, orders, templates
from app.services.notify import notify_customer

router = APIRouter(prefix="/orders", tags=["orders"])


class CancelIn(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


@router.get("", response_model=list[OrderOut])
def list_orders(
    session: SessionDep,
    business: CurrentBusiness,
    status_: Annotated[list[OrderStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[OrderOut]:
    """Newest first, with items. `?status=payment_check&status=awaiting_payment` filters."""
    query = select(Order).where(Order.business_id == business.id)
    if status_:
        query = query.where(col(Order.status).in_(status_))
    query = query.order_by(col(Order.created_at).desc()).offset(offset).limit(limit)
    return [order_out(session, o) for o in session.exec(query).all()]


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: uuid.UUID, session: SessionDep, business: CurrentBusiness) -> OrderOut:
    order = session.exec(
        select(Order).where(Order.id == order_id, Order.business_id == business.id)
    ).first()
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order_out(session, order)


def _act(
    session: Session,
    business: Business,
    order_id: uuid.UUID,
    action: Callable[[Order], bool],
    message: Callable[[Order], str],
    payload: dict | None = None,
) -> OrderOut:
    """Lock, transition, notify the customer, commit, tell the dashboard. No-op if repeated."""
    order = orders.lock_order(session, business.id, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    changed = action(order)
    if changed:
        notify_customer(session, order, message(order), payload=payload)
    session.commit()
    if changed:
        events.bus.publish(business.id, events.ORDER_UPDATED, order_id=order.id)
    return order_out(session, order)


@router.post("/{order_id}/approve", response_model=OrderOut)
def approve(
    order_id: uuid.UUID, session: SessionDep, business: CurrentBusiness, owner: CurrentOwner
) -> OrderOut:
    """Only from payment_check. Sends the fixed confirmation template."""
    return _act(
        session,
        business,
        order_id,
        lambda o: orders.approve(session, o, owner.id),
        templates.confirmed,
    )


@router.post("/{order_id}/not-received", response_model=OrderOut)
def not_received(order_id: uuid.UUID, session: SessionDep, business: CurrentBusiness) -> OrderOut:
    """payment_check → awaiting_payment; the customer is told and the timer restarts."""
    return _act(
        session,
        business,
        order_id,
        lambda o: orders.not_received(session, o, business),
        lambda o: templates.not_received(o, business),
    )


@router.post("/{order_id}/restore", response_model=OrderOut)
def restore(order_id: uuid.UUID, session: SessionDep, business: CurrentBusiness) -> OrderOut:
    """cancelled → payment_check, when the money arrived late. The customer is not messaged."""
    order = orders.lock_order(session, business.id, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    changed = orders.restore(session, order, business)
    session.commit()
    if changed:
        events.bus.publish(business.id, events.ORDER_UPDATED, order_id=order.id)
    return order_out(session, order)


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel(
    order_id: uuid.UUID, body: CancelIn, session: SessionDep, business: CurrentBusiness
) -> OrderOut:
    """Owner cancels. The reason is kept in the conversation log, not shown to the customer."""
    return _act(
        session,
        business,
        order_id,
        lambda o: orders.cancel(session, o, orders.CancelReason.owner_rejected),
        templates.cancelled_by_owner,
        payload={"reason": orders.CancelReason.owner_rejected, "owner_note": body.reason},
    )
