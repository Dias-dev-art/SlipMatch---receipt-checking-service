"""Meta WhatsApp webhook (public). Answer within ~1s; the real work runs in the background."""

import hashlib
import hmac
import json
import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session

from app.core import db
from app.core.config import settings
from app.models import MessageType, ProcessedWebhook
from app.models.base import utcnow
from app.services import media, whatsapp
from app.services.pipeline import handle_incoming, handle_owner_echo, mask_phone
from app.webhook import parser

log = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])


@router.get("/webhook", response_class=PlainTextResponse)
def verify(
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str, Query(alias="hub.challenge")] = "",
) -> str:
    """Meta's one-time subscription check: echo the challenge if the token matches."""
    expected = settings.WHATSAPP_VERIFY_TOKEN
    if mode == "subscribe" and expected and token and hmac.compare_digest(token, expected):
        return challenge
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Verification failed")


def valid_signature(body: bytes, header: str | None) -> bool:
    """X-Hub-Signature-256 = 'sha256=' + HMAC-SHA256(app secret, raw body)."""
    secret = settings.WHATSAPP_APP_SECRET
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@router.post("/webhook")
async def receive(request: Request, background: BackgroundTasks) -> dict[str, str]:
    body = await request.body()
    if not valid_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad signature")
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body is not JSON") from None
    messages, echoes = parser.parse(payload)
    if messages or echoes:
        background.add_task(process, messages, echoes)
    return {"status": "ok"}


# ---------------------------------------------------------------- background


def _first_time(session: Session, wa_message_id: str) -> bool:
    """Meta retries deliveries: record the id, and only the first delivery goes on."""
    inserted = session.exec(
        insert(ProcessedWebhook)
        .values(wa_message_id=wa_message_id, received_at=utcnow())
        .on_conflict_do_nothing()
        .returning(ProcessedWebhook.wa_message_id)
    ).first()
    session.commit()
    return inserted is not None


def _save_image(
    session: Session, client: whatsapp.GraphClient, business_id, media_id: str
) -> str | None:
    downloaded = client.download_media(media_id)
    if not downloaded:
        return None
    data, mime = downloaded
    ext = media.IMAGE_TYPES.get(mime)
    return media.save(session, business_id, "proof", ext, data) if ext else None


def process_message(message: parser.ParsedMessage) -> str:
    with Session(db.engine) as session:
        if not _first_time(session, message.wa_message_id):
            return "duplicate"
        account = whatsapp.account_for_number(session, message.phone_number_id)
        if account is None:
            log.info("message for unknown WhatsApp number ignored")
            return "unknown_number"
        client = whatsapp.client_for(account)
        if client is None:
            return "no_token"
        media_url = None
        if message.type == MessageType.image and message.media_id:
            media_url = _save_image(session, client, account.business_id, message.media_id)
        result = handle_incoming(
            session,
            message.to_incoming(account.business_id, media_url),
            whatsapp.WhatsAppOutbox(client),
        )
        return result.outcome


def process_echo(echo: parser.OwnerEcho) -> str:
    with Session(db.engine) as session:
        if not _first_time(session, echo.wa_message_id):
            return "duplicate"
        account = whatsapp.account_for_number(session, echo.phone_number_id)
        if account is None:
            return "unknown_number"
        outcome = handle_owner_echo(
            session, account.business_id, echo.customer_phone, echo.text, echo.wa_message_id
        )
        log.info("owner replied by hand to %s: %s", mask_phone(echo.customer_phone), outcome)
        return outcome


def process(messages: list[parser.ParsedMessage], echoes: list[parser.OwnerEcho]) -> None:
    for message in messages:
        try:
            process_message(message)
        except Exception:  # one bad message must not stop the others
            log.exception("webhook message failed")
    for echo in echoes:
        try:
            process_echo(echo)
        except Exception:
            log.exception("webhook echo failed")
