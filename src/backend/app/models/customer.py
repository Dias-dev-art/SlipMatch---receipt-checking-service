import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Column, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import id_field, pg_enum, ts_field


class Customer(SQLModel, table=True):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("business_id", "tg_chat_id", name="uq_customers_business_chat"),
    )

    id: uuid.UUID = id_field()
    # the same Telegram user can be a customer of many businesses
    business_id: uuid.UUID = Field(foreign_key="businesses.id", index=True)
    tg_chat_id: str
    tg_username: str | None = None  # without @; not every Telegram user has one
    # shared by the customer with Telegram's button at checkout; digits, E.164 without +
    phone: str | None = None
    display_name: str | None = None  # Telegram first + last name
    created_at: datetime = ts_field()


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: uuid.UUID = id_field()
    business_id: uuid.UUID = Field(foreign_key="businesses.id", index=True)
    customer_id: uuid.UUID = Field(foreign_key="customers.id", index=True)
    # handoff flag; AI silent while true
    needs_owner: bool = False
    handoff_reason: str | None = None
    # when needs_owner was set; the AI resumes by itself 24h later
    handoff_at: datetime | None = ts_field(nullable=True, default=None)
    # owner takeover
    ai_paused_until: datetime | None = ts_field(nullable=True, default=None)
    # for the 24h window
    last_customer_message_at: datetime = ts_field()
    created_at: datetime = ts_field()


class Direction(StrEnum):
    in_ = "in"
    out = "out"


class Sender(StrEnum):
    customer = "customer"
    ai = "ai"
    owner = "owner"
    system = "system"


class MessageType(StrEnum):
    text = "text"
    image = "image"
    location = "location"
    audio = "audio"
    other = "other"


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id: uuid.UUID = id_field()
    business_id: uuid.UUID = Field(foreign_key="businesses.id", index=True)
    conversation_id: uuid.UUID = Field(foreign_key="conversations.id")
    direction: Direction = Field(sa_type=pg_enum(Direction, "message_direction"))
    sender: Sender = Field(sa_type=pg_enum(Sender, "message_sender"))
    tg_message_id: str | None = None
    type: MessageType = Field(
        default=MessageType.text, sa_type=pg_enum(MessageType, "message_type")
    )
    body: str | None = None
    # location, media id, tool calls for debugging
    payload: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB))
    created_at: datetime = ts_field()
