import re
import unicodedata
import uuid

from sqlmodel import Session, col, func, select

from app.models import MenuItem


def slugify(name: str) -> str:
    """'Mee Goreng (Special)!' -> 'mee_goreng_special'."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return text or "item"


def unique_slug(session: Session, business_id: uuid.UUID, name: str) -> str:
    base = slugify(name)
    taken = set(
        session.exec(
            select(MenuItem.slug).where(
                MenuItem.business_id == business_id, MenuItem.slug.startswith(base)
            )
        ).all()
    )
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


def next_sort_order(session: Session, business_id: uuid.UUID) -> int:
    current = session.exec(
        select(func.max(MenuItem.sort_order)).where(MenuItem.business_id == business_id)
    ).one()
    return (current or 0) + 1


def get_item(session: Session, business_id: uuid.UUID, item_id: uuid.UUID) -> MenuItem | None:
    return session.exec(
        select(MenuItem).where(
            MenuItem.id == item_id,
            MenuItem.business_id == business_id,
            col(MenuItem.deleted_at).is_(None),
        )
    ).first()
