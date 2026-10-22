"""Where messages to customers go: WhatsApp when the business connected a number, otherwise
logged only. The dev simulator and tests collect them instead."""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlmodel import Session

from app.services import whatsapp

log = logging.getLogger(__name__)


class Outbox(Protocol):
    def send_text(self, to: str, text: str) -> None: ...

    def send_image(self, to: str, image_url: str, caption: str | None = None) -> None: ...


@dataclass
class CollectingOutbox:
    """Dev simulator and tests: keep what would have been sent to WhatsApp."""

    sent: list[dict[str, Any]] = field(default_factory=list)

    def send_text(self, to: str, text: str) -> None:
        self.sent.append({"type": "text", "to": to, "text": text})

    def send_image(self, to: str, image_url: str, caption: str | None = None) -> None:
        self.sent.append({"type": "image", "to": to, "url": image_url, "caption": caption})


class LogOutbox:
    """No WhatsApp number connected: the message is stored in the conversation and logged."""

    def send_text(self, to: str, text: str) -> None:
        log.info("outbox (not sent, no WhatsApp number): text to %s***", to[:4])

    def send_image(self, to: str, image_url: str, caption: str | None = None) -> None:
        log.info("outbox (not sent, no WhatsApp number): image to %s***", to[:4])


_outbox: Outbox | None = None


def get_outbox(session: Session, business_id: uuid.UUID) -> Outbox:
    """Outbox for messages not triggered by a customer message (owner actions, timers)."""
    if _outbox is not None:
        return _outbox
    account = whatsapp.account_for_business(session, business_id)
    client = whatsapp.client_for(account) if account else None
    return whatsapp.WhatsAppOutbox(client) if client else LogOutbox()


def set_outbox(outbox: Outbox | None) -> None:
    global _outbox
    _outbox = outbox
