import uuid
from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import id_field, ts_field


class WhatsAppAccount(SQLModel, table=True):
    __tablename__ = "whatsapp_accounts"

    id: uuid.UUID = id_field()
    # one number per business for MVP
    business_id: uuid.UUID = Field(foreign_key="businesses.id", unique=True)
    # from Meta, used to resolve the tenant on webhook
    phone_number_id: str = Field(unique=True)
    display_phone: str
    # Fernet, never returned by the API
    access_token_encrypted: str
    # number also used in the WhatsApp Business app
    coexistence: bool = False
    created_at: datetime = ts_field()


class ContactExclusion(SQLModel, table=True):
    """Numbers the AI never answers (friends, family, suppliers)."""

    __tablename__ = "contact_exclusions"
    __table_args__ = (
        UniqueConstraint("business_id", "wa_phone", name="uq_contact_exclusions_business_phone"),
    )

    id: uuid.UUID = id_field()
    business_id: uuid.UUID = Field(foreign_key="businesses.id", index=True)
    wa_phone: str  # E.164 without +
    label: str = ""  # "Mum", "Supplier"


class ProcessedWebhook(SQLModel, table=True):
    """Dedupe Meta retries: one row per WhatsApp message id."""

    __tablename__ = "processed_webhooks"

    wa_message_id: str = Field(primary_key=True)
    received_at: datetime = ts_field()
