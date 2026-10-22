import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    business_name: str = Field(min_length=1, max_length=255)


class OwnerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    created_at: datetime


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    delivery_enabled: bool
    delivery_fee: Decimal
    pickup_enabled: bool
    payment_qr_url: str
    payment_instructions: str
    unique_amount_cents: bool
    payment_timeout_minutes: int
    greeting: str | None
    created_at: datetime


class OwnerWithBusiness(BaseModel):
    owner: OwnerOut
    business: BusinessOut
