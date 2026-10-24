"""All tables are imported here so Alembic and tests see the full metadata."""

from app.models.business import Business, Owner
from app.models.customer import (
    Conversation,
    Customer,
    Direction,
    Message,
    MessageType,
    Sender,
)
from app.models.media import MediaFile
from app.models.menu import MenuItem
from app.models.order import ACTIVE_STATUSES, Order, OrderItem, OrderStatus, OrderType
from app.models.telegram import ProcessedWebhook, TelegramChat

__all__ = [
    "ACTIVE_STATUSES",
    "Business",
    "Conversation",
    "Customer",
    "Direction",
    "MediaFile",
    "MenuItem",
    "Message",
    "MessageType",
    "Order",
    "OrderItem",
    "OrderStatus",
    "OrderType",
    "Owner",
    "ProcessedWebhook",
    "Sender",
    "TelegramChat",
]
