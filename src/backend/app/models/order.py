import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Index, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from app.models.base import id_field, money_field, pg_enum, ts_field, utcnow


class OrderStatus(StrEnum):
    chatting = "chatting"
    awaiting_payment = "awaiting_payment"
    payment_check = "payment_check"
    approved = "approved"
    cancelled = "cancelled"


ACTIVE_STATUSES = (OrderStatus.chatting, OrderStatus.awaiting_payment, OrderStatus.payment_check)


class OrderType(StrEnum):
    pickup = "pickup"
    delivery = "delivery"


class Order(SQLModel, table=True):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("business_id", "code", name="uq_orders_business_code"),
        Index("ix_orders_status_expires", "status", "expires_at"),
        Index(
            "ix_orders_business_status_created", "business_id", "status", text("created_at DESC")
        ),
        # at most one active order per conversation
        Index(
            "uq_orders_one_active_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status IN ('chatting', 'awaiting_payment', 'payment_check')"),
        ),
    )

    id: uuid.UUID = id_field()
    business_id: uuid.UUID = Field(foreign_key="businesses.id", index=True)
    conversation_id: uuid.UUID = Field(foreign_key="conversations.id")
    customer_id: uuid.UUID = Field(foreign_key="customers.id")
    # short human code, unique per business; payment reference
    code: str
    status: OrderStatus = Field(
        default=OrderStatus.chatting, sa_type=pg_enum(OrderStatus, "order_status")
    )
    order_type: OrderType | None = Field(
        default=None, sa_type=pg_enum(OrderType, "order_type"), nullable=True
    )
    address_text: str | None = None
    location_lat: Decimal | None = Field(default=None, max_digits=9, decimal_places=6)
    location_lng: Decimal | None = Field(default=None, max_digits=9, decimal_places=6)
    subtotal: Decimal = money_field(Decimal("0.00"))  # computed by Python
    delivery_fee: Decimal = money_field(Decimal("0.00"))  # copied from business at the time
    total: Decimal = money_field(Decimal("0.00"))  # frozen at awaiting_payment
    payment_proof_media_url: str | None = None  # screenshot, hint only
    expires_at: datetime | None = ts_field(nullable=True, default=None)
    approved_by: uuid.UUID | None = Field(default=None, foreign_key="owners.id")
    approved_at: datetime | None = ts_field(nullable=True, default=None)
    # payment_timeout, owner_timeout, owner_rejected, customer
    cancelled_reason: str | None = None
    created_at: datetime = ts_field()
    updated_at: datetime = ts_field(default_factory=utcnow)


class OrderItem(SQLModel, table=True):
    __tablename__ = "order_items"

    id: uuid.UUID = id_field()
    order_id: uuid.UUID = Field(foreign_key="orders.id", index=True)
    menu_item_id: uuid.UUID = Field(foreign_key="menu_items.id")
    name_snapshot: str  # menu may change later
    unit_price_snapshot: Decimal = money_field()
    qty: int = Field(gt=0)
    note: str | None = None  # "less spicy"
