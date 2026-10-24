"""Telegram Bot API: send text and photos, download photos, register the webhook.

Send errors are logged, never raised: the message is already stored in the conversation and the
customer flow must not crash because Telegram is slow. The bot token is part of every API URL,
so URLs are never logged.
"""

import logging
from typing import Any

import httpx
from sqlmodel import Session

from app.core.config import settings
from app.services import media

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org"
TIMEOUT = 15.0
MAX_MEDIA_BYTES = 5 * 1024 * 1024
# Telegram serves files without a content type we can trust; photos are always JPEG
_TYPES_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

# Telegram only shares a phone number when the customer taps a request_contact button
SHARE_PHONE_KEYBOARD = {
    "keyboard": [[{"text": "📱 Share phone number", "request_contact": True}]],
    "one_time_keyboard": True,
    "resize_keyboard": True,
}
REMOVE_KEYBOARD = {"remove_keyboard": True}

# tests replace this with httpx.MockTransport
_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=_transport)


class BotClient:
    def __init__(self, token: str) -> None:
        self._token = token

    def _call(self, method: str, **request: Any) -> Any:
        """POST one Bot API method; its `result`, or None when it failed."""
        try:
            with _client() as http:
                resp = http.post(f"{API_URL}/bot{self._token}/{method}", **request)
        except httpx.HTTPError as exc:
            log.warning("Telegram %s failed: %s", method, type(exc).__name__)
            return None
        if resp.status_code >= 400:
            # the error body has no secrets; 403 = the customer blocked the bot
            log.warning("Telegram %s rejected %s: %s", method, resp.status_code, resp.text[:300])
            return None
        try:
            body = resp.json()
        except ValueError:
            return None
        return body.get("result") if body.get("ok") else None

    def send_text(
        self, chat_id: str, text: str, reply_markup: dict[str, Any] | None = None
    ) -> bool:
        payload = {"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": True}}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._call("sendMessage", json=payload) is not None

    def send_photo(
        self, chat_id: str, data: bytes, content_type: str, caption: str | None = None
    ) -> bool:
        """Uploads the bytes, so Telegram never needs to reach our /media links."""
        form = {"chat_id": chat_id} | ({"caption": caption} if caption else {})
        files = {"photo": ("photo", data, content_type)}
        return self._call("sendPhoto", data=form, files=files) is not None

    def send_photo_url(self, chat_id: str, url: str, caption: str | None = None) -> bool:
        payload = {"chat_id": chat_id, "photo": url} | ({"caption": caption} if caption else {})
        return self._call("sendPhoto", json=payload) is not None

    def send_typing(self, chat_id: str) -> None:
        """Shows "typing…" under the bot's name for ~5s, while the AI thinks."""
        self._call("sendChatAction", json={"chat_id": chat_id, "action": "typing"})

    def download_file(self, file_id: str) -> tuple[bytes, str] | None:
        """Two steps: file id → file_path (getFile), then the bytes from the file URL."""
        info = self._call("getFile", json={"file_id": file_id})
        path = info.get("file_path") if isinstance(info, dict) else None
        if not path:
            return None
        if (info.get("file_size") or 0) > MAX_MEDIA_BYTES:
            log.warning("Telegram file too large, skipped")
            return None
        try:
            with _client() as http:
                resp = http.get(f"{API_URL}/file/bot{self._token}/{path}")
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("Telegram file download failed: %s", type(exc).__name__)
            return None
        if len(resp.content) > MAX_MEDIA_BYTES:
            log.warning("Telegram file too large, skipped")
            return None
        mime = _TYPES_BY_EXT.get(path.rsplit(".", 1)[-1].lower(), "image/jpeg")
        return resp.content, mime

    def set_webhook(self, url: str, secret: str) -> bool:
        payload = {"url": url, "secret_token": secret, "allowed_updates": ["message"]}
        return self._call("setWebhook", json=payload) is not None


def bot() -> BotClient | None:
    """The shared bot, or None when TELEGRAM_BOT_TOKEN is not set."""
    return BotClient(settings.TELEGRAM_BOT_TOKEN) if settings.TELEGRAM_BOT_TOKEN else None


class TelegramOutbox:
    """`services.outbox.Outbox` that really sends to the customer's Telegram chat."""

    def __init__(self, client: BotClient, session: Session) -> None:
        self.client = client
        self.session = session

    def send_text(self, to: str, text: str, *, remove_keyboard: bool = False) -> None:
        self.client.send_text(to, text, REMOVE_KEYBOARD if remove_keyboard else None)

    def ask_phone(self, to: str, text: str) -> None:
        self.client.send_text(to, text, SHARE_PHONE_KEYBOARD)

    def send_image(self, to: str, image_url: str, caption: str | None = None) -> None:
        path = media.path_of(image_url)
        file = media.load(self.session, path) if path else None
        if file is not None:
            self.client.send_photo(to, file.data, file.content_type, caption)
        else:
            self.client.send_photo_url(to, image_url, caption)
