"""Meta webhook payload → our messages. Tolerant: unknown or broken parts are skipped.

Two change fields matter:
- `messages`: a customer wrote to the business number.
- `smb_message_echoes` (coexistence): the owner wrote from the WhatsApp Business app.
Delivery `statuses` and everything else are ignored.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models import MessageType
from app.services.pipeline import IncomingMessage


@dataclass
class ParsedMessage:
    phone_number_id: str  # the business number, resolves the tenant
    wa_message_id: str
    customer_phone: str
    type: MessageType
    text: str | None = None
    display_name: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    media_id: str | None = None

    def to_incoming(self, business_id: uuid.UUID, media_url: str | None = None) -> IncomingMessage:
        return IncomingMessage(
            business_id=business_id,
            customer_phone=self.customer_phone,
            type=self.type,
            text=self.text,
            display_name=self.display_name,
            wa_message_id=self.wa_message_id,
            latitude=self.latitude,
            longitude=self.longitude,
            media_id=self.media_id,
            media_url=media_url,
        )


@dataclass
class OwnerEcho:
    phone_number_id: str
    wa_message_id: str
    customer_phone: str
    text: str | None


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError):
        return None


def _message(raw: dict, phone_number_id: str, names: dict[str, str]) -> ParsedMessage | None:
    msg_id, sender, kind = raw.get("id"), raw.get("from"), raw.get("type")
    if not (isinstance(msg_id, str) and isinstance(sender, str) and isinstance(kind, str)):
        return None
    parsed = ParsedMessage(
        phone_number_id=phone_number_id,
        wa_message_id=msg_id,
        customer_phone=sender,
        type=MessageType.other,
        display_name=names.get(sender),
    )
    body = raw.get(kind) if isinstance(raw.get(kind), dict) else {}
    if kind == "text":
        parsed.type, parsed.text = MessageType.text, body.get("body")
    elif kind == "interactive":  # a tapped button or list row reads like text
        reply = body.get("button_reply") or body.get("list_reply") or {}
        parsed.type, parsed.text = MessageType.text, reply.get("title")
    elif kind == "button":
        parsed.type, parsed.text = MessageType.text, body.get("text")
    elif kind == "location":
        parsed.type = MessageType.location
        parsed.latitude = _decimal(body.get("latitude"))
        parsed.longitude = _decimal(body.get("longitude"))
    elif kind == "image":
        parsed.type, parsed.media_id, parsed.text = (
            MessageType.image,
            body.get("id"),
            body.get("caption"),
        )
    elif kind == "audio":
        parsed.type = MessageType.audio
    return parsed


def _echo(raw: dict, phone_number_id: str) -> OwnerEcho | None:
    msg_id, to = raw.get("id"), raw.get("to")
    if not (isinstance(msg_id, str) and isinstance(to, str)):
        return None
    text = raw["text"].get("body") if isinstance(raw.get("text"), dict) else None
    return OwnerEcho(phone_number_id, msg_id, to, text)


def parse(payload: Any) -> tuple[list[ParsedMessage], list[OwnerEcho]]:
    messages: list[ParsedMessage] = []
    echoes: list[OwnerEcho] = []
    if not isinstance(payload, dict):
        return messages, echoes
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
            if not isinstance(phone_number_id, str):
                continue
            field = change.get("field")
            if field == "messages":
                names = {
                    c.get("wa_id"): (c.get("profile") or {}).get("name")
                    for c in value.get("contacts") or []
                    if isinstance(c, dict)
                }
                for raw in value.get("messages") or []:
                    if isinstance(raw, dict) and (m := _message(raw, phone_number_id, names)):
                        messages.append(m)
            elif field == "smb_message_echoes":
                for raw in value.get("message_echoes") or []:
                    if isinstance(raw, dict) and (e := _echo(raw, phone_number_id)):
                        echoes.append(e)
    return messages, echoes
