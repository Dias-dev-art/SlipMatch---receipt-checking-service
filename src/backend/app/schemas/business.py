import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.models import Business, WhatsAppAccount
from app.services import media


def _digits(phone: str) -> str:
    """'+60 12-345 6789' -> '60123456789' (E.164 without +, like WhatsApp sends it)."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not 8 <= len(digits) <= 15:
        raise ValueError("phone must have 8 to 15 digits")
    return digits


Phone = Annotated[str, AfterValidator(_digits)]


class WhatsAppOut(BaseModel):
    """The access token is never returned."""

    phone_number_id: str
    display_phone: str
    coexistence: bool


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    delivery_enabled: bool
    delivery_fee: Decimal
    pickup_enabled: bool
    payment_qr_url: str | None
    payment_instructions: str
    unique_amount_cents: bool
    payment_timeout_minutes: int
    greeting: str | None
    whatsapp: WhatsAppOut | None
    created_at: datetime


def business_out(session: Session, business: Business) -> BusinessOut:
    account = session.exec(
        select(WhatsAppAccount).where(WhatsAppAccount.business_id == business.id)
    ).first()
    return BusinessOut(
        id=business.id,
        name=business.name,
        delivery_enabled=business.delivery_enabled,
        delivery_fee=business.delivery_fee,
        pickup_enabled=business.pickup_enabled,
        payment_qr_url=media.absolute_url(business.payment_qr_url),
        payment_instructions=business.payment_instructions,
        unique_amount_cents=business.unique_amount_cents,
        payment_timeout_minutes=business.payment_timeout_minutes,
        greeting=business.greeting,
        whatsapp=WhatsAppOut.model_validate(account, from_attributes=True) if account else None,
        created_at=business.created_at,
    )


class BusinessPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    delivery_enabled: bool | None = None
    delivery_fee: Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)] | None = None
    pickup_enabled: bool | None = None
    payment_instructions: Annotated[str, Field(max_length=1000)] | None = None
    unique_amount_cents: bool | None = None
    payment_timeout_minutes: Annotated[int, Field(ge=1, le=120)] | None = None
    # empty string clears the custom greeting
    greeting: Annotated[str, Field(max_length=500)] | None = None


class WhatsAppIn(BaseModel):
    phone_number_id: Annotated[str, Field(pattern=r"^\d{5,30}$")]
    display_phone: Annotated[str, Field(min_length=1, max_length=30)]
    access_token: Annotated[str, Field(min_length=10, max_length=1000)]
    coexistence: bool = False


class ExclusionIn(BaseModel):
    wa_phone: Phone
    label: Annotated[str, Field(max_length=100)] = ""


class ExclusionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    wa_phone: str
    label: str
