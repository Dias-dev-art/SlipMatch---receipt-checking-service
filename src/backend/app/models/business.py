import uuid
from datetime import datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel

from app.models.base import id_field, money_field, ts_field


class Owner(SQLModel, table=True):
    __tablename__ = "owners"

    id: uuid.UUID = id_field()
    email: str = Field(unique=True, index=True)
    hashed_password: str
    full_name: str
    is_active: bool = True
    created_at: datetime = ts_field()


class Business(SQLModel, table=True):
    __tablename__ = "businesses"

    id: uuid.UUID = id_field()
    # one owner, one business for MVP
    owner_id: uuid.UUID = Field(foreign_key="owners.id", unique=True)
    name: str
    delivery_enabled: bool = False
    delivery_fee: Decimal = money_field(Decimal("0.00"))
    pickup_enabled: bool = True
    payment_qr_url: str = ""
    payment_instructions: str = ""
    unique_amount_cents: bool = False
    payment_timeout_minutes: int = 10
    greeting: str | None = None
    created_at: datetime = ts_field()
