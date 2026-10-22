"""Where messages to customers go. Dev/simulator collect them; step 6 adds WhatsApp."""

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

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
    """Until WhatsApp is connected: the message is stored in the conversation and logged."""

    def send_text(self, to: str, text: str) -> None:
        log.info("outbox (not sent, no WhatsApp yet): text to %s***", to[:4])

    def send_image(self, to: str, image_url: str, caption: str | None = None) -> None:
        log.info("outbox (not sent, no WhatsApp yet): image to %s***", to[:4])


_outbox: Outbox | None = None


def get_outbox() -> Outbox:
    """Outbox for messages not triggered by a customer message (owner actions, timers)."""
    return _outbox or LogOutbox()


def set_outbox(outbox: Outbox | None) -> None:
    global _outbox
    _outbox = outbox
