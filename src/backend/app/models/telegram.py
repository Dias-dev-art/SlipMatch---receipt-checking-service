import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import ts_field


class TelegramChat(SQLModel, table=True):
    """Which shop a customer's chat with the shared bot is ordering from (set by /start <code>)."""

    __tablename__ = "telegram_chats"

    chat_id: str = Field(primary_key=True)
    business_id: uuid.UUID = Field(foreign_key="businesses.id", index=True)
    updated_at: datetime = ts_field()


class ProcessedWebhook(SQLModel, table=True):
    """Dedupe Telegram retries: one row per update, key `tg:<update_id>`."""

    __tablename__ = "processed_webhooks"

    update_key: str = Field(primary_key=True)
    received_at: datetime = ts_field()
