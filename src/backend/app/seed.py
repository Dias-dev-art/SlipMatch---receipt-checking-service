"""Demo data: `uv run python -m app.seed`. Idempotent."""

from decimal import Decimal

from sqlmodel import Session, select

from app.core.db import engine
from app.core.security import hash_password
from app.models import Business, MenuItem, Owner

DEMO_EMAIL = "demo@demo.my"
DEMO_PASSWORD = "demo1234"

MENU = [
    (
        "nasi_lemak",
        "Nasi Lemak",
        "8.00",
        "Coconut rice, sambal, fried anchovies, peanuts, cucumber, boiled egg.",
        ["spicy", "halal", "contains egg", "contains peanuts"],
        "Rice",
    ),
    (
        "mee_goreng",
        "Mee Goreng",
        "7.00",
        "Fried yellow noodles with chicken, egg, vegetables and sweet-spicy sauce.",
        ["spicy", "halal", "contains egg"],
        "Noodles",
    ),
    (
        "roti_canai",
        "Roti Canai",
        "2.00",
        "Flaky flatbread served with dhal curry.",
        ["halal", "vegetarian"],
        "Bread",
    ),
    (
        "teh_tarik",
        "Teh Tarik",
        "3.00",
        "Pulled milk tea, sweet.",
        ["halal", "vegetarian"],
        "Drinks",
    ),
]


def seed(session: Session) -> Business:
    owner = session.exec(select(Owner).where(Owner.email == DEMO_EMAIL)).first()
    if owner is None:
        owner = Owner(
            email=DEMO_EMAIL, hashed_password=hash_password(DEMO_PASSWORD), full_name="Kak Ani"
        )
        session.add(owner)
        session.flush()
    business = session.exec(select(Business).where(Business.owner_id == owner.id)).first()
    if business is None:
        business = Business(
            owner_id=owner.id,
            name="Kak Ani Kitchen",
            delivery_enabled=True,
            delivery_fee=Decimal("3.00"),
            pickup_enabled=True,
            payment_instructions="DuitNow to Kak Ani Kitchen, Bank Harimau 1234567890",
        )
        session.add(business)
        session.flush()
    existing = set(session.exec(select(MenuItem.slug).where(MenuItem.business_id == business.id)))
    for order, (slug, name, price, description, tags, category) in enumerate(MENU, start=1):
        if slug not in existing:
            session.add(
                MenuItem(
                    business_id=business.id,
                    slug=slug,
                    name=name,
                    price=Decimal(price),
                    description=description,
                    tags=tags,
                    category=category,
                    sort_order=order,
                )
            )
    session.commit()
    session.refresh(business)
    return business


if __name__ == "__main__":
    with Session(engine) as s:
        b = seed(s)
    print(f"Seeded '{b.name}'. Login: {DEMO_EMAIL} / {DEMO_PASSWORD}")
