"""Telegram `Update` → our message. Tolerant: unknown or broken parts are skipped.

Only new messages in private chats matter. Edited messages, groups, channels and other bots
are ignored.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models import MessageType
from app.services.pipeline import IncomingMessage


@dataclass
class ParsedUpdate:
    update_id: int
    chat_id: str
    message_id: str
    type: MessageType
    text: str | None = None
    first_name: str | None = None
    display_name: str | None = None
    username: str | None = None  # Telegram @username without @, when the user has one
    # the customer's own number, from the "Share phone number" button
    contact_phone: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    file_id: str | None = None  # photo, or an image sent as a file
    # set for /start: the shop code after it ("" when the bot was opened without a shop link)
    start_code: str | None = None

    def to_incoming(self, business_id: uuid.UUID, media_url: str | None = None) -> IncomingMessage:
        return IncomingMessage(
            business_id=business_id,
            chat_id=self.chat_id,
            type=self.type,
            text=self.text,
            display_name=self.display_name,
            username=self.username,
            message_id=self.message_id,
            latitude=self.latitude,
            longitude=self.longitude,
            media_id=self.file_id,
            media_url=media_url,
        )


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError):
        return None


def _name(user: dict) -> tuple[str | None, str | None]:
    first = user.get("first_name") if isinstance(user.get("first_name"), str) else None
    last = user.get("last_name") if isinstance(user.get("last_name"), str) else None
    full = " ".join(p for p in (first, last) if p) or None
    return first, full


def parse(payload: Any) -> ParsedUpdate | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("update_id"), int):
        return None
    msg = payload.get("message")
    if not isinstance(msg, dict):
        return None
    chat = msg.get("chat") if isinstance(msg.get("chat"), dict) else {}
    user = msg.get("from") if isinstance(msg.get("from"), dict) else {}
    chat_id, message_id = chat.get("id"), msg.get("message_id")
    if chat.get("type") != "private" or not isinstance(chat_id, int) or user.get("is_bot"):
        return None
    if not isinstance(message_id, int):
        return None
    first, full = _name(user)
    username = user.get("username") if isinstance(user.get("username"), str) else None
    parsed = ParsedUpdate(
        update_id=payload["update_id"],
        chat_id=str(chat_id),
        message_id=str(message_id),
        type=MessageType.other,
        first_name=first,
        display_name=full,
        username=username,
    )
    caption = msg.get("caption") if isinstance(msg.get("caption"), str) else None
    document = msg.get("document") if isinstance(msg.get("document"), dict) else {}
    if isinstance(msg.get("text"), str):
        text = msg["text"].strip()
        command, _, rest = text.partition(" ")
        if command == "/start" or command.startswith("/start@"):
            parsed.start_code = rest.strip().lower()
        parsed.type, parsed.text = MessageType.text, text
    elif isinstance(msg.get("photo"), list) and msg["photo"]:
        # sizes come smallest first; the last one is the full picture
        biggest = msg["photo"][-1] if isinstance(msg["photo"][-1], dict) else {}
        parsed.type, parsed.file_id, parsed.text = (
            MessageType.image,
            biggest.get("file_id"),
            caption,
        )
    elif str(document.get("mime_type", "")).startswith("image/"):
        # a screenshot sent "as a file" keeps its full quality
        parsed.type, parsed.file_id, parsed.text = (
            MessageType.image,
            document.get("file_id"),
            caption,
        )
    elif isinstance(msg.get("location"), dict):
        parsed.type = MessageType.location
        parsed.latitude = _decimal(msg["location"].get("latitude"))
        parsed.longitude = _decimal(msg["location"].get("longitude"))
    elif isinstance(msg.get("contact"), dict):
        contact = msg["contact"]
        # only the customer's own number: anyone can forward somebody else's contact card
        if contact.get("user_id") == user.get("id") and isinstance(
            contact.get("phone_number"), str
        ):
            parsed.contact_phone = contact["phone_number"]
    elif any(k in msg for k in ("voice", "audio", "video_note")):
        parsed.type = MessageType.audio
    return parsed
