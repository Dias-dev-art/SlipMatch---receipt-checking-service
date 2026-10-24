import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.models import Business
from app.services import media, shops


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    shop_code: str
    # customers open this to order; null until TELEGRAM_BOT_USERNAME is set
    telegram_link: str | None
    delivery_enabled: bool
    delivery_fee: Decimal
    pickup_enabled: bool
    payment_qr_url: str | None
    payment_instructions: str
    unique_amount_cents: bool
    payment_timeout_minutes: int
    greeting: str | None
    created_at: datetime


def business_out(session: Session, business: Business) -> BusinessOut:
    return BusinessOut(
        id=business.id,
        name=business.name,
        shop_code=business.shop_code,
        telegram_link=shops.telegram_link(business),
        delivery_enabled=business.delivery_enabled,
        delivery_fee=business.delivery_fee,
        pickup_enabled=business.pickup_enabled,
        payment_qr_url=media.absolute_url(business.payment_qr_url),
        payment_instructions=business.payment_instructions,
        unique_amount_cents=business.unique_amount_cents,
        payment_timeout_minutes=business.payment_timeout_minutes,
        greeting=business.greeting,
        created_at=business.created_at,
    )


class BusinessPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    # the end of the Telegram link; 409 if another business has it
    shop_code: Annotated[str, Field(pattern=shops.SHOP_CODE_PATTERN)] | None = None
    delivery_enabled: bool | None = None
    delivery_fee: Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)] | None = None
    pickup_enabled: bool | None = None
    payment_instructions: Annotated[str, Field(max_length=1000)] | None = None
    unique_amount_cents: bool | None = None
    payment_timeout_minutes: Annotated[int, Field(ge=1, le=120)] | None = None
    # empty string clears the custom greeting
    greeting: Annotated[str, Field(max_length=500)] | None = None
