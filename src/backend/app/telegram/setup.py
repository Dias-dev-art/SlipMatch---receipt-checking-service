"""At startup: point the bot's webhook at this server and print each shop's link.

Runs on every start, so a new ngrok URL only needs a restart (PUBLIC_BASE_URL in .env).
"""

import logging

from sqlmodel import Session, col, select

from app.core import db
from app.core.config import settings
from app.models import Business
from app.services import shops
from app.telegram.client import bot

log = logging.getLogger(__name__)

WEBHOOK_PATH = "/telegram/webhook"
MAX_LINKS_LOGGED = 20


def register_webhook() -> bool:
    client = bot()
    if client is None:
        log.info("Telegram bot is off: TELEGRAM_BOT_TOKEN is not set")
        return False
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    if not base.startswith("https://"):
        log.warning("Telegram webhook not set: PUBLIC_BASE_URL must be https (ngrok in dev)")
        return False
    if not settings.TELEGRAM_WEBHOOK_SECRET:
        log.warning("Telegram webhook not set: TELEGRAM_WEBHOOK_SECRET is empty")
        return False
    if not client.set_webhook(base + WEBHOOK_PATH, settings.TELEGRAM_WEBHOOK_SECRET):
        return False
    log.info("Telegram webhook set: %s%s", base, WEBHOOK_PATH)
    return True


def log_shop_links() -> None:
    if not settings.TELEGRAM_BOT_USERNAME:
        log.info("Set TELEGRAM_BOT_USERNAME to get the shops' Telegram links")
        return
    with Session(db.engine) as session:
        businesses = session.exec(
            select(Business).order_by(col(Business.created_at)).limit(MAX_LINKS_LOGGED)
        ).all()
    for business in businesses:
        log.info("Telegram link for %s: %s", business.name, shops.telegram_link(business))


def on_startup() -> None:
    try:
        register_webhook()
        log_shop_links()
    except Exception:  # the dashboard must start even if Telegram or the DB is not ready
        log.exception("Telegram setup failed")
