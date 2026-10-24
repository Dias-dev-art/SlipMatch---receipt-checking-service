import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlmodel import Session

from app.models import Customer, Order, OrderStatus, OrderType
from app.services import media, orders


class OrderItemOut(BaseModel):
    id: uuid.UUID
    menu_item_id: uuid.UUID
    slug: str
    name: str
    unit_price: Decimal
    qty: int
    note: str | None


class CustomerOut(BaseModel):
    id: uuid.UUID
    display_name: str | None  # Telegram first + last name
    username: str | None  # Telegram @username, without @
    phone: str | None  # digits with country code, shared by the customer at checkout


def customer_out(customer: Customer) -> CustomerOut:
    return CustomerOut(
        id=customer.id,
        display_name=customer.display_name,
        username=customer.tg_username,
        phone=customer.phone,
    )


class OrderOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    customer: CustomerOut
    code: str
    status: OrderStatus
    order_type: OrderType | None
    address_text: str | None
    location_lat: Decimal | None
    location_lng: Decimal | None
    items: list[OrderItemOut]
    subtotal: Decimal
    delivery_fee: Decimal
    total: Decimal
    payment_proof_media_url: str | None
    expires_at: datetime | None
    approved_at: datetime | None
    cancelled_reason: str | None
    created_at: datetime
    updated_at: datetime


def order_out(session: Session, order: Order) -> OrderOut:
    # attribute access (not model_dump) so expired rows are reloaded after commit
    skip = {"items", "customer"}
    fields = {name: getattr(order, name) for name in OrderOut.model_fields if name not in skip}
    fields["payment_proof_media_url"] = media.absolute_url(order.payment_proof_media_url)
    customer = session.get(Customer, order.customer_id)
    return OrderOut(
        **fields,
        customer=customer_out(customer),
        items=[
            OrderItemOut(
                id=ln.item.id,
                menu_item_id=ln.item.menu_item_id,
                slug=ln.slug,
                name=ln.item.name_snapshot,
                unit_price=ln.item.unit_price_snapshot,
                qty=ln.item.qty,
                note=ln.item.note,
            )
            for ln in orders.cart_lines(session, order)
        ],
    )
