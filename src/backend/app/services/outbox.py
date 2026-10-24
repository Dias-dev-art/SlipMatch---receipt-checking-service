"""Where messages to customers go: Telegram when the bot token is set, otherwise logged only.
The dev simulator and tests collect them instead."""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlmodel import Session

from app.telegram.client import TelegramOutbox, bot

log = logging.getLogger(__name__)


class Outbox(Protocol):
    # remove_keyboard: hide the "Share phone number" button once it was used
    def send_text(self, to: str, text: str, *, remove_keyboard: bool = False) -> None: ...

    def send_image(self, to: str, image_url: str, caption: str | None = None) -> None: ...

    def ask_phone(self, to: str, text: str) -> None: ...


@dataclass
class CollectingOutbox:
    """Dev simulator and tests: keep what would have been sent to Telegram."""

    sent: list[dict[str, Any]] = field(default_factory=list)

    def send_text(self, to: str, text: str, *, remove_keyboard: bool = False) -> None:
        sent = {"type": "text", "to": to, "text": text}
        self.sent.append(sent | ({"remove_keyboard": True} if remove_keyboard else {}))

    def send_image(self, to: str, image_url: str, caption: str | None = None) -> None:
        self.sent.append({"type": "image", "to": to, "url": image_url, "caption": caption})

    def ask_phone(self, to: str, text: str) -> None:
        self.sent.append({"type": "ask_phone", "to": to, "text": text})


class LogOutbox:
    """No bot token configured: the message is stored in the conversation and logged."""

    def send_text(self, to: str, text: str, *, remove_keyboard: bool = False) -> None:
        log.info("outbox (not sent, no Telegram bot): text to %s***", to[:3])

    def send_image(self, to: str, image_url: str, caption: str | None = None) -> None:
        log.info("outbox (not sent, no Telegram bot): image to %s***", to[:3])

    def ask_phone(self, to: str, text: str) -> None:
        log.info("outbox (not sent, no Telegram bot): phone request to %s***", to[:3])


_outbox: Outbox | None = None


def get_outbox(session: Session, business_id: uuid.UUID) -> Outbox:
    """Outbox for messages not triggered by a customer message (owner actions, timers).

    One bot serves every business, so `business_id` does not change where messages go.
    """
    if _outbox is not None:
        return _outbox
    client = bot()
    return TelegramOutbox(client, session) if client else LogOutbox()


def set_outbox(outbox: Outbox | None) -> None:
    global _outbox
    _outbox = outbox
