"""Telegram webhook (public). Answer fast; the real work runs in the background.

One shared bot serves every business. A chat belongs to the shop whose link the customer opened
(`/start <shop_code>`), or to TELEGRAM_DEFAULT_SHOP.
"""

import hmac
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session

from app.core import db
from app.core.config import settings
from app.models import Business, MessageType, ProcessedWebhook, TelegramChat
from app.models.base import utcnow
from app.services import media, shops, templates
from app.services.pipeline import handle_contact, handle_incoming, mask_id, send_welcome
from app.telegram import parser
from app.telegram.client import BotClient, TelegramOutbox, bot

log = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def valid_secret(header: str | None) -> bool:
    """Telegram repeats the secret given to setWebhook in every call."""
    secret = settings.TELEGRAM_WEBHOOK_SECRET
    return bool(secret and header and hmac.compare_digest(header, secret))


@router.post("/telegram/webhook")
async def receive(request: Request, background: BackgroundTasks) -> dict[str, str]:
    if not valid_secret(request.headers.get(SECRET_HEADER)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad secret token")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body is not JSON") from None
    update = parser.parse(payload)
    if update:
        background.add_task(process, update)
    return {"status": "ok"}


# ---------------------------------------------------------------- background


def _first_time(session: Session, update_id: int) -> bool:
    """Telegram retries deliveries: record the id, and only the first delivery goes on."""
    inserted = session.exec(
        insert(ProcessedWebhook)
        .values(update_key=f"tg:{update_id}", received_at=utcnow())
        .on_conflict_do_nothing()
        .returning(ProcessedWebhook.update_key)
    ).first()
    session.commit()
    return inserted is not None


def bind_chat(session: Session, chat_id: str, business_id: uuid.UUID) -> None:
    """This chat now orders from this shop (opening another shop's link switches)."""
    now = utcnow()
    session.exec(
        insert(TelegramChat)
        .values(chat_id=chat_id, business_id=business_id, updated_at=now)
        .on_conflict_do_update(
            index_elements=["chat_id"], set_={"business_id": business_id, "updated_at": now}
        )
    )


def business_for_chat(session: Session, chat_id: str) -> Business | None:
    chat = session.get(TelegramChat, chat_id)
    if chat is not None:
        return session.get(Business, chat.business_id)
    return shops.by_code(session, settings.TELEGRAM_DEFAULT_SHOP)


def _save_photo(
    session: Session, client: BotClient, business_id: uuid.UUID, file_id: str
) -> str | None:
    downloaded = client.download_file(file_id)
    if not downloaded:
        return None
    data, mime = downloaded
    ext = media.IMAGE_TYPES.get(mime)
    return media.save(session, business_id, "proof", ext, data) if ext else None


def process_update(update: parser.ParsedUpdate) -> str:
    client = bot()
    if client is None:
        log.warning("Telegram update ignored: TELEGRAM_BOT_TOKEN is not set")
        return "no_token"
    with Session(db.engine) as session:
        if not _first_time(session, update.update_id):
            return "duplicate"
        outbox = TelegramOutbox(client, session)

        if update.start_code is not None:
            business = shops.by_code(session, update.start_code) or business_for_chat(
                session, update.chat_id
            )
            if business is None:
                outbox.send_text(update.chat_id, templates.OPEN_SHOP_LINK)
                return "no_shop"
            bind_chat(session, update.chat_id, business.id)
            return send_welcome(
                session, business, update.to_incoming(business.id), update.first_name, outbox
            )

        business = business_for_chat(session, update.chat_id)
        if business is None:
            log.info("chat %s has no shop yet", mask_id(update.chat_id))
            outbox.send_text(update.chat_id, templates.OPEN_SHOP_LINK)
            return "no_shop"
        if update.contact_phone:
            return handle_contact(
                session, update.to_incoming(business.id), update.contact_phone, outbox
            ).outcome
        client.send_typing(update.chat_id)
        media_url = None
        if update.type == MessageType.image and update.file_id:
            media_url = _save_photo(session, client, business.id, update.file_id)
        result = handle_incoming(session, update.to_incoming(business.id, media_url), outbox)
        return result.outcome


def process(update: parser.ParsedUpdate) -> None:
    try:
        process_update(update)
    except Exception:  # a bad update must not take the server down
        log.exception("Telegram update failed")
