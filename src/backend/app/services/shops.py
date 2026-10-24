"""Shop codes: how a customer of the shared Telegram bot reaches one business.

The link t.me/<bot>?start=<shop_code> opens the bot; Telegram then sends `/start <shop_code>`.
"""

import re
import unicodedata

from sqlmodel import Session, select

from app.core.config import settings
from app.models import Business

# Telegram allows A-Z a-z 0-9 _ - in a start parameter (max 64); we keep it short and lowercase
SHOP_CODE_PATTERN = r"^[a-z0-9][a-z0-9-]{2,31}$"


def shop_code_from_name(name: str) -> str:
    """'Kak Ani Kitchen!' -> 'kak-ani-kitchen'."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:28].strip("-")
    return text if len(text) >= 3 else "shop"


def unique_shop_code(session: Session, name: str) -> str:
    base = shop_code_from_name(name)
    taken = set(
        session.exec(select(Business.shop_code).where(Business.shop_code.startswith(base))).all()
    )
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def by_code(session: Session, code: str | None) -> Business | None:
    if not code:
        return None
    return session.exec(select(Business).where(Business.shop_code == code.lower())).first()


def telegram_link(business: Business) -> str | None:
    if not settings.TELEGRAM_BOT_USERNAME:
        return None
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME.lstrip('@')}?start={business.shop_code}"
