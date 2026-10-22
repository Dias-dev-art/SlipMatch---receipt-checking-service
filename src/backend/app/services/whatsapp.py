"""Meta WhatsApp Cloud API (Graph API): send text and images, download media.

Send errors are logged, never raised: the message is already stored in the conversation and the
customer flow must not crash because Meta is slow. Tokens and full phone numbers are never logged.
"""

import logging
import uuid

import httpx
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import TokenEncryptionError, decrypt_token
from app.models import WhatsAppAccount

log = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com"
TIMEOUT = 15.0
MAX_MEDIA_BYTES = 5 * 1024 * 1024

# tests replace this with httpx.MockTransport
_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=_transport)


class GraphClient:
    def __init__(self, phone_number_id: str, token: str) -> None:
        self.phone_number_id = phone_number_id
        self._headers = {"Authorization": f"Bearer {token}"}
        self._base = f"{GRAPH_URL}/{settings.WHATSAPP_GRAPH_VERSION}"

    def _send(self, payload: dict) -> bool:
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", **payload}
        try:
            with _client() as http:
                resp = http.post(
                    f"{self._base}/{self.phone_number_id}/messages",
                    headers=self._headers,
                    json=body,
                )
        except httpx.HTTPError as exc:
            log.warning("WhatsApp send failed: %s", type(exc).__name__)
            return False
        if resp.status_code >= 400:
            # Meta's error body has no secrets; 131047 = outside the 24h window
            log.warning("WhatsApp send rejected %s: %s", resp.status_code, resp.text[:300])
            return False
        return True

    def send_text(self, to: str, text: str) -> bool:
        return self._send({"to": to, "type": "text", "text": {"preview_url": False, "body": text}})

    def send_image(self, to: str, link: str, caption: str | None = None) -> bool:
        image = {"link": link} | ({"caption": caption} if caption else {})
        return self._send({"to": to, "type": "image", "image": image})

    def download_media(self, media_id: str) -> tuple[bytes, str] | None:
        """Two steps: media id → short-lived URL, then the bytes (same bearer token)."""
        try:
            with _client() as http:
                meta = http.get(f"{self._base}/{media_id}", headers=self._headers)
                meta.raise_for_status()
                info = meta.json()
                resp = http.get(info["url"], headers=self._headers)
                resp.raise_for_status()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("WhatsApp media download failed: %s", type(exc).__name__)
            return None
        if len(resp.content) > MAX_MEDIA_BYTES:
            log.warning("WhatsApp media too large, skipped")
            return None
        mime = info.get("mime_type") or resp.headers.get("content-type", "")
        return resp.content, mime.split(";")[0].strip()


class WhatsAppOutbox:
    """`services.outbox.Outbox` that really sends through the business's number."""

    def __init__(self, client: GraphClient) -> None:
        self.client = client

    def send_text(self, to: str, text: str) -> None:
        self.client.send_text(to, text)

    def send_image(self, to: str, image_url: str, caption: str | None = None) -> None:
        self.client.send_image(to, image_url, caption)


def account_for_business(session: Session, business_id: uuid.UUID) -> WhatsAppAccount | None:
    return session.exec(
        select(WhatsAppAccount).where(WhatsAppAccount.business_id == business_id)
    ).first()


def account_for_number(session: Session, phone_number_id: str) -> WhatsAppAccount | None:
    return session.exec(
        select(WhatsAppAccount).where(WhatsAppAccount.phone_number_id == phone_number_id)
    ).first()


def client_for(account: WhatsAppAccount) -> GraphClient | None:
    try:
        token = decrypt_token(account.access_token_encrypted)
    except TokenEncryptionError as exc:
        log.error("cannot use WhatsApp token of business %s: %s", account.business_id, exc)
        return None
    return GraphClient(account.phone_number_id, token)
