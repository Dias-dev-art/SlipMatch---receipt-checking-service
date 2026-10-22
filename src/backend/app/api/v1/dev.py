"""Dev only (ENV=dev): run the real pipeline without WhatsApp."""

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlmodel import col, select

from app.core.deps import CurrentBusiness, SessionDep
from app.models import Conversation, Customer, Message, Order, OrderItem
from app.schemas.order import OrderOut, order_out
from app.services.pipeline import CollectingOutbox, IncomingMessage, handle_incoming

router = APIRouter(prefix="/dev", tags=["dev"])


class SimulateIn(BaseModel):
    customer_phone: str = Field(pattern=r"^\d{8,15}$", examples=["60123456789"])
    text: str = Field(min_length=1, max_length=2000)


class SimulateOut(BaseModel):
    reply: str | None
    order: OrderOut | None
    # what would have been sent to WhatsApp (payment QR + reference, reply...)
    sent: list[dict[str, Any]]
    outcome: str


@router.post("/simulate", response_model=SimulateOut)
def simulate(body: SimulateIn, session: SessionDep, business: CurrentBusiness) -> SimulateOut:
    outbox = CollectingOutbox()
    result = handle_incoming(
        session,
        IncomingMessage(
            business_id=business.id, customer_phone=body.customer_phone, text=body.text
        ),
        outbox,
    )
    return SimulateOut(
        reply=result.reply,
        order=order_out(session, result.order) if result.order else None,
        sent=outbox.sent,
        outcome=result.outcome,
    )


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset(session: SessionDep, business: CurrentBusiness) -> None:
    """Wipe conversations and orders of the owner's business (menu and settings stay)."""
    order_ids = select(Order.id).where(Order.business_id == business.id)
    session.exec(delete(OrderItem).where(col(OrderItem.order_id).in_(order_ids)))
    session.exec(delete(Order).where(Order.business_id == business.id))
    session.exec(delete(Message).where(Message.business_id == business.id))
    session.exec(delete(Conversation).where(Conversation.business_id == business.id))
    session.exec(delete(Customer).where(Customer.business_id == business.id))
    session.commit()
